import re
import urllib.error
from unittest.mock import MagicMock

import pytest

from engine.clock import CLOCK_SYNC_ERROR
from engine.config import R2Config
from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_session_page_key,
    r2_event_strip_key,
    r2_named_event_archive_key,
    r2_named_photo_key,
    r2_named_session_target,
    r2_named_strip_key,
)
from engine.r2 import R2Uploader, link_outdated, signed_url_expiring


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
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


def test_upload_session_returns_signed_private_guest_page(tmp_path):
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")

    url = uploader.upload_session(tmp_path, event, session)

    strip_key = r2_event_strip_key(event, session)
    page_key = r2_event_session_page_key(event, session)
    assert url == f"https://signed.example/{page_key}?expires=604800"
    assert uploader.client.upload_file.call_args.args[2] == strip_key
    page_upload = uploader.client.put_object.call_args
    assert page_upload.kwargs["Key"] == page_key
    assert page_upload.kwargs["ContentType"] == "text/html; charset=utf-8"
    page = page_upload.kwargs["Body"].decode()
    assert f"https://signed.example/{strip_key}?expires=604800" in page
    assert 'id="download-strip"' in page


def test_named_session_uploads_strip_and_original_photos(tmp_path):
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    folder = "sarah-james-2026-06-14"
    stem = "sarah-james-strip-00001"
    target = r2_named_session_target(event, session, folder, stem)
    for filename in ("strip.jpg", "photo-1.jpg", "photo-2.jpg", "photo-3.jpg"):
        (tmp_path / filename).write_bytes(b"jpeg")

    url = uploader.upload_session(
        tmp_path,
        event,
        session,
        cloud_target=target,
    )

    uploaded_keys = [call.args[2] for call in uploader.client.upload_file.call_args_list]
    assert uploaded_keys == [
        r2_named_photo_key(folder, stem, 1),
        r2_named_photo_key(folder, stem, 2),
        r2_named_photo_key(folder, stem, 3),
        r2_named_strip_key(folder, stem),
    ]
    page_key = r2_event_session_page_key(event, session)
    assert url == f"https://signed.example/{page_key}?expires=604800"
    assert uploader.client.put_object.call_args.kwargs["Key"] == page_key


def test_r2_waits_for_clock_before_every_signed_operation(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr("engine.r2.wait_for_system_clock", lambda: waits.append(True))
    uploader = uploader_with_mock_client()
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")

    uploader.upload_session(tmp_path, "event", "session")

    assert len(waits) == 4


def test_session_page_prints_strip_once_then_shows_floating_save():
    page = R2Uploader._session_html(
        "https://signed.example/strip.jpg?x=1&signature=two"
    ).decode()

    assert "__STRIP_URL__" not in page
    assert page.count('src="https://signed.example/strip.jpg?x=1&amp;signature=two"') == 1
    assert 'localStorage.getItem("piccie-printed:" + location.pathname)' in page
    assert "prefers-reduced-motion: reduce" in page
    assert page.index('id="strip"') < page.index('id="download-strip"')
    assert '<span id="save-label">Download</span></a>' in page
    assert "Your strip didn’t load. Check your signal, then try again." in page
    assert "Press and hold the photo" in page
    assert "Save to Photos" in page
    assert "/iPad|iPhone|iPod/" in page
    assert 'navigator.platform === "MacIntel"' in page
    assert 'navigator.share({files: [photoFile]})' in page
    assert 'note.textContent = "Tap Save to Photos, then choose Save Image."' in page
    assert 'id="save-note" class="note" hidden' in page
    assert "connect-src https:" in page
    assert "&amp;signature=two" in page
    assert "—" not in page


def test_r2_replaces_raw_clock_skew_with_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.r2.wait_for_system_clock", lambda: None)
    uploader = uploader_with_mock_client()
    uploader.client.upload_file.side_effect = RuntimeError(
        "An error occurred (RequestTimeTooSkewed) when calling PutObject"
    )
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")

    with pytest.raises(RuntimeError, match="clock has not synchronized") as exc:
        uploader.upload_session(tmp_path, "event", "session")

    assert str(exc.value) == CLOCK_SYNC_ERROR


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


def test_publish_named_event_uses_readable_folder_and_lists_new_strips(tmp_path):
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    folder = "sarah-james-2026-06-14"
    strip_key = r2_named_strip_key(folder, "sarah-james-strip-00001")
    archive = tmp_path / "download-all.zip"
    archive.write_bytes(b"zip")
    uploader.client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": strip_key}], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
    ]

    url, _token = uploader.publish_event(
        event,
        "Sarah & James",
        "2026-06-14",
        archive,
        event_folder=folder,
    )

    assert url.startswith("https://signed.example/")
    assert uploader.client.upload_file.call_args.args[2] == (
        r2_named_event_archive_key(folder)
    )
    gallery = uploader.client.put_object.call_args.kwargs["Body"].decode()
    assert "Download all strips + original photos" in gallery
    assert f"https://signed.example/{strip_key}?expires=604800" in gallery
    assert (
        f"https://signed.example/{r2_named_event_archive_key(folder)}?expires=604800"
        in gallery
    )


