import json
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

        def upload_session(self, _session_dir, _event_id, _session_id, _event_name, _event_date, share_token=None):
            ok, targets = storage.clear_event_photos(event.id)
            assert ok and targets == [target, f"event-content:{event.id}"]
            return "https://photos.example.com/s/token", "https://photos.example.com/s/token", "token"

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
