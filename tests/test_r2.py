from unittest.mock import MagicMock
from engine.config import R2Config
from engine.paths import r2_event_archive_key, r2_event_strip_key, r2_share_key
from engine.r2 import R2Uploader


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

    url, image_url, returned_token = uploader.upload_session(
        tmp_path, event, session, "Sarah & James", "2026-06-14", share_token=token
    )

    assert url == image_url == f"https://gallery.example/s/{token}"
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
