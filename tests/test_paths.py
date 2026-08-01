from engine.paths import (
    r2_event_archive_key,
    r2_event_gallery_key,
    r2_event_session_page_key,
    r2_event_strip_key,
    r2_named_event_archive_key,
    r2_named_event_folder,
    r2_named_photo_key,
    r2_named_session_target,
    r2_named_strip_key,
    r2_named_strip_stem,
    r2_session_target,
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
    assert r2_event_session_page_key(event, session) == (
        f"events/{event}/sessions/{session}/index.html"
    )
    assert r2_event_archive_key(event) == f"events/{event}/download-all.zip"
    assert r2_session_target(event, session) == f"event-session:{event}:{session}"
    assert r2_event_gallery_key(event, token).startswith(f"events/{event}/shares/")
    assert r2_event_gallery_key(event, token).endswith(".html")
    assert token not in r2_event_gallery_key(event, token)


def test_named_event_media_keys_are_human_readable_and_stably_indexed():
    event = "11111111-1111-4111-8111-111111111111"
    folder = r2_named_event_folder("Sarah & James", "2026-06-14")
    stem = r2_named_strip_stem("Sarah & James", 1)

    assert folder == "sarah-james-2026-06-14"
    assert stem == "sarah-james-strip-00001"
    assert r2_named_strip_key(folder, stem) == (
        "sarah-james-2026-06-14/strips/sarah-james-strip-00001.jpg"
    )
    assert r2_named_photo_key(folder, stem, 3).endswith(
        "/photos/sarah-james-strip-00001-photo-03.jpg"
    )
    assert r2_named_event_archive_key(folder) == (
        "sarah-james-2026-06-14/download-all.zip"
    )
    session = "22222222-2222-4222-8222-222222222222"
    assert r2_named_session_target(event, session, folder, stem) == (
        f"named-event-session:{event}:{session}:{folder}:{stem}"
    )
