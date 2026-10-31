"""Image checks, crop geometry, JPEG encoding, and the reference file trailer.

Function addresses refer to the PE32 image identified in docs/REVERSE_ENGINEERING.md.
No downloaded executable is executed at runtime. This module performs no networking.
"""

from __future__ import annotations

import configparser
import io
import math
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from . import __version__

TRAILER = bytes.fromhex("ff020008676a67777932")
JPEG_QUALITY = 40
REFERENCE_SHA256 = "e344fc1b4619d355d88a52bc1eddf216cca60fb55c8e9bab42ac5d4ed04183a9"
COMPATIBILITY_NOTICE = (
    "非官方复现：依据特定 Windows EXE 的原理实现，"
    "不保证与原版输出一致，不保证持续有效或被报名网站接受。"
)


class PhotoError(ValueError):
    """A user-readable validation error, also exposed by the CLI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Settings:
    # Compiled defaults in 0x4013A0; reference.ini overrides four values.
    min_width: int = 295
    min_height: int = 413
    dst_width: int = 295
    dst_height: int = 413
    ratio_x_min: float = 0.0
    ratio_x_max: float = 0.5
    ratio_y_min: float = 0.0
    ratio_y_max: float = 0.5
    blue_h_min: float = 2.5
    blue_h_max: float = 4.5
    # Read for profile fidelity; the analyzed classification branch does not use red.
    red_h_min: float = 0.0
    red_h_max: float = 5.0
    i_min: float = 0.1
    i_max: float = 0.9
    s_min: float = 0.05
    s_max: float = 0.3

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            if path is None:
                text = files("gwy_photo_mac").joinpath("data/reference.ini").read_text()
            else:
                text = Path(path).read_text(encoding="utf-8-sig")
            parser.read_string(text)
            section = parser["PhotoInfo"] if parser.has_section("PhotoInfo") else {}
            values = {}
            for field in fields(cls):
                if field.name in section:
                    value = float(section[field.name])
                    if not math.isfinite(value):
                        raise ValueError("配置必须是有限数字")
                    if field.name.endswith(("width", "height")):
                        if value != int(value) or not 3 <= value <= 10000:
                            raise ValueError("尺寸必须是3至10000之间的整数")
                        value = int(value)
                    values[field.name] = value
            result = cls(**values)
            for prefix in ("ratio_x", "ratio_y", "i", "s"):
                lo, hi = getattr(result, prefix + "_min"), getattr(result, prefix + "_max")
                if not 0 <= lo <= hi <= 1:
                    raise ValueError(f"{prefix}的上下界必须满足0 ≤ min ≤ max ≤ 1")
            for prefix in ("blue_h", "red_h"):
                lo, hi = getattr(result, prefix + "_min"), getattr(result, prefix + "_max")
                if not 0 <= lo <= hi <= 2 * math.pi:
                    raise ValueError("色相上下界必须介于0和2π之间")
            return result
        except (OSError, UnicodeError, ValueError, configparser.Error) as exc:
            raise PhotoError("config", f"无法读取配置：{exc}") from exc


@dataclass(frozen=True)
class Sample:
    x: int
    y: int
    hue: float
    saturation: float
    intensity: float
    category: str


@dataclass(frozen=True)
class Geometry:
    face: tuple[int, int, int, int]
    crop: tuple[int, int, int, int]
    margins: tuple[float, float, float]


@dataclass(frozen=True)
class ProcessedPhoto:
    jpeg: bytes
    report: dict

    def preview(self) -> Image.Image:
        with Image.open(io.BytesIO(self.jpeg)) as image:
            return image.convert("RGB")


def classify_hsi(hue: float, saturation: float, intensity: float, cfg: Settings) -> str:
    """0x401000: I floor, bright low-saturation white, or saturated blue."""
    if intensity < cfg.i_min:
        return "invalid"
    if intensity >= cfg.i_max and saturation <= cfg.s_min:
        return "white"
    if cfg.blue_h_min <= hue <= cfg.blue_h_max and saturation >= cfg.s_max:
        return "blue"
    return "invalid"


def check_background(rgb: np.ndarray, cfg: Settings) -> tuple[Sample, ...]:
    """0x401070: three 3×3 neighborhoods must have the same valid class."""
    h, w = rgb.shape[:2]
    points = ((w // 10, h // 10), (w // 10, h // 4), (w - w // 10, h // 6))
    samples = []
    for x, y in points:
        r, g, b = rgb[y - 1 : y + 2, x - 1 : x + 2].mean(axis=(0, 1)) / 255.0
        total = float(r + g + b)
        intensity = total / 3.0
        saturation = 1.0 - 3.0 * float(min(r, g, b)) / total if total else 0.0
        den = math.sqrt(max(0.0, float((r - g) ** 2 + (r - b) * (g - b))))
        hue = math.acos(max(-1.0, min(1.0, float((2 * r - g - b) / 2.0) / den))) if den else 0.0
        if g < b:
            hue = 6.28318 - hue  # Preserve the reference constant, not math.tau.
        category = classify_hsi(hue, saturation, intensity, cfg)
        samples.append(Sample(x, y, hue, saturation, intensity, category))
    categories = {sample.category for sample in samples}
    if "invalid" in categories or len(categories) != 1:
        raise PhotoError(
            "background",
            "打开照片文件背景不符合要求。请选择白色或蓝色背景照片文件。",
        )
    return tuple(samples)


def calculate_crop(
    face: tuple[int, int, int, int], size: tuple[int, int], cfg: Settings
) -> Geometry:
    """0x40196A–0x401BB6. int division uses C/C++ truncation toward zero."""
    x, y, fw, fh = map(int, face)
    w, h = size
    if w <= 0 or h <= 0 or fw <= 0 or fh <= 0 or fw / w < 0.32:
        raise PhotoError("proportion", "人像头部比例不符合要求。请选择头部比例适当的照片文件。")
    cw = int(fw * 1.6181229773462784)
    ch = int(cw * cfg.dst_height / cfg.dst_width + 0.5)
    cx, cy = x - int((cw - fw) / 2), y - int((ch - fh) / 2)
    if cw > w:
        cx, cw = 0, w
    else:
        cx = max(0, min(cx, w - cw))
    if ch > h:
        cy, ch = 0, h
    else:
        cy = max(0, min(cy, h - ch))
    ratio = ch * cfg.dst_width / (cw * cfg.dst_height)
    if ratio < 0.9:
        new_width = int(ch * cfg.dst_width / cfg.dst_height)
        cx += int((cw - new_width) / 2)
        cw = new_width
    elif ratio > 1.1:
        new_height = int(cw * cfg.dst_height / cfg.dst_width)
        cy += int((ch - new_height) / 2)
        ch = new_height
    if cw <= 0 or ch <= 0:
        raise PhotoError("proportion", "无法按当前配置裁切照片。")
    margins = ((x - cx) / cw, (cw - x - fw + cx) / cw, (y - cy) / ch)
    if not (
        cfg.ratio_x_min <= margins[0] <= cfg.ratio_x_max
        and cfg.ratio_x_min <= margins[1] <= cfg.ratio_x_max
        and cfg.ratio_y_min <= margins[2] <= cfg.ratio_y_max
    ):
        raise PhotoError("proportion", "人像头部比例不符合要求。请选择头部比例适当的照片文件。")
    return Geometry(tuple(map(int, face)), (cx, cy, cw, ch), margins)


@lru_cache(maxsize=1)
def load_classifier() -> cv2.CascadeClassifier:
    # The retained XML has its own Intel license, reproduced in THIRD_PARTY_NOTICES.
    path = files("gwy_photo_mac").joinpath("data/haarcascade_frontalface_alt2.xml")
    classifier = cv2.CascadeClassifier(str(path))
    if classifier.empty():
        raise PhotoError("detector", "无法载入随附的人脸检测器，请重新安装程序。")
    return classifier


def detect_faces(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    faces = load_classifier().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=2, flags=1, minSize=(30, 30)
    )
    return [tuple(map(int, row)) for row in faces]


def read_photo(path: Path, *, allow_png: bool = False) -> tuple[Image.Image, str, bool]:
    try:
        with Image.open(path) as source:
            format_name = source.format
            if format_name != "JPEG" and not (allow_png and format_name == "PNG"):
                raise PhotoError(
                    "format", "打开照片文件类型不是JPG/JPEG格式，请选择JPG/JPEG格式照片文件。"
                )
            rotated = source.getexif().get(274, 1) not in (None, 1)
            image = ImageOps.exif_transpose(source)
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                # Conversion is explicit and reported; no automatic background replacement.
                if rgba.getchannel("A").getextrema() != (255, 255):
                    raise PhotoError("transparency", "不支持透明背景照片，请使用不透明的证件照片。")
            return image.convert("RGB"), format_name, rotated
    except PhotoError:
        raise
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoError("read", "无法读取照片文件，文件可能损坏或不可访问。") from exc


def encode_jpeg(rgb: np.ndarray) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(rgb).save(
        stream,
        format="JPEG",
        quality=JPEG_QUALITY,
        subsampling=2,
        progressive=False,
        optimize=False,
        dpi=(96, 96),
    )
    return stream.getvalue() + TRAILER


def inspect_output(data: bytes, size: tuple[int, int]) -> None:
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9" + TRAILER):
        raise PhotoError("output", "输出文件格式或文件尾标记校验失败。")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format != "JPEG" or image.size != size or image.mode != "RGB":
                raise PhotoError("output", "输出文件尺寸或色彩模式校验失败。")
    except OSError as exc:
        raise PhotoError("output", "输出JPEG无法完整解码。") from exc


def process_photo(
    path: Path, cfg: Settings | None = None, *, allow_png: bool = False
) -> ProcessedPhoto:
    cfg = cfg or Settings.load()
    source, format_name, rotated = read_photo(Path(path), allow_png=allow_png)
    if source.width < cfg.min_width or source.height < cfg.min_height:
        raise PhotoError(
            "pixels",
            "打开照片文件像素数低。请选择高于或符合像素数要求的照片文件，禁止放大低像素照片。",
        )
    rgb = np.array(source)
    samples = check_background(rgb, cfg)
    faces = detect_faces(rgb)
    if not faces:
        raise PhotoError("face", "打开照片文件不符合要求。请选择正面人像标准证件照片文件。")
    # Match 0x401932: additional detections do not reject an image; largest wins.
    geometry = calculate_crop(max(faces, key=lambda face: face[2]), source.size, cfg)
    x, y, w, h = geometry.crop
    pixels = cv2.resize(
        rgb[y : y + h, x : x + w], (cfg.dst_width, cfg.dst_height), interpolation=cv2.INTER_LINEAR
    )
    data = encode_jpeg(pixels)
    inspect_output(data, (cfg.dst_width, cfg.dst_height))
    report = {
        "app_version": __version__,
        "reference_sha256": REFERENCE_SHA256,
        "compatibility_notice": COMPATIBILITY_NOTICE,
        "website_verified": False,
        "source_format": format_name,
        "source_dimensions": list(source.size),
        "png_conversion": format_name == "PNG",
        "exif_orientation_applied": rotated,
        "background": samples[0].category,
        "background_samples": [asdict(sample) for sample in samples],
        "detected_faces": faces,
        "selected_face": geometry.face,
        "crop_xywh": geometry.crop,
        "face_margins": geometry.margins,
        "settings": asdict(cfg),
        "output_dimensions": [cfg.dst_width, cfg.dst_height],
        "jpeg_quality": JPEG_QUALITY,
        "output_bytes": len(data),
        "trailer_hex": TRAILER.hex(),
        "opencv_version": cv2.__version__,
    }
    return ProcessedPhoto(data, report)


def write_output(
    result: ProcessedPhoto,
    destination: Path,
    *,
    overwrite: bool = False,
    source: Path | None = None,
) -> None:
    """Do not overwrite the source; reserve new output paths without a race."""
    destination = Path(destination).expanduser()
    if source is not None:
        source = Path(source).expanduser()
        same = destination.resolve() == source.resolve()
        if destination.exists() and source.exists():
            same = same or os.path.samefile(destination, source)
        if same:
            raise PhotoError("source_overwrite", "不能覆盖源照片，请选择另存位置。")
    try:
        if not overwrite:
            with destination.open("xb") as output:
                output.write(result.jpeg)
        else:
            # Atomic replacement keeps a pre-existing file intact on write failure.
            fd, temporary = tempfile.mkstemp(prefix=".gwy-photo-", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(result.jpeg)
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except FileExistsError as exc:
        raise PhotoError("exists", "目标文件已存在，请选择其他文件名或明确允许覆盖。") from exc
    except OSError as exc:
        raise PhotoError("write", f"保存失败：{exc.strerror or '无法写入目标文件'}") from exc
