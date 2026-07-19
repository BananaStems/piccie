from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.atomicio import jpeg_is_intact, write_json_atomic
from engine.config import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "piccie.db"
EVENTS_DIR = DATA_DIR / "events"
DISK_LOW_MB = int(os.environ.get("PICCIE_DISK_LOW_MB", "500"))
# Written by data-fallback.service to tmpfs (/run always writable) when /data
# fails its read/write test — used when /data itself is read-only and cannot
# hold its own .DEGRADED marker.
RUN_DEGRADED_MARKER = Path("/run/piccie.degraded")


def disk_free_mb() -> int:
    usage = shutil.disk_usage(DATA_DIR)
    return usage.free // (1024 * 1024)


def disk_low() -> bool:
    return disk_free_mb() < DISK_LOW_MB


def data_degraded() -> bool:
    """True if /data is missing/read-only and the appliance fell back to a
    volatile tmpfs (set by data-fallback.service). Photos won't persist."""
    if (DATA_DIR / ".DEGRADED").exists():
        return True
    # /run marker: set by data-fallback.service when /data is present but READ-
    # ONLY (errors=remount-ro fired). A ro /data cannot hold its own .DEGRADED,
    # so the fallback writes it to tmpfs instead.
    if RUN_DEGRADED_MARKER.exists():
        return True
    if str(DATA_DIR) == "/data":
        # Must be its own partition. A plain directory (no mount) means writes
        # land on the root fs — a tmpfs overlay after lockdown, wiped at power-off.
        if not os.path.ismount("/data"):
            return True
        # Mounted but not writable (remounted read-only after an ext4 error).
        if not os.access("/data", os.W_OK):
            return True
    return False


