import json
import os
from pathlib import Path

import pytest
from PIL import Image

os.environ["PICCIE_CAMERA"] = "mock"

from engine.storage import Storage


@pytest.fixture
def storage(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    events = tmp_path / "events"
    monkeypatch.setattr("engine.storage.DB_PATH", db)
    monkeypatch.setattr("engine.storage.EVENTS_DIR", events)
    monkeypatch.setattr("engine.storage.DATA_DIR", tmp_path)
    return Storage(db_path=db, events_dir=events)


def test_create_event_and_session(storage):
    event = storage.create_event(
        "Wedding",
        "2026-06-14",
        "classic",
        line1="Sarah & James",
        line2="Forever",
        ends_at="2026-06-14T22:30:00",
        date_separator="/",
    )
    assert event.name == "Wedding"
    assert event.line1 == "Sarah & James"
    assert event.line2 == "Forever"
    assert event.date_separator == "/"
    assert event.ends_at == "2026-06-14T22:30:00"
    assert event.photo_count == 0
    session = storage.create_session(event.id)
    assert Path(session.local_path).exists()
    storage.increment_event_photo_count(event.id)
    updated = storage.get_event(event.id)
    assert updated.photo_count == 1


def test_list_event_sessions(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    first = storage.create_session(event.id)
    second = storage.create_session(event.id)
    assert {session.id for session in storage.list_event_sessions(event.id)} == {first.id, second.id}


def test_update_event(storage):
    event = storage.create_event(
        "Wedding",
        "2026-06-14",
        "classic",
        line1="Sarah & James",
        line2="Forever",
    )
    updated = storage.update_event(
        event.id,
        "Anniversary",
        "2027-01-01",
        line1="Sarah & James",
        line2="Forever",
    )
    assert updated is not None
    assert updated.name == "Anniversary"
    assert updated.line1 == "Sarah & James"
    assert updated.line2 == "Forever"
    assert updated.date == "2027-01-01"
    switched = storage.update_event(
        event.id,
        "Anniversary",
        "2027-01-01",
        line1="Sarah & James",
        line2="Forever",
        template_id="love",
    )
    assert switched.template_id == "love"
    meta = (storage.events_dir / event.id / "meta.json").read_text()
    assert "Sarah & James" in meta
    assert "Forever" in meta
    assert "2027-01-01" in meta
    assert '"template_id": "love"' in meta


def test_event_strip_line1_falls_back_to_name(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    assert event.strip_line1() == "Wedding"
    assert event.line2 == ""


def test_db_migration_adds_line_columns(storage):
    with storage._connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    assert "line1" in cols
    assert "line2" in cols
    assert "date_separator" in cols
    assert "share_url" in cols
    assert "share_token" in cols
    assert "ends_at" in cols


def test_event_concludes_24_hours_after_end(storage):
    event = storage.create_event(
        "Wedding", "2026-06-14", "classic", ends_at="2026-06-14T22:00:00"
    )
    from datetime import datetime

    assert event.is_concluded(datetime.fromisoformat("2026-06-15T21:59:00")) is False
    assert event.is_concluded(datetime.fromisoformat("2026-06-15T22:00:00")) is True


def test_migration_removes_abandoned_host_email_data(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    with storage._connect() as conn:
        conn.execute("ALTER TABLE events ADD COLUMN host_email TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE events SET host_email = 'host@example.com' WHERE id = ?", (event.id,))
        storage._migrate_events(conn)
        value = conn.execute("SELECT host_email FROM events WHERE id = ?", (event.id,)).fetchone()[0]
    assert value == ""


def test_clear_event_photos(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    session_dir = Path(session.local_path)
    (session_dir / "strip.jpg").write_bytes(b"fake")
    storage.increment_event_photo_count(event.id)
    ok, basenames = storage.clear_event_photos(event.id)
    assert ok is True
    assert basenames == [f"event-content:{event.id}"]
    assert storage.get_session(session.id) is None
    assert not session_dir.exists()
    refreshed = storage.get_event(event.id)
    assert refreshed.photo_count == 0


def test_clear_event_photos_collects_r2_targets(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    target = f"event-session:{event.id}:{session.id}"
    storage.write_session_meta(
        session,
        {
            "session_id": session.id,
            "event_id": event.id,
            "r2_target": target,
            "upload_status": "complete",
        },
    )
    ok, basenames = storage.clear_event_photos(event.id)
    assert ok is True
    assert basenames == [target, f"event-content:{event.id}"]
    assert storage.pending_r2_deletions() == [target, f"event-content:{event.id}"]
    storage.complete_r2_deletion(target)
    storage.complete_r2_deletion(f"event-content:{event.id}")
    assert storage.pending_r2_deletions() == []


def test_delete_event_removes_db_and_files(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    event_dir = Path(storage.events_dir) / event.id
    assert event_dir.exists()
    ok, basenames = storage.delete_event(event.id)
    assert ok is True
    assert basenames == [f"event:{event.id}"]
    assert storage.get_event(event.id) is None
    assert storage.get_session(session.id) is None
    assert not event_dir.exists()
    ok, basenames = storage.delete_event(event.id)
    assert ok is False
    assert basenames == []


def test_event_share_roundtrip(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    updated = storage.set_event_share(event.id, "https://gallery.example/g/token", "token")
    assert updated.share_url == "https://gallery.example/g/token"
    assert updated.share_token == "token"
    meta = json.loads((storage.events_dir / event.id / "meta.json").read_text())
    assert meta["share_url"] == "https://gallery.example/g/token"

    disabled = storage.set_event_share(event.id, None, None)
    assert disabled.share_url is None
    assert disabled.share_token is None


def test_corrupt_completed_session_is_terminal(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    session_dir = Path(session.local_path)
    Image.new("RGB", (1, 1)).save(session_dir / "strip.jpg")

    assert storage.list_sessions_needing_upload() == []
    assert storage.get_session(session.id).upload_status == "corrupt"

    with storage._connect() as conn:
        conn.execute("UPDATE sessions SET created_at = ? WHERE id = ?", ("2020-01-01T00:00:00+00:00", session.id))
    assert storage.prune_abandoned_sessions() == 1
    assert storage.get_session(session.id) is None
    assert not session_dir.exists()
