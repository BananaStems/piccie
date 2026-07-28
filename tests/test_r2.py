from unittest.mock import MagicMock

from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_strip_key,
)
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


def uploader_with_mock_client():
    uploader = R2Uploader(
        R2Config("acct", "key", "secret", "photos")
    )
    uploader.client = MagicMock()
    uploader.client.generate_presigned_url.side_effect = (
        lambda _operation, Params, ExpiresIn: (
            f"https://signed.example/{Params['Key']}?expires={ExpiresIn}"
        )
    )
    return uploader


def test_eu_jurisdiction_uses_eu_endpoint():
    uploader = R2Uploader(
        R2Config(
            "acct",
            "key",
            "secret",
            "photos",
            jurisdiction="eu",
        )
    )
    assert uploader.client.meta.endpoint_url == "https://acct.eu.r2.cloudflarestorage.com"


def test_upload_session_returns_signed_private_object_url(tmp_path):
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    token = f"{event}.{session}.secret"
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")

    url, returned_token = uploader.upload_session(
        tmp_path, event, session, "Sarah & James", "2026-06-14", share_token=token
    )

    strip_key = r2_event_strip_key(event, session)
    assert url == f"https://signed.example/{strip_key}?expires=604800"
    assert returned_token == token
    assert uploader.client.upload_file.call_args.args[2] == strip_key
    keys = {call.kwargs["Key"] for call in uploader.client.put_object.call_args_list}
    assert keys == {f"events/{event}/manifest.json"}


def test_publish_event_uploads_static_gallery_then_revokes_old_link(tmp_path):
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    archive = tmp_path / "download-all.zip"
    archive.write_bytes(b"zip")
    previous = f"{event}.old"
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": r2_event_strip_key(event, session)}],
        "IsTruncated": False,
    }

    url, token = uploader.publish_event(
        event, "Sarah & James", "2026-06-14", archive, previous
    )

    gallery_key = r2_event_gallery_key(event, token)
    assert url == f"https://signed.example/{gallery_key}?expires=604800"
    assert token.startswith(f"{event}.")
    assert uploader.client.upload_file.call_args.args[2] == r2_event_archive_key(event)
    gallery_upload = [
        call for call in uploader.client.put_object.call_args_list
        if call.kwargs["Key"] == gallery_key
    ][0]
    gallery = gallery_upload.kwargs["Body"].decode()
    assert "Sarah &amp; James" in gallery
    assert (
        f"https://signed.example/{r2_event_strip_key(event, session)}?expires=604800"
        in gallery
    )
    assert gallery_upload.kwargs["ContentType"] == "text/html; charset=utf-8"
    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos",
        Key=r2_event_gallery_key(event, previous),
    )


def test_gallery_html_escapes_event_text_and_does_not_embed_credentials():
    uploader = uploader_with_mock_client()
    uploader.client.list_objects_v2.return_value = {"Contents": []}

    page = uploader._gallery_html(
        "11111111-1111-4111-8111-111111111111",
        '<script>alert("x")</script>',
        "2026-06-14",
    ).decode()

    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "SECRET_ACCESS_KEY" not in page
    assert "access_key" not in page


def test_gallery_html_lists_every_paginated_strip():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    first = r2_event_strip_key(
        event, "22222222-2222-4222-8222-222222222222"
    )
    second = r2_event_strip_key(
        event, "33333333-3333-4333-8333-333333333333"
    )
    uploader.client.list_objects_v2.side_effect = [
        {
            "Contents": [{"Key": first}],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        },
        {
            "Contents": [{"Key": second}],
            "IsTruncated": False,
        },
    ]

    page = uploader._gallery_html(event, "Wedding", "2026-06-14").decode()

    assert first in page
    assert second in page
    assert uploader.client.list_objects_v2.call_args_list[1].kwargs[
        "ContinuationToken"
    ] == "next-page"


def test_delete_event_target_removes_every_object_under_prefix():
    uploader = uploader_with_mock_client()
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


def test_disable_event_share_removes_exact_static_page():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    token = f"{event}.secret"

    uploader.disable_share(event, token)

    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos",
        Key=r2_event_gallery_key(event, token),
    )


def test_guest_download_must_match_uploaded_strip(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg bytes")
    uploader = uploader_with_mock_client()
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda _request, timeout: Response(b"jpeg bytes"),
    )

    uploader.verify_guest_download("https://signed.example/object.jpg", strip)


def test_guest_download_mismatch_fails_closed(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"expected")
    uploader = uploader_with_mock_client()
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda _request, timeout: Response(b"wrong"),
    )
    monkeypatch.setattr("engine.r2.time.sleep", lambda _seconds: None)

    try:
        uploader.verify_guest_download(
            "https://signed.example/object.jpg",
            strip,
            attempts=2,
        )
    except RuntimeError as exc:
        assert "signed download URL" in str(exc)
    else:
        raise AssertionError("mismatched guest bytes should fail the upload")