def test_gallery_html_escapes_event_text_and_does_not_embed_credentials():
    page = R2Uploader._gallery_html(
        '<script>alert("x")</script>',
        "2026-06-14",
        [],
        "https://signed.example/archive.zip",
    ).decode()

    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "SECRET_ACCESS_KEY" not in page
    assert "access_key" not in page


def test_event_strip_listing_follows_every_page():
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

    assert uploader._event_strip_keys(event, None) == [first, second]
    assert uploader.client.list_objects_v2.call_args_list[1].kwargs[
        "ContinuationToken"
    ] == "next-page"


def test_delete_event_target_removes_every_object_under_prefix():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    object_key = f"events/{event}/sessions/old/strip.jpg"
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": object_key}],
        "IsTruncated": False,
    }

    uploader.delete_target(f"event:{event}")

    uploader.client.list_objects_v2.assert_called_once_with(
        Bucket="photos", Prefix=f"events/{event}/"
    )
    deleted = uploader.client.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert deleted == [{"Key": object_key}]


def test_delete_named_session_removes_strip_page_and_original_photos():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    folder = "sarah-james-2026-06-14"
    stem = "sarah-james-strip-00001"
    photo_key = r2_named_photo_key(folder, stem, 1)
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": photo_key}],
        "IsTruncated": False,
    }

    session = "22222222-2222-4222-8222-222222222222"
    uploader.delete_target(r2_named_session_target(event, session, folder, stem))

    deleted_directly = [
        call.kwargs["Key"] for call in uploader.client.delete_object.call_args_list
    ]
    assert deleted_directly == [
        r2_named_strip_key(folder, stem),
        r2_event_session_page_key(event, session),
    ]
    uploader.client.list_objects_v2.assert_called_once_with(
        Bucket="photos",
        Prefix=f"{folder}/photos/{stem}-photo-",
    )
    assert uploader.client.delete_objects.call_args.kwargs["Delete"]["Objects"] == [
        {"Key": photo_key}
    ]


def test_delete_named_event_removes_human_readable_folder():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"
    folder = "sarah-james-2026-06-14"
    uploader.client.list_objects_v2.return_value = {
        "Contents": [],
        "IsTruncated": False,
    }

    uploader.delete_target(f"named-event:{event}:{folder}")

    uploader.client.list_objects_v2.assert_called_once_with(
        Bucket="photos",
        Prefix=f"{folder}/",
    )


def test_delete_event_archive_target_removes_only_download_bundle():
    uploader = uploader_with_mock_client()
    event = "11111111-1111-4111-8111-111111111111"

    uploader.delete_target(f"event-archive:{event}")

    uploader.client.delete_object.assert_called_once_with(
        Bucket="photos",
        Key=r2_event_archive_key(event),
    )
    uploader.client.delete_objects.assert_not_called()


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


def test_guest_download_follows_landing_page_to_uploaded_strip(tmp_path, monkeypatch):
    strip = tmp_path / "strip.jpg"
    strip.write_bytes(b"jpeg bytes")
    uploader = uploader_with_mock_client()
    page = uploader._session_html(
        "https://signed.example/strip.jpg?x=1&signature=two"
    )
    requested = []

    def open_url(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith("index.html"):
            return Response(page)
        return Response(b"jpeg bytes")

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", open_url)

    uploader.verify_guest_download("https://signed.example/index.html", strip)

    assert requested == [
        "https://signed.example/index.html",
        "https://signed.example/strip.jpg?x=1&signature=two",
    ]


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
        assert "guest page" in str(exc)
    else:
        raise AssertionError("mismatched guest bytes should fail the upload")


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



def public_uploader(domain="piccie.link"):
    uploader = R2Uploader(
        R2Config(
            "acct",
            "key",
            "secret",
            "photos",
            public_bucket="piccie-links",
            public_domain=domain,
            link_secret="test-link-secret",
        )
    )
    uploader.client = MagicMock()
    uploader.client.generate_presigned_url.side_effect = (
        lambda _operation, Params, ExpiresIn: f"https://signed.example/{Params['Key']}"
    )
    return uploader


NAMED_TARGET = r2_named_session_target(
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "sarah-james-2026-06-14",
    "sarah-james-strip-00001",
)


def test_custom_domain_guest_link_is_short_and_unguessable(tmp_path):
    uploader = public_uploader()
    for name in ("strip.jpg", "photo-1.jpg", "photo-2.jpg", "photo-3.jpg"):
        (tmp_path / name).write_bytes(b"jpeg")

    url = uploader.upload_session(
        tmp_path,
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        cloud_target=NAMED_TARGET,
    )

    assert re.fullmatch(r"https://piccie\.link/[\w-]{6}/[\w-]{10}", url)
    assert len(url) <= 42  # fits a 29x29 QR code
    copy = uploader.client.copy_object.call_args.kwargs
    assert copy["Bucket"] == "piccie-links"
    assert copy["CopySource"] == {
        "Bucket": "photos",
        "Key": "sarah-james-2026-06-14/strips/sarah-james-strip-00001.jpg",
    }
    assert copy["Key"] == url.removeprefix("https://piccie.link/") + ".jpg"
    page = uploader.client.put_object.call_args.kwargs
    assert page["Bucket"] == "piccie-links"
    assert page["Key"] == url.removeprefix("https://piccie.link/")
    assert page["CacheControl"] == "private"
    assert f"{url}.jpg" in page["Body"].decode()
    # Readable names and signed private links never reach the public bucket.
    assert "sarah" not in url
    assert "signed.example" not in page["Body"].decode()


def test_deleting_a_strip_removes_its_public_copy_even_after_domain_is_off(tmp_path):
    (tmp_path / "strip.jpg").write_bytes(b"jpeg")
    for name in ("photo-1.jpg", "photo-2.jpg", "photo-3.jpg"):
        (tmp_path / name).write_bytes(b"jpeg")
    url = public_uploader().upload_session(
        tmp_path,
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        cloud_target=NAMED_TARGET,
    )
    public_key = url.removeprefix("https://piccie.link/")
    uploader = public_uploader(domain="")
    uploader.client.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}

    uploader.delete_target(NAMED_TARGET)

    public_deletes = [
        call.kwargs["Key"]
        for call in uploader.client.delete_object.call_args_list
        if call.kwargs["Bucket"] == "piccie-links"
    ]
    assert public_deletes == [public_key, f"{public_key}.jpg"]


