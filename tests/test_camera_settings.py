import json

from engine.camera_settings import CameraSettings


def test_legacy_grade_settings_become_neutral_look(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    (tmp_path / "camera-settings.json").write_text(json.dumps({
        "grade_enabled": True,
        "saturation": 1.4,
        "contrast": 1.3,
        "awb_mode": "indoor",
    }))

    settings = CameraSettings.load()

    assert settings.filter_name == "clean"
    assert settings.saturation == settings.contrast == settings.sharpness == 1.0
    assert settings.awb_mode == "auto"


def test_filter_settings_only_accept_known_looks():
    settings = CameraSettings()
    settings.merge({"filter_name": "warm", "filter_strength": 5})
    assert settings.filter_name == "warm"
    assert settings.filter_strength == 1.0
    settings.merge({"filter_name": "made-up"})
    assert settings.filter_name == "warm"


def test_saved_unknown_look_falls_back_to_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    (tmp_path / "camera-settings.json").write_text(json.dumps({"filter_name": "made-up"}))
    assert CameraSettings.load().filter_name == "clean"
