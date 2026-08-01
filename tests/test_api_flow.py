import json
import os
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["PICCIE_CAMERA"] = "mock"

TEST_SSH_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7xmMhz1/FKQxq0ML54lMRKG/th7+UEMiaq7HLEJHNC test-deploy"

from engine.api.routes import router
from engine.camera import CameraService
from engine.capture_delivery import CaptureDelivery
from engine.config import ConfigStore
from engine.storage import Storage
from engine.templates import TemplateRegistry


class FakeUploadQueue:
    backlog = 0
    cloud_health = (True, None)

    def enqueue_best_effort(self, _job):
        return True

    def retry_pending_deletions_async(self):
        return None

    def check_cloud_health(self):
        return self.cloud_health


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PICCIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PICCIE_ONBOARDING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", tmp_path / "local.json")
    monkeypatch.setattr(
        "engine.ssh_access.AUTHORIZED_KEYS_PATH",
        tmp_path / "ssh" / "authorized_keys",
    )
    monkeypatch.setattr("engine.storage.DATA_DIR", tmp_path)
    monkeypatch.setattr("engine.storage.RUN_DEGRADED_MARKER", tmp_path / ".run-degraded")

    app = FastAPI()
    app.include_router(router)
    app.state.config_store = ConfigStore(tmp_path / "config.json")
    app.state.storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    app.state.templates = TemplateRegistry(custom_templates_dir=tmp_path / "templates")
    app.state.camera = CameraService()
    app.state.upload_queue = FakeUploadQueue()
    app.state.capture_delivery = CaptureDelivery(
        app.state.storage,
        app.state.camera,
        app.state.templates,
        app.state.upload_queue,
    )
    app.state.admin_tokens = set()
    app.state.onboarding_lock = threading.Lock()
    app.state.kiosk_watchdog = None
    try:
        with TestClient(app) as test_client:
            yield test_client, app
    finally:
        app.state.camera.close()


def test_operator_auth_event_and_capture_flow(client):
    test_client, app = client
    status = test_client.get("/api/status").json()
    assert status["version"] == "1.0.10"
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
    assert test_client.post("/api/admin/unlock", json={"pin": "123"}).status_code == 422
    assert test_client.post("/api/admin/unlock", json={"pin": "12345"}).status_code == 422
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
    assert app.state.storage.get_event(event["id"]).photo_count == 1

    # Simulate power loss after strip.jpg was atomically written but before the
    # final DB/meta transaction completed. Retrying must repair, not double count.
    with app.state.storage._connect() as conn:
        conn.execute(
            "UPDATE sessions SET finalized_at = NULL WHERE id = ?", (session_id,)
        )
        conn.execute(
            "UPDATE events SET photo_count = 0 WHERE id = ?", (event["id"],)
        )
    app.state.storage.session_meta_path(
        app.state.storage.get_session(session_id)
    ).unlink(missing_ok=True)
    repaired = test_client.post(f"/api/sessions/{session_id}/finalize")
    assert repaired.status_code == 200
    assert app.state.storage.get_event(event["id"]).photo_count == 1
    assert app.state.storage.get_session_meta(
        app.state.storage.get_session(session_id)
    )["r2_target"].endswith(":launch-test-strip-00001")

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


def test_operator_can_delete_one_gallery_strip_without_removing_others(client):
    test_client, app = client
    from PIL import Image

    app.state.config_store.set_admin_pin("2468")
    token = test_client.post("/api/admin/unlock", json={"pin": "2468"}).json()["token"]
    headers = {"X-Admin-Token": token}
    event = app.state.storage.create_event("Wedding", "2026-08-01", "classic")
    first = app.state.storage.create_session(event.id)
    second = app.state.storage.create_session(event.id)
    for session in (first, second):
        Image.new("RGB", (2, 6)).save(Path(session.local_path) / "strip.jpg")
        Image.new("RGB", (2, 2)).save(Path(session.local_path) / "photo-1.jpg")
        app.state.storage.mark_session_finalized(session.id)

    assert test_client.delete(f"/api/sessions/{first.id}").status_code == 401
    deleted = test_client.delete(f"/api/sessions/{first.id}", headers=headers)

    assert deleted.json() == {"ok": True, "share_disabled": False}
    assert test_client.get(f"/api/sessions/{first.id}").status_code == 404
    remaining = test_client.get(f"/api/events/{event.id}/sessions").json()
    assert [session["id"] for session in remaining] == [second.id]
    assert app.state.storage.get_event(event.id).photo_count == 1
    assert app.state.storage.pending_r2_deletions() == [
        f"named-event-session:{event.id}:{first.id}:{event.r2_folder}:wedding-strip-00001"
    ]
    assert test_client.delete(f"/api/sessions/{first.id}", headers=headers).status_code == 404