def test_deleting_an_event_removes_its_public_prefix():
    uploader = public_uploader()
    uploader.client.list_objects_v2.return_value = {
        "Contents": [{"Key": "abc123/page"}],
        "IsTruncated": False,
    }

    uploader.delete_target("named-event:11111111-1111-4111-8111-111111111111:wedding-2026-06-14")

    buckets = [call.kwargs["Bucket"] for call in uploader.client.delete_objects.call_args_list]
    assert buckets == ["photos", "piccie-links"]
    public_prefix = uploader.client.list_objects_v2.call_args_list[1].kwargs["Prefix"]
    assert re.fullmatch(r"[\w-]{6}/", public_prefix)


def test_custom_domain_event_gallery_and_zip_are_public_copies(tmp_path):
    uploader = public_uploader()
    strip = "wedding-2026-06-14/strips/wedding-strip-00001.jpg"
    uploader.client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": strip}], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
    ]
    archive = tmp_path / "all.zip"
    archive.write_bytes(b"zip")
    event = "11111111-1111-4111-8111-111111111111"

    url, token = uploader.publish_event(
        event, "Wedding", "2026-06-14", archive, event_folder="wedding-2026-06-14"
    )

    assert url.startswith("https://piccie.link/")
    copies = {call.kwargs["CopySource"]["Key"]: call.kwargs["Key"] for call in uploader.client.copy_object.call_args_list}
    share_key = url.removeprefix("https://piccie.link/")
    assert copies["wedding-2026-06-14/download-all.zip"] == f"{share_key}.zip"
    gallery = uploader.client.put_object.call_args.kwargs
    assert gallery["Bucket"] == "piccie-links"
    assert f"https://piccie.link/{copies[strip]}" in gallery["Body"].decode()
    assert "signed.example" not in gallery["Body"].decode()

    uploader.disable_share(event, token)
    public_deletes = [
        call.kwargs["Key"]
        for call in uploader.client.delete_object.call_args_list
        if call.kwargs["Bucket"] == "piccie-links"
    ]
    assert public_deletes == [share_key, f"{share_key}.zip"]


def _domain_check(monkeypatch, *, private_leaks):
    uploader = public_uploader()
    bodies = {}
    uploader.client.put_object.side_effect = lambda **kw: bodies.__setitem__(kw["Key"], kw["Body"])
    copied = set()
    uploader.client.copy_object.side_effect = lambda **kw: copied.add(kw["Key"])

    def fake_urlopen(request, timeout):
        key = request.full_url.removeprefix("https://piccie.link/")
        if key in copied or private_leaks:
            return Response(bodies[key])
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("engine.r2.urllib.request.urlopen", fake_urlopen)
    return uploader


def test_domain_check_passes_when_only_the_public_bucket_is_served(monkeypatch):
    uploader = _domain_check(monkeypatch, private_leaks=False)

    uploader.check_public_domain()

    deleted = {(c.kwargs["Bucket"], c.kwargs["Key"]) for c in uploader.client.delete_object.call_args_list}
    assert len(deleted) == 3


def test_domain_check_refuses_a_domain_on_the_private_bucket(monkeypatch):
    uploader = _domain_check(monkeypatch, private_leaks=True)

    with pytest.raises(RuntimeError, match="private bucket photos"):
        uploader.check_public_domain()

    assert uploader.client.delete_object.call_count == 3


def test_link_outdated_follows_domain_changes():
    assert link_outdated("https://piccie.link/abc/def", "piccie.link") is False
    assert link_outdated("https://acct.r2.cloudflarestorage.com/x?X-Amz-Signature=1", "piccie.link") is True
    assert link_outdated("https://piccie.link/abc/def", "") is True
