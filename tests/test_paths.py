from engine.paths import (
    r2_event_archive_key,
    r2_event_manifest_key,
    r2_event_strip_key,
    r2_session_target,
    r2_share_key,
    slugify,
)


def test_slugify():
    assert slugify("Sarah & James") == "sarah-james"
    assert slugify("  Hello World!  ") == "hello-world"


def test_private_event_keys():
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    token = f"{event}.secret"
    assert r2_event_strip_key(event, session) == f"events/{event}/sessions/{session}/strip.jpg"
    assert r2_event_manifest_key(event) == f"events/{event}/manifest.json"
    assert r2_event_archive_key(event) == f"events/{event}/download-all.zip"
    assert r2_session_target(event, session) == f"event-session:{event}:{session}"
    assert r2_share_key(event, token).startswith(f"events/{event}/shares/")
    assert token not in r2_share_key(event, token)
