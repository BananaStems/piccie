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


def test_session_page_uses_full_width_strip_and_fixed_download_menu():
    page = R2Uploader._session_html(
        "https://signed.example/strip.jpg?x=1&signature=two"
    ).decode()

    assert 'min-height:100svh' in page
    assert 'min-height:100dvh' in page
    assert '.photo{width:100%}' in page
    assert '.photo img{display:block;width:100%;height:auto' in page
    assert 'border-radius:0' in page
    assert 'position:fixed' in page
    assert 'bottom:0' in page
    assert 'class="actions-inner"' in page
    assert page.index('class="photo"') < page.index('id="download-strip"')
    assert "<h1>" not in page
    assert ">Download</a>" in page
    assert "Download photo strip" not in page
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
