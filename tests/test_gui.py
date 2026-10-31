import pytest

pytest.importorskip("PySide6")

from gwy_photo_mac.gui import PhotoWindow  # noqa: E402


def test_open_process_then_bad_input_clears_old_result(qtbot, photo_path, detector_stub, tmp_path):
    window = PhotoWindow()
    qtbot.addWidget(window)
    window.show()
    assert not window.save_button.isEnabled()
    window.load_photo(photo_path)
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.result is not None
    assert window.save_button.isEnabled()
    assert "检查通过" in window.status.text()
    bad = tmp_path / "bad.jpg"
    bad.write_text("invalid")
    window.load_photo(bad)
    assert window.result is None
    assert not window.save_button.isEnabled()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.result is None
    assert not window.save_action.isEnabled()
    assert "检查未通过" in window.status.text()


def test_configuration_change_invalidates_result(qtbot, photo_path, detector_stub):
    window = PhotoWindow()
    qtbot.addWidget(window)
    window.load_photo(photo_path)
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.result is not None
    window.png_checkbox.setChecked(True)
    assert window.result is None
    assert not window.save_button.isEnabled()
