import numpy as np
import pytest
from PIL import Image

from gwy_photo_mac import core


@pytest.fixture
def photo_path(tmp_path):
    path = tmp_path / "证件照片.jpg"
    image = np.full((826, 590, 3), 250, dtype=np.uint8)
    image[250:700, 160:440] = [180, 130, 110]
    Image.fromarray(image).save(path, quality=95)
    return path


@pytest.fixture
def detector_stub(monkeypatch):
    # Check deterministic pixel/geometry/save paths without shipping anyone's face.
    # The real detector is separately loaded and exercised on a blank negative image.
    monkeypatch.setattr(core, "detect_faces", lambda image: [(120, 180, 380, 380)])
