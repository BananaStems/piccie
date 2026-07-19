import os

import pytest

os.environ["PICCIE_DATA_DIR"] = "/tmp/piccie-test-data"
from engine.config import ConfigStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    # Isolate from any real local.json on the dev machine.
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", tmp_path / "local.json")
    return ConfigStore(path=tmp_path / "config.json")


def test_ensure_creates_default_config(store):
    assert store.load() is None
    config = store.ensure()
    assert store.path.exists()
    again = store.ensure()
    assert again.active_event_id == config.active_event_id


def test_config_json_never_contains_r2_secrets(store):
    local = store.path.parent / "local.json"
    local.write_text(
        '{"r2":{"account_id":"acc","access_key":"key","secret_key":"secret",'
        '"bucket":"bucket","public_base_url":"https://cdn.example.com"}}'
    )
    config = store.ensure()
    assert config.r2 is not None
    assert config.r2.secret_key == "secret"
    assert "secret" not in store.path.read_text()


def test_admin_pin_is_hashed_and_verifiable(store):
    config = store.set_admin_pin("2468")
    assert config.admin_pin_set
    assert store.verify_admin_pin("2468")
    assert not store.verify_admin_pin("0000")
    assert "2468" not in store.path.read_text()


@pytest.mark.parametrize("pin", ["123", "123456789", "12ab"])
def test_admin_pin_validation(store, pin):
    with pytest.raises(ValueError):
        store.set_admin_pin(pin)


def test_active_event_roundtrip(store):
    store.set_active_event("event-1")
    assert store.load().active_event_id == "event-1"
    store.set_active_event(None)
    assert store.load().active_event_id is None


def test_performance_settings_roundtrip(store):
    store.set_performance("pi4", "performance")
    config = store.load()
    assert config.performance_device == "pi4"
    assert config.performance_mode == "performance"


def test_ensure_rebuilds_on_corrupt_json(store):
    store.path.write_text("{ this is not valid json")
    config = store.ensure()  # must not raise; rebuilds from local defaults
    assert config.active_event_id is None
