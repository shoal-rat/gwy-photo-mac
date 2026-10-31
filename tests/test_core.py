import hashlib
import io
import os
from dataclasses import replace
from importlib.resources import files

import numpy as np
import pytest
from PIL import Image

from gwy_photo_mac.core import (
    TRAILER,
    PhotoError,
    Settings,
    calculate_crop,
    check_background,
    classify_hsi,
    detect_faces,
    inspect_output,
    load_classifier,
    process_photo,
    write_output,
)


def test_reference_profile_and_executable_defaults(tmp_path):
    assert Settings.load().s_max == 0.1
    assert Settings.load().i_max == 0.7
    path = tmp_path / "photo.ini"
    path.write_text("[PhotoInfo]\nmin_width=400\n")
    cfg = Settings.load(path)
    assert cfg.min_width == 400
    assert cfg.s_max == 0.3
    assert cfg.i_max == 0.9


@pytest.mark.parametrize(
    "content",
    ["[PhotoInfo]\ns_max=nan", "[PhotoInfo]\ndst_width=0", "[PhotoInfo]\ni_min=2", "bad ini"],
)
def test_invalid_profile_is_readable_error(tmp_path, content):
    path = tmp_path / "photo.ini"
    path.write_text(content)
    with pytest.raises(PhotoError, match="无法读取配置"):
        Settings.load(path)


@pytest.mark.parametrize(
    "h,s,i,expected",
    [
        (0, 0.05, 0.7, "white"),
        (0, 0.050001, 0.7, "invalid"),
        (2.5, 0.1, 0.1, "blue"),
        (4.5, 0.1, 0.1, "blue"),
        (4.50001, 0.1, 0.1, "invalid"),
        (3, 1, 0.0999, "invalid"),
        (3, 1, 0.9, "blue"),
    ],
)
def test_hsi_boundary_cases(h, s, i, expected):
    assert classify_hsi(h, s, i, Settings.load()) == expected


@pytest.mark.parametrize("color,expected", [((255, 255, 255), "white"), ((0, 100, 200), "blue")])
def test_background_three_samples(color, expected):
    rgb = np.full((413, 295, 3), color, dtype=np.uint8)
    assert {sample.category for sample in check_background(rgb, Settings.load())} == {expected}


def test_mixed_background_rejected():
    rgb = np.full((413, 295, 3), 255, dtype=np.uint8)
    rgb[102:105, 28:31] = (0, 100, 200)
    with pytest.raises(PhotoError) as error:
        check_background(rgb, Settings.load())
    assert error.value.code == "background"


def test_crop_clamped_to_original_dimensions():
    geometry = calculate_crop((180, 270, 660, 660), (1000, 1400), Settings.load())
    assert geometry.crop == (0, 0, 1000, 1400)
    assert all(0 <= margin <= 0.5 for margin in geometry.margins)


@pytest.mark.parametrize("face", [(400, 300, 200, 200), (100, 1300, 340, 100), (0, 0, 0, 0)])
def test_invalid_head_geometry_rejected(face):
    with pytest.raises(PhotoError) as error:
        calculate_crop(face, (1060, 1484), Settings.load())
    assert error.value.code == "proportion"


def test_real_bundled_detector_loads_and_rejects_blank():
    model = files("gwy_photo_mac").joinpath("data/haarcascade_frontalface_alt2.xml").read_bytes()
    assert (
        hashlib.sha256(model).hexdigest()
        == "6e8fac74c150b1662166552056fdaf628de68332f25022c38f293b485f428f17"
    )
    assert not load_classifier().empty()
    assert detect_faces(np.full((413, 295, 3), 255, dtype=np.uint8)) == []


def test_end_to_end_output_unicode_filename(photo_path, detector_stub, tmp_path):
    original = photo_path.read_bytes()
    result = process_photo(photo_path)
    destination = tmp_path / "报名照片.JPG"
    write_output(result, destination, source=photo_path)
    assert photo_path.read_bytes() == original
    assert destination.read_bytes().endswith(b"\xff\xd9" + TRAILER)
    assert result.report["website_verified"] is False
    assert result.report["output_dimensions"] == [295, 413]
    assert result.report["jpeg_quality"] == 40
    assert "source" not in result.report
    with Image.open(io.BytesIO(result.jpeg)) as image:
        image.load()
        assert image.size == (295, 413)
        assert image.mode == "RGB"
        assert not image.getexif()


def test_small_input_rejected_before_detector(tmp_path, monkeypatch):
    path = tmp_path / "small.jpg"
    Image.new("RGB", (294, 413), "white").save(path)
    monkeypatch.setattr(
        "gwy_photo_mac.core.detect_faces", lambda _: pytest.fail("must reject before detector")
    )
    with pytest.raises(PhotoError) as error:
        process_photo(path)
    assert error.value.code == "pixels"


def test_largest_face_selected(photo_path, detector_stub, monkeypatch):
    monkeypatch.setattr(
        "gwy_photo_mac.core.detect_faces", lambda _: [(10, 10, 40, 40), (120, 180, 380, 380)]
    )
    assert process_photo(photo_path).report["selected_face"] == (120, 180, 380, 380)


def test_png_requires_explicit_conversion(photo_path, detector_stub, tmp_path):
    path = tmp_path / "photo.png"
    with Image.open(photo_path) as image:
        image.save(path)
    with pytest.raises(PhotoError) as error:
        process_photo(path)
    assert error.value.code == "format"
    result = process_photo(path, allow_png=True)
    assert result.report["png_conversion"] is True


def test_transparent_png_rejected(tmp_path):
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (295, 413), (255, 255, 255, 0)).save(path)
    with pytest.raises(PhotoError) as error:
        process_photo(path, allow_png=True)
    assert error.value.code == "transparency"


def test_file_content_checked_instead_of_extension(tmp_path):
    path = tmp_path / "pretending.jpg"
    Image.new("RGB", (295, 413), "white").save(path, format="PNG")
    with pytest.raises(PhotoError) as error:
        process_photo(path)
    assert error.value.code == "format"


def test_broken_image_rejected(tmp_path):
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"\xff\xd8broken")
    with pytest.raises(PhotoError) as error:
        process_photo(path)
    assert error.value.code == "read"


def test_output_marker_damage_rejected(photo_path, detector_stub):
    result = process_photo(photo_path)
    with pytest.raises(PhotoError):
        inspect_output(result.jpeg[:-1], (295, 413))


def test_overwrite_policy_and_source_aliases(photo_path, detector_stub, tmp_path):
    result = process_photo(photo_path)
    output = tmp_path / "output.jpg"
    output.write_bytes(b"previous")
    with pytest.raises(PhotoError) as error:
        write_output(result, output)
    assert error.value.code == "exists"
    assert output.read_bytes() == b"previous"
    write_output(result, output, overwrite=True)
    assert output.read_bytes() == result.jpeg
    for name, link in [("symlink.jpg", "symlink"), ("hardlink.jpg", "hardlink")]:
        alias = tmp_path / name
        if link == "symlink":
            alias.symlink_to(photo_path)
        else:
            os.link(photo_path, alias)
        with pytest.raises(PhotoError) as error:
            write_output(result, alias, overwrite=True, source=photo_path)
        assert error.value.code == "source_overwrite"


def test_custom_dimensions_are_used(photo_path, detector_stub):
    cfg = replace(Settings.load(), dst_width=215, dst_height=301)
    result = process_photo(photo_path, cfg)
    inspect_output(result.jpeg, (215, 301))
