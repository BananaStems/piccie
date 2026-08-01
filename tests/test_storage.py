import os
import sqlite3
from datetime import datetime, timedelta
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
    assert event.r2_folder == "wedding-2026-06-14"
    session = storage.create_session(event.id)
    assert session.strip_number == 1
    assert Path(session.local_path).exists()
    storage.mark_session_finalized(session.id)
    updated = storage.get_event(event.id)
    assert updated.photo_count == 1


def test_event_folder_collisions_and_deleted_strip_numbers_are_not_reused(storage):
    first_event = storage.create_event("Wedding", "2026-06-14", "classic")
    second_event = storage.create_event("Wedding", "2026-06-14", "classic")
    assert first_event.r2_folder == "wedding-2026-06-14"
    assert second_event.r2_folder == "wedding-2026-06-14-2"

    first_session = storage.create_session(first_event.id)
    assert first_session.strip_number == 1
    assert storage.delete_session(first_session.id)[0] is True
    second_session = storage.create_session(first_event.id)
    assert second_session.strip_number == 2


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
    stored = storage.get_event(event.id)
    assert stored.line1 == "Sarah & James"
    assert stored.line2 == "Forever"
    assert stored.date == "2027-01-01"
    assert stored.template_id == "love"
    assert not (storage.events_dir / event.id / "meta.json").exists()


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
    assert "r2_folder" in cols
    assert "next_strip_number" in cols


