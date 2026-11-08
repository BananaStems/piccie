from __future__ import annotations

import hashlib
import re
import unicodedata


def slugify(text: str, max_len: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        return "item"
    return slug[:max_len].strip("-") or "item"


def r2_event_prefix(event_id: str) -> str:
    return f"events/{event_id}/"


def r2_event_strip_key(event_id: str, session_id: str) -> str:
    return f"{r2_event_prefix(event_id)}sessions/{session_id}/strip.jpg"


def r2_event_session_page_key(event_id: str, session_id: str) -> str:
    return f"{r2_event_prefix(event_id)}sessions/{session_id}/index.html"


def r2_event_archive_key(event_id: str) -> str:
    return f"{r2_event_prefix(event_id)}download-all.zip"


def r2_event_gallery_key(event_id: str, token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{r2_event_prefix(event_id)}shares/{digest}.html"


def r2_session_target(event_id: str, session_id: str) -> str:
    return f"event-session:{event_id}:{session_id}"


def r2_named_event_folder(event_name: str, event_date: str) -> str:
    """Human-readable R2 folder used for an event's guest media."""
    return f"{slugify(event_name)}-{event_date}"


def r2_named_strip_stem(event_name: str, strip_number: int) -> str:
    return f"{slugify(event_name)}-strip-{strip_number:05d}"


def r2_named_strip_key(event_folder: str, strip_stem: str) -> str:
    return f"{event_folder}/strips/{strip_stem}.jpg"


def r2_named_photo_key(event_folder: str, strip_stem: str, photo_index: int) -> str:
    return f"{event_folder}/photos/{strip_stem}-photo-{photo_index:02d}.jpg"


def r2_named_event_archive_key(event_folder: str) -> str:
    return f"{event_folder}/download-all.zip"


def r2_named_session_target(
    event_id: str,
    session_id: str,
    event_folder: str,
    strip_stem: str,
) -> str:
    return (
        f"named-event-session:{event_id}:{session_id}:{event_folder}:{strip_stem}"
    )
