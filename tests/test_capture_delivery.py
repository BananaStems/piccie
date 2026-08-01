from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from engine import capture_delivery as capture_delivery_module
from engine.atomicio import jpeg_is_intact
from engine.capture_delivery import CaptureDelivery, CaptureDeliveryError
from engine.storage import Storage
from engine.templates import TemplateRegistry


class FakeCamera:
    available = True
    error: Exception | None = None

    def capture_to_file(self, path: Path, label: str = "") -> None:
        if self.error:
            raise self.error
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 480), "#a77b63").save(path, format="JPEG")


class FakeUploads:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.jobs = []
        self.resume_calls = 0

    def enqueue_best_effort(self, job) -> bool:
        if not self.accept:
            return False
        self.jobs.append(job)
        return True

    def resume_pending(self) -> int:
        self.resume_calls += 1
        return 0


@pytest.fixture
def capture_delivery(tmp_path, monkeypatch):
    storage = Storage(tmp_path / "piccie.db", tmp_path / "events")
    camera = FakeCamera()
    uploads = FakeUploads()
    templates = TemplateRegistry(custom_templates_dir=tmp_path / "templates")
    monkeypatch.setattr(capture_delivery_module, "data_degraded", lambda: False)
    monkeypatch.setattr(capture_delivery_module, "disk_low", lambda: False)
    monkeypatch.setattr(capture_delivery_module, "disk_free_mb", lambda: 4096)
    delivery = CaptureDelivery(storage, camera, templates, uploads)
    return delivery, storage, camera, uploads


def create_event(storage: Storage):
    return storage.create_event("Wedding", "2099-08-01", "classic")


def test_complete_lifecycle_and_duplicate_finalize(capture_delivery):
    delivery, storage, _camera, uploads = capture_delivery
    event = create_event(storage)

    session = delivery.start(event.id)
    for index in (1, 2, 3):
        delivery.capture(session.id, index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _call: delivery.finalize(session.id), range(2)))

    assert all(result.finalized_at for result in results)
    assert storage.get_event(event.id).photo_count == 1
    assert jpeg_is_intact(Path(session.local_path) / "strip.jpg")
    meta = storage.get_session_meta(storage.get_session(session.id))
    assert meta["session_id"] == session.id
    assert meta["event_id"] == event.id
    assert meta["strip_number"] == 1
    assert meta["r2_target"].endswith(":wedding-strip-00001")
    assert uploads.jobs


def test_finalize_succeeds_when_queue_is_full(capture_delivery):
    delivery, storage, _camera, uploads = capture_delivery
    uploads.accept = False
    event = create_event(storage)
    session = delivery.start(event.id)
    for index in (1, 2, 3):
        delivery.capture(session.id, index)

    result = delivery.finalize(session.id)

    assert result.finalized_at
    assert jpeg_is_intact(Path(session.local_path) / "strip.jpg")
    assert storage.get_event(event.id).photo_count == 1
    assert uploads.jobs == []


def test_recover_repairs_intact_strip_and_resumes_upload(capture_delivery):
    delivery, storage, _camera, uploads = capture_delivery
    event = create_event(storage)
    session = storage.create_session(event.id)
    Image.new("RGB", (10, 30), "white").save(
        Path(session.local_path) / "strip.jpg",
        format="JPEG",
    )

    delivery.recover()

    repaired = storage.get_session(session.id)
    assert repaired.finalized_at
    assert storage.get_event(event.id).photo_count == 1
    assert storage.get_session_meta(repaired)["r2_target"].endswith(
        ":wedding-strip-00001"
    )
    assert uploads.resume_calls == 1


def test_recover_does_not_count_corrupt_strip(capture_delivery):
    delivery, storage, _camera, uploads = capture_delivery
    event = create_event(storage)
    session = storage.create_session(event.id)
    storage.mark_session_finalized(session.id)
    (Path(session.local_path) / "strip.jpg").write_bytes(b"not-a-jpeg")

    delivery.recover()

    assert storage.get_session(session.id).finalized_at is None
    assert storage.get_event(event.id).photo_count == 0
    assert uploads.resume_calls == 1


def test_start_rejects_unready_booth_before_creating_session(
    capture_delivery,
    monkeypatch,
):
    delivery, storage, camera, _uploads = capture_delivery
    event = create_event(storage)

    camera.available = False
    with pytest.raises(CaptureDeliveryError) as unavailable:
        delivery.start(event.id)
    assert (unavailable.value.status_code, unavailable.value.detail) == (
        503,
        "Camera unavailable",
    )

    camera.available = True
    monkeypatch.setattr(capture_delivery_module, "data_degraded", lambda: True)
    with pytest.raises(CaptureDeliveryError) as degraded:
        delivery.start(event.id)
    assert degraded.value.status_code == 503
    assert "degraded" in degraded.value.detail
    assert storage.list_event_sessions(event.id) == []


def test_capture_and_finalize_preserve_public_errors(capture_delivery):
    delivery, storage, camera, _uploads = capture_delivery
    event = create_event(storage)
    session = delivery.start(event.id)

    with pytest.raises(CaptureDeliveryError) as invalid:
        delivery.capture(session.id, 4)
    assert (invalid.value.status_code, invalid.value.detail) == (
        400,
        "photo_index must be 1, 2, or 3",
    )

    camera.error = RuntimeError("sensor stalled")
    with pytest.raises(CaptureDeliveryError) as failed:
        delivery.capture(session.id, 1)
    assert (failed.value.status_code, failed.value.detail) == (
        500,
        "Capture failed: sensor stalled",
    )

    camera.error = None
    with pytest.raises(CaptureDeliveryError) as missing:
        delivery.finalize(session.id)
    assert (missing.value.status_code, missing.value.detail) == (
        400,
        "Missing photo-1.jpg",
    )