@dataclass
class Event:
    id: str
    name: str
    line1: str
    line2: str
    date: str
    ends_at: str
    template_id: str
    photo_count: int
    date_separator: str = "/"
    share_url: str | None = None
    share_token: str | None = None

    def strip_line1(self) -> str:
        return self.line1 or self.name

    def launch_until(self) -> datetime:
        return datetime.fromisoformat(self.ends_at) + timedelta(hours=24)

    def is_concluded(self, now: datetime | None = None) -> bool:
        deadline = self.launch_until()
        if deadline.tzinfo is None:
            current = (now or datetime.now().astimezone()).replace(tzinfo=None)
        else:
            current = now or datetime.now(timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            current = current.astimezone(deadline.tzinfo)
        return current >= deadline


@dataclass
class Session:
    id: str
    event_id: str
    created_at: str
    r2_strip_url: str | None
    local_path: str
    upload_status: str


class Storage:
    def __init__(self, db_path: Path = DB_PATH, events_dir: Path = EVENTS_DIR) -> None:
        self.db_path = db_path
        self.events_dir = events_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Power-loss safety on a yank-to-shutdown appliance: WAL + full fsync.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA wal_autocheckpoint=256")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    ends_at TEXT NOT NULL DEFAULT '',
                    date_separator TEXT NOT NULL DEFAULT '/',
                    template_id TEXT NOT NULL,
                    photo_count INTEGER NOT NULL DEFAULT 0,
                    share_url TEXT,
                    share_token TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    r2_strip_url TEXT,
                    local_path TEXT NOT NULL,
                    upload_status TEXT NOT NULL DEFAULT 'pending',
                    FOREIGN KEY (event_id) REFERENCES events(id)
                );
                CREATE TABLE IF NOT EXISTS r2_deletions (
                    basename TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._migrate_events(conn)

    def _migrate_events(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        if "line1" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN line1 TEXT NOT NULL DEFAULT ''")
        if "line2" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN line2 TEXT NOT NULL DEFAULT ''")
        if "date_separator" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN date_separator TEXT NOT NULL DEFAULT '/'")
        if "ends_at" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN ends_at TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE events SET ends_at = date || 'T23:59:00' WHERE ends_at = ''")
        if "share_url" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN share_url TEXT")
        if "share_token" not in cols:
            conn.execute("ALTER TABLE events ADD COLUMN share_token TEXT")
        # The abandoned scheduled-email prototype briefly stored host addresses.
        # Sharing no longer needs them, so remove any retained personal data.
        if "host_email" in cols:
            conn.execute("UPDATE events SET host_email = ''")

    def list_events(self) -> list[Event]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY date DESC, created_at DESC"
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_event(self, event_id: str) -> Event | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def create_event(
        self,
        name: str,
        date: str,
        template_id: str,
        *,
        line1: str = "",
        line2: str = "",
        ends_at: str | None = None,
        date_separator: str = "/",
    ) -> Event:
        event_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        ends_at = ends_at or f"{date}T23:59:00"
        event_dir = self.events_dir / event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": event_id,
            "name": name,
            "line1": line1,
            "line2": line2,
            "date": date,
            "ends_at": ends_at,
            "date_separator": date_separator,
            "template_id": template_id,
        }
        write_json_atomic(event_dir / "meta.json", meta)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (id, name, line1, line2, date, ends_at, date_separator, template_id, photo_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (event_id, name, line1, line2, date, ends_at, date_separator, template_id, created_at),
            )
        return Event(
            id=event_id,
            name=name,
            line1=line1,
            line2=line2,
            date=date,
            ends_at=ends_at,
            date_separator=date_separator,
            template_id=template_id,
            photo_count=0,
        )

    def create_session(self, event_id: str) -> Session:
        session_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        session_dir = self.events_dir / event_id / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, event_id, created_at, local_path, upload_status) VALUES (?, ?, ?, ?, 'pending')",
                (session_id, event_id, created_at, str(session_dir)),
            )
        return Session(
            id=session_id,
            event_id=event_id,
            created_at=created_at,
            r2_strip_url=None,
            local_path=str(session_dir),
            upload_status="pending",
        )

    def get_session(self, session_id: str) -> Session | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def list_event_sessions(self, event_id: str) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE event_id = ? ORDER BY created_at DESC, rowid DESC",
                (event_id,),
            ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def update_session_upload(self, session_id: str, status: str, r2_strip_url: str | None = None) -> None:
        with self._connect() as conn:
            if r2_strip_url:
                conn.execute(
                    "UPDATE sessions SET upload_status = ?, r2_strip_url = ? WHERE id = ?",
                    (status, r2_strip_url, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET upload_status = ? WHERE id = ?",
                    (status, session_id),
                )

    def update_event(
        self,
        event_id: str,
        name: str,
        date: str,
        *,
        line1: str = "",
        line2: str = "",
        ends_at: str | None = None,
        date_separator: str = "/",
        template_id: str | None = None,
    ) -> Event | None:
        event = self.get_event(event_id)
        if not event:
            return None
        resolved_template_id = template_id or event.template_id
        resolved_ends_at = ends_at or event.ends_at
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET name = ?, line1 = ?, line2 = ?, date = ?, ends_at = ?, date_separator = ?, template_id = ? WHERE id = ?",
                (name, line1, line2, date, resolved_ends_at, date_separator, resolved_template_id, event_id),
            )
        meta_path = self.events_dir / event_id / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["name"] = name
            meta["line1"] = line1
            meta["line2"] = line2
            meta["date"] = date
            meta["ends_at"] = resolved_ends_at
            meta["date_separator"] = date_separator
            meta["template_id"] = resolved_template_id
            write_json_atomic(meta_path, meta)
        return Event(
            id=event_id,
            name=name,
            line1=line1,
            line2=line2,
            date=date,
            ends_at=resolved_ends_at,
            date_separator=date_separator,
            template_id=resolved_template_id,
            photo_count=event.photo_count,
            share_url=event.share_url,
            share_token=event.share_token,
        )

    def set_event_share(
        self,
        event_id: str,
        share_url: str | None,
        share_token: str | None,
    ) -> Event | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET share_url = ?, share_token = ? WHERE id = ?",
                (share_url, share_token, event_id),
            )
        event = self.get_event(event_id)
        if not event:
            return None
        meta_path = self.events_dir / event_id / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                meta = {"id": event_id}
            meta["share_url"] = share_url
            write_json_atomic(meta_path, meta)
        return event

    def clear_event_photos(self, event_id: str) -> tuple[bool, list[str]]:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
            if not row:
                return False, []
            session_rows = conn.execute(
                "SELECT local_path FROM sessions WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            targets = self._collect_r2_targets(session_rows)
            targets.append(f"event-content:{event_id}")
            self._record_r2_deletions(conn, targets)
            conn.execute("DELETE FROM sessions WHERE event_id = ?", (event_id,))
            conn.execute("UPDATE events SET photo_count = 0 WHERE id = ?", (event_id,))
        for session_row in session_rows:
            session_dir = Path(session_row["local_path"])
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
        sessions_dir = self.events_dir / event_id / "sessions"
        if sessions_dir.exists():
            shutil.rmtree(sessions_dir, ignore_errors=True)
        return True, targets

    def delete_event(self, event_id: str) -> tuple[bool, list[str]]:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
            if not row:
                return False, []
            session_rows = conn.execute(
                "SELECT local_path FROM sessions WHERE event_id = ?",
                (event_id,),
            ).fetchall()
            targets = self._collect_r2_targets(session_rows)
            targets.append(f"event:{event_id}")
            self._record_r2_deletions(conn, targets)
            conn.execute("DELETE FROM sessions WHERE event_id = ?", (event_id,))
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        event_dir = self.events_dir / event_id
        if event_dir.exists():
            shutil.rmtree(event_dir)
        return True, targets

    def _collect_r2_targets(self, session_rows: list[sqlite3.Row]) -> list[str]:
        targets: list[str] = []
        for session_row in session_rows:
            meta_path = Path(session_row["local_path"]) / "meta.json"
            try:
                target = json.loads(meta_path.read_text()).get("r2_target")
            except (OSError, json.JSONDecodeError):
                target = None
            if target:
                targets.append(target)
        return list(dict.fromkeys(targets))

    @staticmethod
    def _record_r2_deletions(conn: sqlite3.Connection, targets: list[str]) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO r2_deletions (basename, created_at) VALUES (?, ?)",
            ((target, created_at) for target in targets),
        )

    def pending_r2_deletions(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT basename FROM r2_deletions ORDER BY created_at").fetchall()
        return [row["basename"] for row in rows]

    def r2_deletion_pending(self, target: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM r2_deletions WHERE basename = ?", (target,)
            ).fetchone()
        return row is not None

    def complete_r2_deletion(self, target: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM r2_deletions WHERE basename = ?", (target,))

    def increment_event_photo_count(self, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET photo_count = photo_count + 1 WHERE id = ?",
                (event_id,),
            )

    def template_event_count(self, template_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE template_id = ?", (template_id,)
            ).fetchone()
        return int(row[0])

    def session_meta_path(self, session: Session) -> Path:
        return Path(session.local_path) / "meta.json"

    def write_session_meta(self, session: Session, meta: dict) -> None:
        write_json_atomic(self.session_meta_path(session), meta)

    def get_session_meta(self, session: Session) -> dict:
        path = self.session_meta_path(session)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def list_sessions_needing_upload(self) -> list[Session]:
        sessions: list[Session] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE upload_status IN ('pending', 'failed', 'uploading')
                ORDER BY created_at ASC
                """
            ).fetchall()
        for row in rows:
            session = self._row_to_session(row)
            session_dir = Path(session.local_path)
            strip = session_dir / "strip.jpg"
            photos = [session_dir / f"photo-{i}.jpg" for i in range(1, 4)]
            # Require every file present AND a structurally-intact strip: a strip
            # truncated by a power yank must not be resumed forever (the rescan
            # would otherwise re-enqueue this 'failed' session every 30s).
            if not strip.exists():
                continue
            if not jpeg_is_intact(strip) or not all(p.exists() for p in photos):
                logger.warning("session %s output corrupt; marking terminal", session.id)
                self.update_session_upload(session.id, "corrupt")
                continue
            sessions.append(session)
        return sessions

    def get_session_target(self, session_id: str) -> str | None:
        """Return the R2 deletion target fixed when the session was finalized."""
        session = self.get_session(session_id)
        if not session:
            return None
        meta_path = self.session_meta_path(session)
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return meta.get("r2_target")

    def sweep_orphan_dirs(self) -> int:
        """Reclaim event/session directories with no matching DB row. Deletes
        commit the DB row then rmtree the dir; a power yank between the two
        leaves an orphan dir that would otherwise fill the disk forever. Run at
        boot after the DB is open."""
        if not self.events_dir.exists():
            return 0
        with self._connect() as conn:
            event_ids = {row[0] for row in conn.execute("SELECT id FROM events")}
            session_ids = {row[0] for row in conn.execute("SELECT id FROM sessions")}
        removed = 0
        for event_dir in self.events_dir.iterdir():
            if not event_dir.is_dir():
                continue
            if event_dir.name not in event_ids:
                shutil.rmtree(event_dir, ignore_errors=True)
                removed += 1
                continue
            sessions_dir = event_dir / "sessions"
            if not sessions_dir.exists():
                continue
            for session_dir in sessions_dir.iterdir():
                if session_dir.is_dir() and session_dir.name not in session_ids:
                    shutil.rmtree(session_dir, ignore_errors=True)
                    removed += 1
        if removed:
            logger.info("Swept %s orphan director(ies)", removed)
        return removed

    def prune_abandoned_sessions(self, max_age_hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed = 0
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sessions").fetchall()
        for row in rows:
            session = self._row_to_session(row)
            session_dir = Path(session.local_path)
            if (session_dir / "strip.jpg").exists() and session.upload_status != "corrupt":
                continue
            try:
                created = datetime.fromisoformat(session.created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > cutoff:
                continue
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            removed += 1
        if removed:
            logger.info("Pruned %s abandoned session(s)", removed)
        return removed

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        keys = row.keys()
        return Event(
            id=row["id"],
            name=row["name"],
            line1=row["line1"] if "line1" in keys else "",
            line2=row["line2"] if "line2" in keys else "",
            date=row["date"],
            ends_at=(row["ends_at"] if "ends_at" in keys else "") or f"{row['date']}T23:59:00",
            date_separator=row["date_separator"] if "date_separator" in keys else "/",
            template_id=row["template_id"],
            photo_count=row["photo_count"],
            share_url=row["share_url"] if "share_url" in keys else None,
            share_token=row["share_token"] if "share_token" in keys else None,
        )

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            event_id=row["event_id"],
            created_at=row["created_at"],
            r2_strip_url=row["r2_strip_url"],
            local_path=row["local_path"],
            upload_status=row["upload_status"],
        )
