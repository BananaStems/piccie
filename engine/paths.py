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


def r2_event_manifest_key(event_id: str) -> str:
    return f"{r2_event_prefix(event_id)}manifest.json"


def r2_event_archive_key(event_id: str) -> str:
    return f"{r2_event_prefix(event_id)}download-all.zip"


def r2_share_key(event_id: str, token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{r2_event_prefix(event_id)}shares/{digest}.json"


def r2_session_target(event_id: str, session_id: str) -> str:
    return f"event-session:{event_id}:{session_id}"
