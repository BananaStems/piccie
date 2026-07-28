import json
import urllib.parse
from unittest.mock import MagicMock

from engine.config import R2Config
from engine.paths import r2_event_archive_key, r2_event_strip_key, r2_share_key
from engine.r2 import R2Uploader


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_eu_jurisdiction_uses_eu_endpoint():
    config = R2Config(
        "acct", "key", "secret", "photos", "https://cdn.example.com", jurisdiction="eu"
    )
    uploader = R2Uploader(config)
    assert uploader.client.meta.endpoint_url == "https://acct.eu.r2.cloudflarestorage.com"


def test_upload_session_is_private_and_returns_worker_link(tmp_path):
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    uploader.client = MagicMock()
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    token = f"{event}.{session}.secret"

    url, returned_token = uploader.upload_session(
        tmp_path, event, session, "Sarah & James", "2026-06-14", share_token=token
    )

    assert url == f"https://gallery.example/s/{token}"
    assert returned_token == token
    upload = uploader.client.upload_file.call_args
    assert upload.args[2] == r2_event_strip_key(event, session)
    keys = {call.kwargs["Key"] for call in uploader.client.put_object.call_args_list}
    assert r2_share_key(event, token) in keys
    assert f"events/{event}/manifest.json" in keys


def test_publish_event_replaces_old_share_after_new_one_exists(tmp_path):
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    uploader.client = MagicMock()
    event = "11111111-1111-4111-8111-111111111111"
    archive = tmp_path / "download-all.zip"
    archive.write_bytes(b"zip")
    previous = f"{event}.old"

    url, token = uploader.publish_event(event, "Wedding", "2026-06-14", archive, previous)

    assert url == f"https://gallery.example/g/{token}"
    assert token.startswith(f"{event}.")
    upload = uploader.client.upload_file.call_args
    assert upload.args[2] == r2_event_archive_key(event)
    put_keys = [call.kwargs["Key"] for call in uploader.client.put_object.call_args_list]
    delete_key = uploader.client.delete_object.call_args.kwargs["Key"]
    assert r2_share_key(event, token) in put_keys
    assert delete_key == r2_share_key(event, previous)


def test_delete_event_target_removes_every_object_under_prefix():
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    uploader.client = MagicMock()
    event = "11111111-1111-4111-8111-111111111111"
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": f"events/{event}/manifest.json"}],
        "IsTruncated": False,
    }

    uploader.delete_target(f"event:{event}")

    uploader.client.list_objects_v2.assert_called_once_with(
        Bucket="photos", Prefix=f"events/{event}/"
    )
    deleted = uploader.client.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert deleted == [{"Key": f"events/{event}/manifest.json"}]


def test_delete_share_target_removes_exact_hashed_record():
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    uploader.client = MagicMock()
    event = "11111111-1111-4111-8111-111111111111"
    token = f"{event}.session.secret"

    uploader.delete_target(f"event-share:{event}:{token}")

    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos",
        Key=r2_share_key(event, token),
    )


def test_guest_download_must_match_uploaded_strip(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg bytes")
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda _request, timeout: Response(b"jpeg bytes"),
    )

    uploader.verify_guest_download("https://gallery.example/s/token", strip)


def test_guest_download_mismatch_fails_closed(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"expected")
    config = R2Config("acct", "key", "secret", "photos", "https://gallery.example")
    uploader = R2Uploader(config)
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda _request, timeout: Response(b"wrong"),
    )
    monkeypatch.setattr("engine.r2.time.sleep", lambda _seconds: None)

    try:
        uploader.verify_guest_download(
            "https://gallery.example/s/token",
            strip,
            attempts=2,
        )
    except RuntimeError as exc:
        assert "guest link" in str(exc)
    else:
        raise AssertionError("mismatched guest bytes should fail the upload")


def test_worker_upload_uses_bearer_credential_and_expected_keys(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg")
    config = R2Config(
        public_base_url="https://gallery.example",
        worker_token="booth-token",
    )
    uploader = R2Uploader(config)
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        return Response(b'{"ok":true}')

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", urlopen)
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    token = f"{event}.{session}.secret"
    uploader.upload_session(
        tmp_path,
        event,
        session,
        "Wedding",
        "2026-06-14",
        share_token=token,
    )

    assert uploader.client is None
    assert len(requests) == 3
    assert all(request.get_header("Authorization") == "Bearer booth-token" for request in requests)
    keys = {
        urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["key"][0]
        for request in requests
    }
    assert keys == {
        r2_event_strip_key(event, session),
        r2_share_key(event, token),
        f"events/{event}/manifest.json",
    }


def test_worker_large_upload_uses_multipart_and_completes(tmp_path, monkeypatch):
    archive = tmp_path / "download-all.zip"
    archive.write_bytes(b"abcdefghij")
    uploader = R2Uploader(
        R2Config(
            public_base_url="https://gallery.example",
            worker_token="booth-token",
        )
    )
    monkeypatch.setattr("engine.r2.MULTIPART_THRESHOLD", 4)
    monkeypatch.setattr("engine.r2.MULTIPART_PART_SIZE", 4)
    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        if path.endswith("/start"):
            return Response(b'{"upload_id":"upload-1"}')
        if path.endswith("/part"):
            part = urllib.parse.parse_qs(
                urllib.parse.urlsplit(request.full_url).query
            )["part"][0]
            return Response(json.dumps({"etag": f"etag-{part}"}).encode())
        return Response(b'{"ok":true}')

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", urlopen)
    uploader._upload_file(
        archive,
        "events/11111111-1111-4111-8111-111111111111/download-all.zip",
        "application/zip",
    )

    paths = [urllib.parse.urlsplit(request.full_url).path for request in calls]
    assert paths.count("/booth/multipart/part") == 3
    assert paths[-1] == "/booth/multipart/complete"
    completion = json.loads(calls[-1].data)
    assert completion["parts"] == [
        {"partNumber": 1, "etag": "etag-1"},
        {"partNumber": 2, "etag": "etag-2"},
        {"partNumber": 3, "etag": "etag-3"},
    ]


def test_worker_deletion_sends_only_validated_target_to_worker(monkeypatch):
    uploader = R2Uploader(
        R2Config(
            public_base_url="https://gallery.example",
            worker_token="booth-token",
        )
    )
    requests = []
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda request, timeout: requests.append(request) or Response(b'{"ok":true}'),
    )
    event = "11111111-1111-4111-8111-111111111111"
    uploader.delete_target(f"event:{event}")
    parsed = urllib.parse.urlsplit(requests[0].full_url)
    assert parsed.path == "/booth/prefix"
    assert urllib.parse.parse_qs(parsed.query)["prefix"] == [f"events/{event}/"]