def test_migration_assigns_stable_folder_and_strip_numbers(tmp_path):
    db = tmp_path / "legacy.db"
    events_dir = tmp_path / "events"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE events (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, date TEXT NOT NULL,
                template_id TEXT NOT NULL, photo_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL, created_at TEXT NOT NULL,
                r2_strip_url TEXT, local_path TEXT NOT NULL,
                upload_status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE r2_deletions (
                basename TEXT PRIMARY KEY, created_at TEXT NOT NULL
            );
            INSERT INTO events VALUES (
                'event-1', 'Sarah & James', '2026-06-14', 'classic', 2,
                '2026-01-01T00:00:00+00:00'
            );
            INSERT INTO sessions VALUES (
                'session-1', 'event-1', '2026-01-01T01:00:00+00:00', NULL,
                '/tmp/session-1', 'complete'
            );
            INSERT INTO sessions VALUES (
                'session-2', 'event-1', '2026-01-01T02:00:00+00:00', NULL,
                '/tmp/session-2', 'complete'
            );
            """
        )

    migrated = Storage(db, events_dir)

    assert migrated.get_event("event-1").r2_folder == "sarah-james-2026-06-14"
    assert migrated.get_session("session-1").strip_number == 1
    assert migrated.get_session("session-2").strip_number == 2
    assert migrated.create_session("event-1").strip_number == 3


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
    storage.mark_session_finalized(session.id)
    ok, basenames = storage.clear_event_photos(event.id)
    assert ok is True
    assert basenames == [
        f"named-event-session:{event.id}:{session.id}:{event.r2_folder}:wedding-strip-00001",
        f"event-content:{event.id}",
        f"named-event-archive:{event.id}:{event.r2_folder}",
    ]
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
    named_archive = f"named-event-archive:{event.id}:{event.r2_folder}"
    assert basenames == [target, f"event-content:{event.id}", named_archive]
    assert storage.pending_r2_deletions() == [
        target,
        f"event-content:{event.id}",
        named_archive,
    ]
    storage.complete_r2_deletion(target)
    storage.complete_r2_deletion(f"event-content:{event.id}")
    storage.complete_r2_deletion(named_archive)
    assert storage.pending_r2_deletions() == []


def test_clear_event_photos_invalidates_existing_event_share(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    token = f"{event.id}.secret"
    storage.set_event_share(event.id, "https://gallery.example/shared", token)
    archive = storage.events_dir / event.id / "download-all.zip"
    archive.write_bytes(b"old archive")

    ok, targets = storage.clear_event_photos(event.id)

    assert ok is True
    assert f"event-share:{event.id}:{token}" in targets
    refreshed = storage.get_event(event.id)
    assert refreshed.share_url is None
    assert refreshed.share_token is None
    assert not archive.exists()


def test_delete_session_removes_only_one_strip_and_invalidates_shared_gallery(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    first = storage.create_session(event.id)
    second = storage.create_session(event.id)
    for session in (first, second):
        (Path(session.local_path) / "strip.jpg").write_bytes(b"fake")
        storage.mark_session_finalized(session.id)
    token = f"{event.id}.secret"
    storage.set_event_share(event.id, "https://gallery.example/shared", token)

    ok, targets = storage.delete_session(first.id)

    assert ok is True
    assert targets == [
        f"named-event-session:{event.id}:{first.id}:{event.r2_folder}:wedding-strip-00001",
        f"event-archive:{event.id}",
        f"named-event-archive:{event.id}:{event.r2_folder}",
        f"event-share:{event.id}:{token}",
    ]
    assert storage.get_session(first.id) is None
    assert not Path(first.local_path).exists()
    assert storage.get_session(second.id) is not None
    assert Path(second.local_path).exists()
    refreshed = storage.get_event(event.id)
    assert refreshed.photo_count == 1
    assert refreshed.share_url is None
    assert refreshed.share_token is None
    assert set(storage.pending_r2_deletions()) == set(targets)
    assert storage.delete_session(first.id) == (False, [])


def test_delete_event_removes_db_and_files(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    event_dir = Path(storage.events_dir) / event.id
    assert event_dir.exists()
    ok, basenames = storage.delete_event(event.id)
    assert ok is True
    assert basenames == [
        f"named-event-session:{event.id}:{session.id}:{event.r2_folder}:wedding-strip-00001",
        f"event:{event.id}",
        f"named-event:{event.id}:{event.r2_folder}",
    ]
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
    disabled = storage.set_event_share(event.id, None, None)
    assert disabled.share_url is None
    assert disabled.share_token is None


def test_corrupt_completed_session_is_terminal(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    session_dir = Path(session.local_path)
    (session_dir / "strip.jpg").write_bytes(b"\xff\xd8truncated")

    assert storage.list_sessions_needing_upload() == []
    assert storage.get_session(session.id).upload_status == "corrupt"

    with storage._connect() as conn:
        conn.execute("UPDATE sessions SET created_at = ? WHERE id = ?", ("2020-01-01T00:00:00+00:00", session.id))
    assert storage.prune_abandoned_sessions() == 1
    assert storage.get_session(session.id) is None
    assert not session_dir.exists()


def test_valid_strip_resumes_without_source_photos(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")

    assert [item.id for item in storage.list_sessions_needing_upload()] == [session.id]


def test_orphan_photo_tree_is_quarantined_not_deleted(storage):
    orphan = storage.events_dir / "missing-database-event"
    orphan.mkdir()
    photo = orphan / "strip.jpg"
    photo.write_bytes(b"guest photo")

    assert storage.sweep_orphan_dirs() == 1

    recovered = storage.events_dir.parent / "recovered-orphans" / orphan.name
    assert (recovered / "strip.jpg").read_bytes() == b"guest photo"
    assert not orphan.exists()


def test_finalized_strip_reconciliation_repairs_count_exactly_once(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")

    assert storage.reconcile_finalized_sessions() == 1
    assert storage.get_event(event.id).photo_count == 1
    assert storage.get_session(session.id).finalized_at is not None

    storage.reconcile_finalized_sessions()
    storage.mark_session_finalized(session.id)
    assert storage.get_event(event.id).photo_count == 1


def test_failed_upload_uses_persistent_exponential_backoff(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    Image.new("RGB", (2, 2)).save(Path(session.local_path) / "strip.jpg")
    storage.update_session_upload(
        session.id,
        "failed",
        error="offline",
        increment_attempt=True,
    )
    failed = storage.get_session(session.id)
    updated = datetime.fromisoformat(failed.upload_updated_at)

    assert storage.list_sessions_needing_upload(now=updated) == []
    assert [
        item.id
        for item in storage.list_sessions_needing_upload(
            now=updated + timedelta(seconds=31)
        )
    ] == [session.id]


def test_upload_summary_is_database_backed(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    storage.create_session(event.id)
    failed = storage.create_session(event.id)
    storage.update_session_upload(
        failed.id,
        "failed",
        error="venue internet unavailable",
        increment_attempt=True,
    )

    assert storage.upload_summary() == {
        "pending": 1,
        "failed": 1,
        "last_error": "venue internet unavailable",
    }
    refreshed = storage.get_session(failed.id)
    assert refreshed.upload_attempts == 1
    assert refreshed.upload_error == "venue internet unavailable"


def test_legacy_skipped_uploads_are_requeued_by_migration(storage):
    event = storage.create_event("Wedding", "2026-06-14", "classic")
    session = storage.create_session(event.id)
    with storage._connect() as conn:
        conn.execute(
            "UPDATE sessions SET upload_status = 'skipped' WHERE id = ?",
            (session.id,),
        )
        storage._migrate_sessions(conn)

    migrated = storage.get_session(session.id)
    assert migrated.upload_status == "failed"
    assert "not configured" in migrated.upload_error
