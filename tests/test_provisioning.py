from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import R2Config
from engine.provisioning import _r2_probe


def test_r2_probe_uses_guest_strip_route_and_cleans_up(monkeypatch):
    class FakeUploader:
        body = b""
        event_id = ""
        verified = False
        deleted = []

        def __init__(self, _config):
            pass

        def upload_session(self, session_dir: Path, event_id, session_id):
            type(self).body = (session_dir / "strip.jpg").read_bytes()
            type(self).event_id = event_id
            return f"https://gallery.example/s/{event_id}/{session_id}"

        def delete_target(self, target):
            type(self).deleted.append(target)

        def verify_guest_download(self, url, expected_path):
            assert url.startswith(f"https://gallery.example/s/{self.event_id}/")
            assert expected_path.read_bytes() == self.body
            type(self).verified = True

    monkeypatch.setattr("engine.provisioning.R2Uploader", FakeUploader)

    _r2_probe(
        R2Config("acct", "key", "secret", "photos")
    )

    assert FakeUploader.verified is True
    assert FakeUploader.deleted == [f"event:{FakeUploader.event_id}"]


def test_r2_probe_fails_closed_on_wrong_guest_bytes_and_still_cleans(monkeypatch):
    class FakeUploader:
        deleted = []

        def __init__(self, _config):
            pass

        def upload_session(self, *_args):
            return "https://gallery.example/s/probe"

        def delete_target(self, target):
            type(self).deleted.append(target)

        def verify_guest_download(self, _url, _expected_path):
            raise RuntimeError("guest link unavailable")

    monkeypatch.setattr("engine.provisioning.R2Uploader", FakeUploader)

    with pytest.raises(RuntimeError, match="guest link unavailable"):
        _r2_probe(
            R2Config("acct", "key", "secret", "photos")
        )

    assert len(FakeUploader.deleted) == 1
