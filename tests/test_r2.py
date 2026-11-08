from unittest.mock import MagicMock

from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_prefix,
    r2_event_strip_key,
    r2_legacy_share_keys,
    r2_legacy_strip_key,
)
from engine.r2 import R2Uploader, link_outdated, signed_url_expiring


class Response:
    """A signed-URL reply that honours a 1-byte Range request, like R2."""

    def __init__(self, body, ranged=True):
        self.body = body
        self.headers = (
            {"Content-Range": f"bytes 0-0/{len(body)}"}
            if ranged
            else {"Content-Length": str(len(body))}
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


def uploader_with_mock_client(public_domain=""):
    uploader = R2Uploader(
        R2Config("acct", "key", "secret", "photos", public_domain=public_domain)
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
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")

    url = uploader.upload_session(tmp_path, event, session)

    strip_key = r2_event_strip_key(event, session)
    assert url == f"https://signed.example/{strip_key}?expires=604800"
    assert uploader.client.upload_file.call_args.args[2] == strip_key
    uploader.client.put_object.assert_not_called()


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
    archive_key = r2_event_archive_key(event, token)
    assert uploader.client.upload_file.call_args.args[2] == archive_key
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
    assert f"https://signed.example/{archive_key}?expires=604800" in gallery
    assert gallery_upload.kwargs["ContentType"] == "text/html; charset=utf-8"
    deleted = uploader.client.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert {"Key": r2_event_gallery_key(event, previous)} in deleted
    assert {"Key": r2_event_archive_key(event, previous)} in deleted


def test_gallery_html_escapes_event_text_and_does_not_embed_credentials():
    uploader = uploader_with_mock_client()
    uploader.client.list_objects_v2.return_value = {"Contents": []}

    page = uploader._gallery_html(
        "11111111-1111-4111-8111-111111111111",
        '<script>alert("x")</script>',
        "2026-06-14",
        "events/x/shares/a.zip",
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
    legacy = r2_legacy_strip_key(event, "44444444-4444-4444-8444-444444444444")
    uploader.client.list_objects_v2.side_effect = [
        {
            "Contents": [{"Key": first}],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        },
        {
            "Contents": [{"Key": second}, {"Key": r2_event_gallery_key(event, "t")}],
            "IsTruncated": False,
        },
        {"Contents": [{"Key": legacy}], "IsTruncated": False},
    ]

    page = uploader._gallery_html(event, "Wedding", "2026-06-14", "a.zip").decode()

    assert first in page
    assert second in page
    assert legacy in page
    assert ".html" not in page.split("<section")[1]
    assert uploader.client.list_objects_v2.call_args_list[1].kwargs[
        "ContinuationToken"
    ] == "next-page"


def test_delete_event_target_removes_every_object_under_prefix():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    uploader.client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": r2_event_strip_key(event, "s1")}], "IsTruncated": False},
        {"Contents": [{"Key": r2_legacy_strip_key(event, "s0")}], "IsTruncated": False},
    ]

    uploader.delete_target(f"event:{event}")

    prefixes = [c.kwargs["Prefix"] for c in uploader.client.list_objects_v2.call_args_list]
    assert prefixes == [r2_event_prefix(event), f"events/{event}/"]
    deleted = [
        c.kwargs["Delete"]["Objects"] for c in uploader.client.delete_objects.call_args_list
    ]
    assert deleted == [
        [{"Key": r2_event_strip_key(event, "s1")}],
        [{"Key": r2_legacy_strip_key(event, "s0")}],
    ]


def test_delete_session_target_removes_new_and_legacy_strip():
    uploader = uploader_with_mock_client()
    event, session = "e1", "s1"
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": r2_legacy_strip_key(event, session)}],
        "IsTruncated": False,
    }

    uploader.delete_target(f"event-session:{event}:{session}")

    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos", Key=r2_event_strip_key(event, session)
    )
    uploader.client.list_objects_v2.assert_called_once_with(
        Bucket="photos", Prefix=f"events/{event}/sessions/{session}/"
    )


def test_legacy_clear_tombstone_spares_strips_taken_after_the_clear():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"

    uploader.delete_target(f"event-content:{event}")

    uploader.client.list_objects_v2.assert_not_called()
    uploader.client.delete_objects.assert_not_called()
    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos", Key=f"events/{event}/download-all.zip"
    )


