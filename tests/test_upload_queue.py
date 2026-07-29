import json
import itertools
import queue
import threading
from pathlib import Path

from PIL import Image

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

        def upload_session(self, _session_dir, _event_id, _session_id):
            ok, targets = storage.clear_event_photos(event.id)
            assert ok and targets == [
                target,
                f"event-content:{event.id}",
            ]
            return "https://photos.example.com/strip"

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
    assert storage.pending_r2_deletions() == [f"event-content:{event.id}"]
    assert storage.get_session(session.id) is None


def test_worker_persists_one_failure_without_immediate_retry_storm(tmp_path):
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    event = storage.create_event("Wedding", "2026-08-01", "classic")
    session = storage.create_session(event.id)
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue.storage = storage
    upload_queue._queue = queue.PriorityQueue()
    upload_queue._queue.put(
        (0, 0, UploadJob(session.id, event.id, Path(session.local_path)))
    )
    upload_queue._stop_event = threading.Event()
    upload_queue._inflight_lock = threading.Lock()
    upload_queue._inflight = {session.id}
    upload_queue._inflight_events = {session.id: event.id}
    upload_queue._cloud_lock = threading.Lock()
    upload_queue._cloud_reachable = None
    upload_queue._cloud_error = None
    calls = []

    def fail_once(_job):
        calls.append(True)
        upload_queue._stop_event.set()
        raise RuntimeError("venue network dropped")

    upload_queue._process = fail_once
    upload_queue._worker()
    assert len(calls) == 1
    failed = storage.get_session(session.id)
    assert failed.upload_status == "failed"
    assert failed.upload_attempts == 1
    assert failed.upload_error == "venue network dropped"


def test_current_guest_job_precedes_historical_backlog():
    upload_queue = UploadQueue.__new__(UploadQueue)
    upload_queue._queue = queue.PriorityQueue()
    upload_queue._sequence = itertools.count()
    upload_queue._inflight = set()
    upload_queue._inflight_events = {}
    upload_queue._inflight_lock = threading.Lock()
    old = UploadJob("old", "event", Path("/old"))
    current = UploadJob("current", "event", Path("/current"))

    upload_queue.enqueue(old, block=False, historical=True)
    upload_queue.enqueue(current, block=False)

    assert upload_queue._queue.get_nowait()[2].session_id == "current"


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
    assert upload_queue._deletion_conflicts_with_upload("event-share:event-1:token")
    assert upload_queue._deletion_conflicts_with_upload("event-content:event-1")
    assert upload_queue._deletion_conflicts_with_upload("event:event-1")
    assert not upload_queue._deletion_conflicts_with_upload("event:event-2")
