from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

"""Crash-safe writes for a power-yanked appliance.

Every persistent write goes temp-file -> fsync -> os.replace so a power loss
mid-write leaves either the old file intact or the new file complete, never a
truncated one. os.replace is atomic within a filesystem; the fsync guarantees
the bytes hit the disk before the rename is durable-ordered on ext4 (which is
mounted data=ordered here).
"""


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, obj: Any, *, indent: int = 2) -> None:
    write_text_atomic(path, json.dumps(obj, indent=indent))


def _fsync_dir(directory: Path) -> None:
    # Fsync the directory so the rename itself is durable (the file's new name
    # survives a power loss, not just its contents).
    try:
        dir_fd = os.open(str(directory), os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def jpeg_is_intact(path: Path) -> bool:
    """Cheap structural check: a complete JPEG starts with SOI (FF D8) and ends
    with EOI (FF D9). A file truncated by a power yank mid-write fails the EOI
    check, so we never upload a half-written strip to R2 as a broken image."""
    try:
        size = path.stat().st_size
        if size < 4:
            return False
        with path.open("rb") as fh:
            if fh.read(2) != b"\xff\xd8":
                return False
            fh.seek(-2, os.SEEK_END)
            return fh.read(2) == b"\xff\xd9"
    except OSError:
        return False