def test_disable_event_share_removes_page_and_its_zip():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    token = f"{event}.secret"

    uploader.disable_share(event, token)

    deleted = uploader.client.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert deleted == [
        {"Key": r2_event_gallery_key(event, token)},
        {"Key": r2_event_archive_key(event, token)},
        *({"Key": key} for key in r2_legacy_share_keys(event, token)),
        {"Key": f"events/{event}/download-all.zip"},
    ]


def test_signed_url_expiring_reads_sigv4_lifetime():
    from datetime import datetime, timedelta, timezone

    def signed(age: timedelta) -> str:
        stamp = (datetime.now(timezone.utc) - age).strftime("%Y%m%dT%H%M%SZ")
        return f"https://r2.example/k?X-Amz-Date={stamp}&X-Amz-Expires=604800&X-Amz-Signature=x"

    assert not signed_url_expiring(signed(timedelta(days=1)))
    assert signed_url_expiring(signed(timedelta(days=6, hours=1)))
    assert signed_url_expiring(signed(timedelta(days=8)))
    assert not signed_url_expiring("https://gallery.example/g/token")


def test_real_presigned_url_is_fresh():
    url = R2Uploader(R2Config("acct", "key", "secret", "photos")).download_url("k")
    assert "X-Amz-Date=" in url and not signed_url_expiring(url)


def test_guest_download_must_match_uploaded_strip(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg bytes")
    uploader = uploader_with_mock_client()
    ranges = []

    def urlopen(request, timeout):
        ranges.append(request.get_header("Range"))
        return Response(b"jpeg bytes")

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", urlopen)

    uploader.verify_guest_download("https://signed.example/object.jpg", strip)

    assert ranges == ["bytes=0-0"]


def test_guest_download_accepts_server_that_ignores_range(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg bytes")
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen",
        lambda _request, timeout: Response(b"jpeg bytes", ranged=False),
    )

    uploader_with_mock_client().verify_guest_download("https://signed.example/o.jpg", strip)


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
        assert "guest link could not return it" in str(exc)
    else:
        raise AssertionError("mismatched guest bytes should fail the upload")


def test_custom_domain_gives_plain_short_links():
    uploader = uploader_with_mock_client(public_domain="get.piccie.uk")
    key = r2_event_strip_key("e1", "s1")

    assert uploader.download_url(key) == f"https://get.piccie.uk/{key}"
    uploader.client.generate_presigned_url.assert_not_called()


def test_link_outdated_follows_the_domain_setting():
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    signed = f"https://acct.r2.cloudflarestorage.com/photos/k?X-Amz-Date={stamp}&X-Amz-Expires=604800&X-Amz-Signature=x"
    plain = "https://get.piccie.uk/k.jpg"

    assert not link_outdated(signed, "")
    assert link_outdated(plain, "")  # domain turned off: sign again
    assert link_outdated(signed, "get.piccie.uk")  # domain turned on: switch now
    assert not link_outdated(plain, "get.piccie.uk")
    assert link_outdated(plain, "photos.example.com")


def test_custom_domain_check_serves_a_probe_then_deletes_it(monkeypatch):
    uploader = uploader_with_mock_client()
    fetched = []

    def urlopen(request, timeout):
        fetched.append(request.full_url)
        body = uploader.client.put_object.call_args.kwargs["Body"]
        return Response(body)

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", urlopen)

    uploader.check_public_domain("get.piccie.uk")

    key = uploader.client.put_object.call_args.kwargs["Key"]
    assert fetched == [f"https://get.piccie.uk/{key}"]
    uploader.client.delete_object.assert_called_once_with(Bucket="photos", Key=key)


def test_custom_domain_check_rejects_a_domain_that_serves_something_else(monkeypatch):
    import pytest

    uploader = uploader_with_mock_client()
    monkeypatch.setattr(
        "engine.r2.urllib.request.urlopen", lambda _request, timeout: Response(b"<html>")
    )

    with pytest.raises(RuntimeError, match="not with this bucket's files"):
        uploader.check_public_domain("photos.example.com")
    uploader.client.delete_object.assert_called_once()
