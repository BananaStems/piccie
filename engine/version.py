from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _release_value(filename: str, fallback: str) -> str:
    try:
        value = (ROOT_DIR / filename).read_text(encoding="utf-8").strip()
    except OSError:
        return fallback
    return value or fallback


APP_VERSION = _release_value("VERSION", "0.0.0-dev")
BUILD_ID = _release_value("BUILD", "source")