def test_guest_qr_uses_short_lan_redirect(client, monkeypatch):
    test_client, app = client
    monkeypatch.setattr("engine.api.routes._lan_ip", lambda: "192.168.1.40")
    event = app.state.storage.create_event("Wedding", "2026-08-01", "classic")
    session = app.state.storage.create_session(event.id)
    signed_url = "https://signed.example/events/event/session/index.html?signature=long"
    app.state.storage.update_session_upload(
        session.id,
        "complete",
        signed_url,
    )

    response = test_client.get(f"/api/sessions/{session.id}")
    qr_url = response.json()["guest_qr_url"]

    assert qr_url == f"http://192.168.1.40:8080/api/d/{session.id}"
    assert len(qr_url) < len(signed_url)
    redirect = test_client.get(f"/api/d/{session.id}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == signed_url
    assert redirect.headers["cache-control"] == "no-store"


def test_qr_endpoint_renders_short_link_locally(client):
    test_client, _app = client

    response = test_client.get(
        "/api/qr",
        params={"data": "http://192.168.1.40:8080/api/d/session-id"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_degraded_storage_blocks_capture_session(client, monkeypatch):
    test_client, app = client
    event = app.state.storage.create_event("Wedding", "2026-08-01", "classic")
    monkeypatch.setattr("engine.capture_delivery.data_degraded", lambda: True)

    response = test_client.post(f"/api/events/{event.id}/sessions")

    assert response.status_code == 503
    assert "degraded" in response.json()["detail"]


def test_preflight_checks_capture_and_guest_delivery(client, monkeypatch):
    test_client, app = client
    monkeypatch.setattr("engine.api.routes.current_ssid", lambda: "Venue")

    ready = test_client.post("/api/admin/preflight").json()
    assert ready["ready"] is True
    assert ready["capture_ready"] is True
    assert ready["r2_reachable"] is True

    app.state.upload_queue.cloud_health = (False, "R2 unavailable")
    not_ready = test_client.post("/api/admin/preflight").json()
    assert not_ready["ready"] is False
    assert not_ready["capture_ready"] is True
    assert "R2 unavailable" in not_ready["warnings"][0]

    monkeypatch.setattr(
        app.state.camera,
        "capture_to_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sensor stalled")),
    )
    camera_failed = test_client.post("/api/admin/preflight").json()
    assert camera_failed["capture_ready"] is False
    assert camera_failed["camera_available"] is False
    assert "sensor stalled" in camera_failed["errors"][0]


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


def test_operator_can_update_pin_and_ssh_access_from_settings(client):
    test_client, app = client
    app.state.config_store.set_admin_pin("2468")
    old_token = test_client.post("/api/admin/unlock", json={"pin": "2468"}).json()["token"]
    old_headers = {"X-Admin-Token": old_token}

    assert test_client.get("/api/settings/access").status_code == 401
    access = test_client.get("/api/settings/access", headers=old_headers)
    assert access.status_code == 200
    assert access.json()["ssh_key_configured"] is False

    invalid_pin = test_client.put(
        "/api/settings/access/pin",
        json={"pin": "12345"},
        headers=old_headers,
    )
    assert invalid_pin.status_code == 422

    invalid = test_client.put(
        "/api/settings/access/ssh",
        json={"ssh_authorized_key": "not-a-key"},
        headers=old_headers,
    )
    assert invalid.status_code == 422
    added = test_client.put(
        "/api/settings/access/ssh",
        json={"ssh_authorized_key": TEST_SSH_KEY},
        headers=old_headers,
    )
    assert added.json() == {"ok": True, "ssh_key_configured": True}
    assert (app.state.storage.db_path.parent / "ssh" / "authorized_keys").read_text() == TEST_SSH_KEY + "\n"

    changed = test_client.put(
        "/api/settings/access/pin",
        json={"pin": "8642"},
        headers=old_headers,
    )
    assert changed.status_code == 200
    new_headers = {"X-Admin-Token": changed.json()["token"]}
    assert test_client.get("/api/settings/access", headers=old_headers).status_code == 401
    assert test_client.get("/api/settings/access", headers=new_headers).status_code == 200

    removed = test_client.put(
        "/api/settings/access/ssh",
        json={"ssh_authorized_key": ""},
        headers=new_headers,
    )
    assert removed.json() == {"ok": True, "ssh_key_configured": False}
    assert not (app.state.storage.db_path.parent / "ssh" / "authorized_keys").exists()
    assert test_client.post("/api/admin/unlock", json={"pin": "2468"}).status_code == 401
    assert test_client.post("/api/admin/unlock", json={"pin": "8642"}).status_code == 200


def test_safe_shutdown_requires_operator_and_schedules_poweroff(client, monkeypatch):
    test_client, app = client
    scheduled = []
    app.state.config_store.set_admin_pin("2468")
    monkeypatch.setattr(
        "engine.api.routes.schedule_poweroff", lambda: scheduled.append(True)
    )

    assert test_client.post("/api/system/shutdown").status_code == 401
    token = test_client.post("/api/admin/unlock", json={"pin": "2468"}).json()["token"]
    response = test_client.post(
        "/api/system/shutdown", headers={"X-Admin-Token": token}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "shutting_down": True}
    assert scheduled == [True]


def test_safe_shutdown_reports_helper_failure(client, monkeypatch):
    test_client, _app = client

    def fail():
        raise RuntimeError("systemd refused shutdown")

    monkeypatch.setattr("engine.api.routes.schedule_poweroff", fail)
    response = test_client.post("/api/system/shutdown")

    assert response.status_code == 500
    assert response.json()["detail"] == "systemd refused shutdown"


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


def test_kiosk_onboarding_requires_imported_r2_then_finishes(client, monkeypatch, tmp_path):
    test_client, app = client
    monkeypatch.setattr("engine.provisioning._r2_probe", lambda _config: None)
    connection = {"ssid": None}
    monkeypatch.setattr("engine.api.routes.current_ssid", lambda: connection["ssid"])

    invalid_pin = test_client.post(
        "/api/onboarding/complete",
        json={"admin_pin": "12345"},
    )
    assert invalid_pin.status_code == 422

    blocked = test_client.post(
        "/api/onboarding/complete",
        json={"admin_pin": "2468"},
    )
    assert blocked.status_code == 400
    assert "Wi-Fi first" in blocked.json()["detail"]

    assert test_client.post(
        "/api/wifi/connect",
        json={"ssid": "Venue", "password": "venue-password", "hidden": False},
    ).status_code == 200
    connection["ssid"] = "Venue"
    missing_r2 = test_client.post(
        "/api/onboarding/complete",
        json={"admin_pin": "2468"},
    )
    assert missing_r2.status_code == 400
    assert "piccie-r2.txt" in missing_r2.json()["detail"]

    (tmp_path / "local.json").write_text(json.dumps({
        "r2": {
            "account_id": "account",
            "access_key": "access",
            "secret_key": "secret",
            "bucket": "photo-strips",
            "jurisdiction": "default",
        }
    }))
    assert test_client.get("/api/status").json()["r2_configured"] is True
    completed = test_client.post(
        "/api/onboarding/complete",
        json={
            "admin_pin": "2468",
            "ssh_authorized_key": TEST_SSH_KEY,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["restarting"] is False
    assert (tmp_path / ".provisioned").exists()
    assert not (tmp_path / ".lockdown-requested").exists()
    assert (tmp_path / "ssh" / "authorized_keys").read_text() == TEST_SSH_KEY + "\n"
    assert app.state.config_store.ensure().r2.bucket == "photo-strips"
    assert test_client.post("/api/admin/unlock", json={"pin": "2468"}).status_code == 200


def test_removed_phone_setup_endpoints_are_not_exposed(client):
    test_client, _app = client
    assert test_client.post("/api/onboarding/pair").status_code == 404
    assert test_client.get("/api/setup/status").status_code == 404
    assert test_client.post("/api/setup/complete", json={}).status_code == 404


def test_event_share_builds_archive_and_can_be_disabled(client, monkeypatch):
    test_client, app = client
    from engine import config as config_module

    config_module.LOCAL_CONFIG_PATH.write_text(json.dumps({
        "r2": {
            "account_id": "acct",
            "access_key": "key",
            "secret_key": "secret",
            "bucket": "photos",
        }
    }))
    event = app.state.storage.create_event("Wedding", "2026-08-01", "classic")
    session = app.state.storage.create_session(event.id)
    from PIL import Image
    Image.new("RGB", (2, 6)).save(Path(session.local_path) / "strip.jpg")
    for photo_index in range(1, 4):
        Image.new("RGB", (2, 2)).save(
            Path(session.local_path) / f"photo-{photo_index}.jpg"
        )

    class FakeUploader:
        previous = []
        disabled = []

        def __init__(self, _config):
            pass

        def publish_event(
            self,
            event_id,
            _name,
            _date,
            archive,
            previous_token=None,
            event_folder=None,
        ):
            with zipfile.ZipFile(archive) as bundle:
                assert bundle.namelist() == [
                    "strips/wedding-strip-00001.jpg",
                    "photos/wedding-strip-00001-photo-01.jpg",
                    "photos/wedding-strip-00001-photo-02.jpg",
                    "photos/wedding-strip-00001-photo-03.jpg",
                ]
            assert event_folder == "wedding-2026-08-01"
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
