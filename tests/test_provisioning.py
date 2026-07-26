from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import R2Config
from engine.provisioning import _public_r2_probe


def test_r2_probe_uses_guest_strip_route_and_cleans_up(monkeypatch):
    class FakeUploader:
        body = b""
        uploaded_token = ""
        verified = False
        deleted = []

        def __init__(self, _config):
            pass

        @staticmethod
        def new_session_share_token(event_id, session_id):
            return f"{event_id}.{session_id}.probe"

        def upload_session(
            self,
            session_dir: Path,
            _event_id,
            _session_id,
            _event_name,
            _event_date,
            share_token=None,
        ):
            type(self).body = (session_dir / "strip.jpg").read_bytes()
            type(self).uploaded_token = share_token
            return f"https://gallery.example/s/{share_token}", share_token

        def delete_target(self, target):
            type(self).deleted.append(target)

        def verify_guest_download(self, url, expected_path):
            assert url == f"https://gallery.example/s/{self.uploaded_token}"
            assert expected_path.read_bytes() == self.body
            type(self).verified = True

    monkeypatch.setattr("engine.provisioning.R2Uploader", FakeUploader)

    _public_r2_probe(
        R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    )

    assert ".probe" in FakeUploader.uploaded_token
    assert FakeUploader.verified is True
    assert FakeUploader.deleted == [
        f"event:{FakeUploader.uploaded_token.split('.', 1)[0]}"
    ]


def test_r2_probe_fails_closed_on_wrong_guest_bytes_and_still_cleans(monkeypatch):
    class FakeUploader:
        deleted = []

        def __init__(self, _config):
            pass

        @staticmethod
        def new_session_share_token(event_id, session_id):
            return f"{event_id}.{session_id}.probe"

        def upload_session(self, *_args, share_token=None):
            return f"https://gallery.example/s/{share_token}", share_token

        def delete_target(self, target):
            type(self).deleted.append(target)

        def verify_guest_download(self, _url, _expected_path):
            raise RuntimeError("guest link unavailable")

    monkeypatch.setattr("engine.provisioning.R2Uploader", FakeUploader)

    with pytest.raises(RuntimeError, match="guest link unavailable"):
        _public_r2_probe(
            R2Config("acct", "key", "secret", "photos", "https://gallery.example")
        )

    assert len(FakeUploader.deleted) == 1
