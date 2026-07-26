import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from engine import upload_queue as upload_queue_module
from engine.config import ConfigStore
from engine.storage import Storage
from engine.upload_queue import UploadJob, UploadQueue


def test_delete_requested_during_upload_wins(tmp_path, monkeypatch):
    local = tmp_path / "local.json"
    local.write_text(
        json.dumps(
            {
                "r2": {
                    "account_id": "acct",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "photos",
                    "public_base_url": "https://photos.example.com",
                }
            }
        )
    )
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", local)
    store = ConfigStore(tmp_path / "config.json")
    store.ensure()
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2026-08-01", "classic")
    session = storage.create_session(event.id)
    target = f"event-session:{event.id}:{session.id}"
    storage.write_session_meta(
        session,
        {
            "session_id": session.id,
            "event_id": event.id,
            "r2_target": target,
            "upload_status": "pending",
        },
    )
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")

    class RacingUploader:
        deleted = []
        tokens = []

        def upload_session(self, _session_dir, _event_id, _session_id, _event_name, _event_date, share_token=None):
            self.tokens.append(share_token)
            ok, targets = storage.clear_event_photos(event.id)
            assert ok and targets == [
                target,
                f"event-share:{event.id}:{share_token}",
                f"event-content:{event.id}",
            ]
            return "https://photos.example.com/s/token", share_token

        def delete_target(self, value):
            self.deleted.append(value)

    uploader = RacingUploader()
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue.config_store = store
    upload_queue._get_uploader = lambda _config: uploader

    upload_queue._process(
        UploadJob(session.id, event.id, Path(session.local_path), cloud_target=target)
    )

    assert uploader.deleted == [target]
    assert storage.pending_r2_deletions() == [
        f"event-share:{event.id}:{uploader.tokens[0]}",
        f"event-content:{event.id}",
    ]
    assert storage.get_session(session.id) is None


def test_retry_reuses_share_token_persisted_before_upload(tmp_path, monkeypatch):
    local = tmp_path / "local.json"
    local.write_text(
        json.dumps(
            {
                "r2": {
                    "account_id": "acct",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "photos",
                    "public_base_url": "https://photos.example.com",
                }
            }
        )
    )
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", local)
    store = ConfigStore(tmp_path / "config.json")
    store.ensure()
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2026-08-01", "classic")
    session = storage.create_session(event.id)
    target = f"event-session:{event.id}:{session.id}"
    storage.write_session_meta(session, {"r2_target": target})
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")

    class FlakyUploader:
        tokens = []

        def upload_session(
            self,
            _session_dir,
            _event_id,
            _session_id,
            _event_name,
            _event_date,
            share_token=None,
        ):
            self.tokens.append(share_token)
            if len(self.tokens) == 1:
                raise RuntimeError("connection dropped after share write")
            return f"https://photos.example.com/s/{share_token}", share_token

        def verify_guest_download(self, _url, expected_path):
            assert expected_path.read_bytes().endswith(b"\xff\xd9")

    uploader = FlakyUploader()
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue.config_store = store
    upload_queue._get_uploader = lambda _config: uploader
    upload_queue._cloud_lock = threading.Lock()
    upload_queue._cloud_reachable = None
    upload_queue._cloud_error = None
    job = UploadJob(session.id, event.id, Path(session.local_path), target)

    with pytest.raises(RuntimeError, match="connection dropped"):
        upload_queue._process(job)
    persisted_token = storage.get_session_meta(session)["share_token"]

    upload_queue._process(job)

    assert uploader.tokens == [persisted_token, persisted_token]
    assert storage.get_session(session.id).upload_status == "complete"


def test_retry_failures_are_persisted_with_attempt_count(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2026-08-01", "classic")
    session = storage.create_session(event.id)
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue._stop_event = threading.Event()
    upload_queue._process = lambda _job: (_ for _ in ()).throw(
        RuntimeError("venue network dropped")
    )
    monkeypatch.setattr(upload_queue_module, "MAX_RETRIES", 3)
    monkeypatch.setattr(upload_queue_module, "RETRY_BASE_SECONDS", 0)

    with pytest.raises(RuntimeError, match="venue network dropped"):
        upload_queue._process_with_retry(
            UploadJob(session.id, event.id, Path(session.local_path))
        )

    failed = storage.get_session(session.id)
    assert failed.upload_status == "failed"
    assert failed.upload_attempts == 3
    assert failed.upload_error == "venue network dropped"


def test_backlog_includes_database_pending_and_failed(tmp_path):
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2026-08-01", "classic")
    storage.create_session(event.id)
    failed = storage.create_session(event.id)
    storage.update_session_upload(failed.id, "failed", error="offline")
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage

    assert upload_queue.backlog == 2


def test_cloud_health_fails_closed_then_recovers(tmp_path, monkeypatch):
    local = tmp_path / "local.json"
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", local)
    store = ConfigStore(tmp_path / "config.json")
    store.ensure()
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.config_store = store
    upload_queue._cloud_lock = threading.Lock()
    upload_queue._probe_lock = threading.Lock()
    upload_queue._cloud_reachable = None
    upload_queue._cloud_error = None

    assert upload_queue.check_cloud_health() == (
        False,
        "Cloud photo delivery is not configured.",
    )

    local.write_text(
        json.dumps(
            {
                "r2": {
                    "account_id": "acct",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "photos",
                    "public_base_url": "https://photos.example.com",
                }
            }
        )
    )
    monkeypatch.setattr("engine.provisioning._public_r2_probe", lambda _config: None)

    assert upload_queue.check_cloud_health() == (True, None)
    assert upload_queue.cloud_health == (True, None)


def test_event_deletions_wait_for_inflight_upload():
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue._inflight_lock = threading.Lock()
    upload_queue._inflight_events = {"session-1": "event-1"}

    assert upload_queue._deletion_conflicts_with_upload(
        "event-session:event-1:session-1"
    )
    assert upload_queue._deletion_conflicts_with_upload("event-share:event-1:token")
    assert upload_queue._deletion_conflicts_with_upload("event-content:event-1")
    assert upload_queue._deletion_conflicts_with_upload("event:event-1")
    assert not upload_queue._deletion_conflicts_with_upload("event:event-2")
