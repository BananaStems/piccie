import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from engine import upload_queue as upload_queue_module
from engine.config import ConfigStore
from engine.storage import Storage
from engine.upload_queue import UploadJob, UploadQueue


def _r2_store(tmp_path, monkeypatch) -> ConfigStore:
    local = tmp_path / "local.json"
    local.write_text(
        json.dumps(
            {
                "r2": {
                    "account_id": "acct",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "photos",
                }
            }
        )
    )
    monkeypatch.setattr("engine.config.LOCAL_CONFIG_PATH", local)
    store = ConfigStore(tmp_path / "config.json")
    store.ensure()
    return store


def test_delete_requested_during_upload_wins(tmp_path, monkeypatch):
    store = _r2_store(tmp_path, monkeypatch)
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2099-08-01", "classic")
    session = storage.create_session(event.id)
    target = f"event-session:{event.id}:{session.id}"
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")

    class RacingUploader:
        deleted = []

        def upload_session(self, _session_dir, _event_id, _session_id):
            ok, targets = storage.clear_event_photos(event.id)
            assert ok and targets == [target]
            return "https://photos.example.com/s/token"

        def delete_target(self, value):
            self.deleted.append(value)

    uploader = RacingUploader()
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue.config_store = store
    upload_queue.uploader = lambda _config: uploader

    upload_queue._process(UploadJob(session.id, event.id, Path(session.local_path)))

    assert uploader.deleted == [target]
    assert storage.pending_r2_deletions() == []
    assert storage.get_session(session.id) is None


def test_clear_photos_never_deletes_strips_taken_after_it(tmp_path, monkeypatch):
    store = _r2_store(tmp_path, monkeypatch)
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2099-08-01", "classic")
    cleared = storage.create_session(event.id)
    storage.clear_event_photos(event.id)  # venue offline: the tombstone waits
    later = storage.create_session(event.id)

    class Recorder:
        deleted = []

        def delete_target(self, value):
            self.deleted.append(value)

    uploader = Recorder()
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue.config_store = store
    upload_queue.uploader = lambda _config: uploader
    upload_queue._inflight_lock = threading.Lock()
    upload_queue._inflight_events = {}

    assert upload_queue.retry_pending_deletions() == 1
    assert uploader.deleted == [f"event-session:{event.id}:{cleared.id}"]
    assert storage.get_session(later.id) is not None


def test_retry_failures_are_persisted_with_attempt_count(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2099-08-01", "classic")
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
                }
            }
        )
    )
    monkeypatch.setattr("engine.provisioning._r2_probe", lambda _config: None)

    assert upload_queue.check_cloud_health() == (True, None)
    assert upload_queue.cloud_health == (True, None)


def test_event_deletions_wait_for_inflight_upload():
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue._inflight_lock = threading.Lock()
    upload_queue._inflight_events = {"session-1": "event-1"}

    assert upload_queue._deletion_conflicts_with_upload(
        "event-session:event-1:session-1"
    )
    assert not upload_queue._deletion_conflicts_with_upload("event-share:event-1:token")
    assert not upload_queue._deletion_conflicts_with_upload("event-content:event-1")
    assert upload_queue._deletion_conflicts_with_upload("event:event-1")
    assert not upload_queue._deletion_conflicts_with_upload("event:event-2")
