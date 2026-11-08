from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_prefix,
    r2_event_strip_key,
    r2_legacy_share_keys,
    r2_legacy_strip_key,
    r2_session_target,
    slugify,
)


def test_slugify():
    assert slugify("Sarah & James") == "sarah-james"
    assert slugify("  Hello World!  ") == "hello-world"


def test_event_keys_are_short_and_hide_ids():
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    token = f"{event}.secret"
    strip = r2_event_strip_key(event, session)
    assert strip.startswith(r2_event_prefix(event)) and strip.endswith(".jpg")
    assert len(strip) == len("12345678/12345678901.jpg")
    assert event not in strip and session not in strip
    assert r2_event_strip_key(event, session) == strip  # deterministic, so deletes find it
    assert r2_event_archive_key(event, token) == r2_event_gallery_key(event, token)[:-4] + "zip"
    assert r2_event_gallery_key(event, token).startswith(r2_event_prefix(event))
    assert token not in r2_event_gallery_key(event, token)
    assert r2_session_target(event, session) == f"event-session:{event}:{session}"


def test_legacy_keys_match_1_0_6():
    event = "11111111-1111-4111-8111-111111111111"
    session = "22222222-2222-4222-8222-222222222222"
    assert r2_legacy_strip_key(event, session) == f"events/{event}/sessions/{session}/strip.jpg"
    assert all(
        key.startswith(f"events/{event}/shares/")
        for key in r2_legacy_share_keys(event, f"{event}.secret")
    )
