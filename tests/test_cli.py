import json

from gwy_photo_mac.cli import main


def test_cli_json_success(photo_path, detector_stub, tmp_path, capsys):
    output = tmp_path / "output.jpg"
    assert main(["process", str(photo_path), "-o", str(output), "--json"]) == 0
    text = capsys.readouterr().out
    report = json.loads(text)
    assert report["ok"] is True
    assert str(tmp_path) not in text
    assert output.exists()


def test_cli_reports_error_without_creating_output(tmp_path, capsys):
    output = tmp_path / "output.jpg"
    assert main(["process", str(tmp_path / "missing.jpg"), "-o", str(output), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "read"
    assert not output.exists()


def test_cli_refuses_overwriting_original(photo_path, detector_stub, capsys):
    original = photo_path.read_bytes()
    assert main(["process", str(photo_path), "-o", str(photo_path), "--overwrite", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "source_overwrite"
    assert photo_path.read_bytes() == original
