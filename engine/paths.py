from __future__ import annotations

import base64
import hashlib
import re
import unicodedata


def slugify(text: str, max_len: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        return "item"
    return slug[:max_len].strip("-") or "item"


def _short_name(value: str, length: int) -> str:
    # Custom-domain links are public, so names are unguessable hashes, kept short for the QR.
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:length]


def r2_event_prefix(event_id: str) -> str:
    return f"{_short_name('event:' + event_id, 8)}/"


def r2_event_strip_key(event_id: str, session_id: str) -> str:
    return f"{r2_event_prefix(event_id)}{_short_name('strip:' + session_id, 11)}.jpg"


def _r2_share_key(event_id: str, token: str, extension: str) -> str:
    return f"{r2_event_prefix(event_id)}{_short_name(token, 16)}.{extension}"


def r2_event_archive_key(event_id: str, token: str) -> str:
    # One zip per share link, so disabling or replacing a link also revokes its zip.
    return _r2_share_key(event_id, token, "zip")


def r2_event_gallery_key(event_id: str, token: str) -> str:
    return _r2_share_key(event_id, token, "html")


# Releases up to 1.0.6 kept every object under events/<event_id>/.
def r2_legacy_event_prefix(event_id: str) -> str:
    return f"events/{event_id}/"


def r2_legacy_strip_key(event_id: str, session_id: str) -> str:
    return f"{r2_legacy_event_prefix(event_id)}sessions/{session_id}/strip.jpg"


def r2_legacy_share_keys(event_id: str, token: str) -> list[str]:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    stem = f"{r2_legacy_event_prefix(event_id)}shares/{digest}"
    return [f"{stem}.html", f"{stem}.zip"]


def r2_session_target(event_id: str, session_id: str) -> str:
    return f"event-session:{event_id}:{session_id}"
