import os
import threading
import zipfile
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["PICCIE_CAMERA"] = "mock"

from engine.api.routes import router
from engine.camera import CameraService
from engine.config import ConfigStore
from engine.storage import Storage
from engine.templates import TemplateRegistry


class FakeUploadQueue:
    backlog = 0

    def enqueue_best_effort(self, _job):
        return True

    def retry_pending_deletions_async(self):
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PICCIE_ONBOARDING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", tmp_path / "local.json")
    monkeypatch.setattr("engine.storage.DATA_DIR", tmp_path)
    monkeypatch.setattr("engine.storage.RUN_DEGRADED_MARKER", tmp_path / ".run-degraded")

    app = FastAPI()
    app.include_router(router)
    app.state.config_store = ConfigStore(tmp_path / "config.json")
    app.state.storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    app.state.templates = TemplateRegistry(custom_templates_dir=tmp_path / "templates")
    app.state.camera = CameraService()
    app.state.upload_queue = FakeUploadQueue()
    app.state.finalize_lock = threading.Lock()
    app.state.admin_tokens = set()
    app.state.kiosk_watchdog = None
    try:
        with TestClient(app) as test_client:
            yield test_client, app
    finally:
        app.state.camera.close()


def test_operator_auth_event_and_capture_flow(client):
    test_client, app = client
    status = test_client.get("/api/status").json()
    assert status["version"] == "1.0.0"
    assert status["build"]
    app.state.config_store.set_admin_pin("2468")
    event_body = {
        "name": "Launch test",
        "line1": "SAM & ALEX",
        "line2": "WEDDING",
        "date": "2026-08-01",
        "ends_at": "2026-08-01T23:00:00",
        "date_separator": "/",
        "template_id": "classic",
    }

    assert test_client.post("/api/events", json=event_body).status_code == 401
    assert test_client.post("/api/admin/unlock", json={"pin": "0000"}).status_code == 401
    token = test_client.post("/api/admin/unlock", json={"pin": "2468"}).json()["token"]
    headers = {"X-Admin-Token": token}

    created = test_client.post("/api/events", json=event_body, headers=headers)
    assert created.status_code == 200
    event = created.json()
    assert event["date_separator"] == "/"
    assert event["ends_at"] == "2026-08-01T23:00:00"
    assert event["concluded"] is False

    active = test_client.put(
        "/api/admin/active-event",
        json={"event_id": event["id"]},
        headers=headers,
    )
    assert active.status_code == 200
    assert test_client.get("/api/status").json()["active_event_id"] == event["id"]

    started = test_client.post(f"/api/events/{event['id']}/sessions")
    assert started.status_code == 200
    session_id = started.json()["id"]
    for index in (1, 2, 3):
        capture = test_client.post(f"/api/sessions/{session_id}/capture/{index}")
        assert capture.status_code == 200
        assert capture.json()["local_url"].endswith(f"/photos/{index}")

    finalized = test_client.post(f"/api/sessions/{session_id}/finalize")
    assert finalized.status_code == 200
    assert finalized.json()["strip_local_url"].endswith("/strip")
    assert test_client.get(finalized.json()["strip_local_url"]).status_code == 200

    cleared = test_client.put(
        "/api/admin/active-event", json={"event_id": None}, headers=headers
    )
    assert cleared.status_code == 200


def test_concluded_event_cannot_launch_or_start_session(client):
    test_client, app = client
    event = app.state.storage.create_event(
        "Old event", "2020-01-01", "classic", ends_at="2020-01-01T20:00:00"
    )
    response = test_client.put("/api/admin/active-event", json={"event_id": event.id})
    assert response.status_code == 409
    assert "concluded" in response.json()["detail"]
    assert test_client.post(f"/api/events/{event.id}/sessions").status_code == 409


def test_performance_mode_requires_matching_device_and_warning(client, monkeypatch):
    test_client, app = client
    applied = []
    monkeypatch.setattr("engine.api.routes.detect_device", lambda: "pi4")
    monkeypatch.setattr("engine.api.routes.detected_memory_gb", lambda: 4)
    monkeypatch.setattr(
        "engine.api.routes.apply_performance_profile",
        lambda device, mode: applied.append((device, mode)),
    )

    settings = test_client.get("/api/settings/performance").json()
    assert settings["detected_device"] == "pi4"
    assert settings["detected_memory_gb"] == 4
    assert settings["mode"] == "standard"

    assert test_client.put(
        "/api/settings/performance",
        json={"device": "pi4", "mode": "performance"},
    ).status_code == 422
    assert test_client.put(
        "/api/settings/performance",
        json={"device": "pi5", "mode": "standard"},
    ).status_code == 409

    changed = test_client.put(
        "/api/settings/performance",
        json={
            "device": "pi4",
            "mode": "performance",
            "warning_acknowledged": True,
        },
    )
    assert changed.json() == {"ok": True, "restarting": True}
    assert applied == [("pi4", "performance")]
    assert app.state.config_store.ensure().performance_mode == "performance"


