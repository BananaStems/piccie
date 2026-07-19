import json

import pytest

from engine.config import ConfigStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    config_file = tmp_path / "local.json"
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", config_file)
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    return ConfigStore(path=tmp_path / "config.json"), config_file


def test_r2_from_local_file(store):
    config_store, config_file = store
    config_file.write_text(
        json.dumps(
            {
                "r2": {
                    "account_id": "acc123",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "bucket",
                    "public_base_url": "https://cdn.example.com",
                },
            }
        )
    )
    r2 = config_store.r2_from_local()
    assert r2 is not None
    assert r2.bucket == "bucket"