def test_phone_studio_pairs_installs_and_archives_template(client, monkeypatch):
    test_client, app = client
    monkeypatch.setattr("engine.api.routes._lan_ip", lambda: "192.168.1.40")
    pairing = test_client.post("/api/templates/pair")
    assert pairing.status_code == 200
    assert pairing.json()["url"].startswith("http://192.168.1.40:8080/studio.html#token=")
    token = pairing.json()["url"].split("#token=", 1)[1]
    headers = {"X-Studio-Token": token}
    bootstrap = test_client.get("/api/studio/bootstrap", headers=headers)
    assert bootstrap.status_code == 200
    assert any(font["id"] == "playfair-display" for font in bootstrap.json()["fonts"])
    assert any(font["id"] == "dancing-script" for font in bootstrap.json()["fonts"])
    assert len(bootstrap.json()["fonts"]) >= 20

    installed = test_client.post(
        "/api/studio/templates",
        headers=headers,
        json={
            "name": "Phone template",
            "background": "#ffffff",
            "assets": [],
            "layers": [{
                "id": "heading",
                "type": "text",
                "source": "line1",
                "x": 50,
                "y": 1380,
                "w": 500,
                "h": 90,
                "font": "sans",
                "font_size": 60,
                "fill": "#29231e",
                "align": "center",
            }],
        },
    )
    assert installed.status_code == 200
    template_id = installed.json()["id"]
    event = app.state.storage.create_event("Uses custom", "2026-08-01", template_id)
    archived = test_client.post(f"/api/templates/{template_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert archived.json()["event_count"] == 1
    assert app.state.templates.load(event.template_id).archived is True
    assert test_client.delete(f"/api/templates/{template_id}").status_code == 409

    restored = test_client.post(f"/api/templates/{template_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived"] is False
    assert app.state.templates.load(template_id).archived is False

    assert test_client.post(f"/api/templates/{template_id}/archive").status_code == 200
    assert test_client.delete(f"/api/events/{event.id}").status_code == 200
    assert test_client.delete(f"/api/templates/{template_id}").status_code == 204
    with pytest.raises(FileNotFoundError):
        app.state.templates.load(template_id)

    replacement = test_client.post("/api/templates/pair")
    replacement_token = replacement.json()["url"].split("#token=", 1)[1]
    assert replacement_token != token
    assert test_client.get("/api/studio/bootstrap", headers=headers).status_code == 401
    assert test_client.get(
        "/api/studio/bootstrap",
        headers={"X-Studio-Token": replacement_token},
    ).status_code == 200


def test_kiosk_onboarding_connects_wifi_then_saves_r2(client, monkeypatch, tmp_path):
    test_client, app = client
    monkeypatch.setattr("engine.provisioning._public_r2_probe", lambda _config: None)
    connection = {"ssid": None}
    monkeypatch.setattr("engine.api.routes.current_ssid", lambda: connection["ssid"])

    blocked = test_client.post(
        "/api/onboarding/complete",
        json={
            "admin_pin": "2468",
            "r2": {
                "account_id": "account",
                "access_key": "access",
                "secret_key": "secret",
                "bucket": "photo-strips",
                "public_base_url": "https://photos.example.com",
                "jurisdiction": "default",
            },
        },
    )
    assert blocked.status_code == 400
    assert "Wi-Fi first" in blocked.json()["detail"]

    assert test_client.post(
        "/api/wifi/connect",
        json={"ssid": "Venue", "password": "venue-password", "hidden": False},
    ).status_code == 200
    connection["ssid"] = "Venue"
    completed = test_client.post(
        "/api/onboarding/complete",
        json={
            "admin_pin": "2468",
            "ssh_authorized_key": "ssh-ed25519 AAAATEST operator",
            "r2": {
                "account_id": "account",
                "access_key": "access",
                "secret_key": "secret",
                "bucket": "photo-strips",
                "public_base_url": "https://photos.example.com",
                "jurisdiction": "default",
            },
        },
    )
    assert completed.status_code == 200
    assert (tmp_path / ".provisioned").exists()
    assert (tmp_path / "ssh" / "authorized_keys").read_text() == "ssh-ed25519 AAAATEST operator\n"
    assert app.state.config_store.ensure().r2.bucket == "photo-strips"
    assert test_client.post("/api/admin/unlock", json={"pin": "2468"}).status_code == 200


def test_event_share_builds_archive_and_can_be_disabled(client, monkeypatch):
    test_client, app = client
    from engine import config as config_module

    config_module.LOCAL_CONFIG_PATH.write_text(json.dumps({
        "r2": {
            "account_id": "acct",
            "access_key": "key",
            "secret_key": "secret",
            "bucket": "photos",
            "public_base_url": "https://gallery.example",
        }
    }))
    event = app.state.storage.create_event("Wedding", "2026-08-01", "classic")
    session = app.state.storage.create_session(event.id)
    from PIL import Image
    Image.new("RGB", (2, 6)).save(Path(session.local_path) / "strip.jpg")

    class FakeUploader:
        previous = []
        disabled = []

        def __init__(self, _config):
            pass

        def publish_event(self, event_id, _name, _date, archive, previous_token=None):
            with zipfile.ZipFile(archive) as bundle:
                assert bundle.namelist() == ["wedding-strip-001.jpg"]
            self.previous.append(previous_token)
            token = f"{event_id}.new-token"
            return f"https://gallery.example/g/{token}", token

        def disable_share(self, event_id, token):
            self.disabled.append((event_id, token))

    monkeypatch.setattr("engine.api.routes.R2Uploader", FakeUploader)
    created = test_client.post(f"/api/events/{event.id}/share")
    assert created.status_code == 200
    assert created.json()["enabled"] is True
    assert app.state.storage.get_event(event.id).share_token.endswith(".new-token")

    regenerated = test_client.post(f"/api/events/{event.id}/share/regenerate")
    assert regenerated.status_code == 200
    assert FakeUploader.previous[-1].endswith(".new-token")

    disabled = test_client.delete(f"/api/events/{event.id}/share")
    assert disabled.json() == {"enabled": False, "url": None}
    assert app.state.storage.get_event(event.id).share_url is None
