from __future__ import annotations

import threading
from pathlib import Path

from engine.atomicio import jpeg_is_intact
from engine.camera import CameraService
from engine.composer import compose_strip
from engine.paths import r2_session_target
from engine.storage import (
    Event,
    Session,
    Storage,
    data_degraded,
    disk_free_mb,
    disk_low,
)
from engine.templates import TemplateRegistry
from engine.upload_queue import UploadJob, UploadQueue


class CaptureDeliveryError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class CaptureDelivery:
    """Own the durable path from a guest session to upload handoff."""

    def __init__(
        self,
        storage: Storage,
        camera: CameraService,
        templates: TemplateRegistry,
        uploads: UploadQueue,
    ) -> None:
        self.storage = storage
        self.camera = camera
        self.templates = templates
        self.uploads = uploads
        # ponytail: one booth composes one strip at a time; use per-session locks
        # only if Piccie ever supports concurrent guest capture stations.
        self._finalize_lock = threading.Lock()

    def start(self, event_id: str) -> Session:
        event = self.storage.get_event(event_id)
        if not event:
            raise CaptureDeliveryError(404, "Event not found")
        if event.is_concluded():
            raise CaptureDeliveryError(
                409,
                "This event has concluded. Edit its end time to launch it again.",
            )
        if not self.camera.available:
            raise CaptureDeliveryError(503, "Camera unavailable")
        if data_degraded():
            raise CaptureDeliveryError(
                503,
                "Photo storage is degraded. Restart the booth and repair /data "
                "before taking photos.",
            )
        if disk_low():
            raise CaptureDeliveryError(
                507,
                f"Storage almost full ({disk_free_mb()} MB free). Delete old events to continue.",
            )
        return self.storage.create_session(event_id)

    def capture(self, session_id: str, photo_index: int) -> None:
        if photo_index not in (1, 2, 3):
            raise CaptureDeliveryError(400, "photo_index must be 1, 2, or 3")
        session, _event = self._session_event(session_id)
        path = Path(session.local_path) / f"photo-{photo_index}.jpg"
        try:
            self.camera.capture_to_file(path, label=f"Photo {photo_index}")
        except Exception as exc:
            raise CaptureDeliveryError(500, f"Capture failed: {exc}") from exc

    def finalize(self, session_id: str) -> Session:
        with self._finalize_lock:
            session, event = self._session_event(session_id)
            session_dir = Path(session.local_path)
            strip_path = session_dir / "strip.jpg"

            if not jpeg_is_intact(strip_path):
                photos = [session_dir / f"photo-{index}.jpg" for index in range(1, 4)]
                for photo in photos:
                    if not photo.exists():
                        raise CaptureDeliveryError(400, f"Missing {photo.name}")
                template = self.templates.load(event.template_id)
                compose_strip(
                    template,
                    photos,
                    event.strip_line1(),
                    event.line2,
                    event.date,
                    strip_path,
                    date_separator=event.date_separator,
                )
                if not jpeg_is_intact(strip_path):
                    raise RuntimeError("Composed strip is missing or corrupt")

            return self._commit(session, event)

    def recover(self) -> None:
        self.storage.prune_abandoned_sessions()
        self.storage.sweep_orphan_dirs()
        self.storage.reconcile_finalized_sessions()

        # Repair metadata after a power loss between strip rename and meta write.
        # Startup already scans every session for reconciliation, so this second
        # bounded local pass buys recoverability without another public interface.
        for event in self.storage.list_events():
            for session in self.storage.list_event_sessions(event.id):
                if jpeg_is_intact(Path(session.local_path) / "strip.jpg"):
                    self._repair_meta(session, event)
        self.uploads.resume_pending()

    def _session_event(self, session_id: str) -> tuple[Session, Event]:
        session = self.storage.get_session(session_id)
        if not session:
            raise CaptureDeliveryError(404, "Session not found")
        event = self.storage.get_event(session.event_id)
        if not event:
            raise CaptureDeliveryError(404, "Event not found")
        return session, event

    def _meta(self, session: Session, event: Event) -> dict:
        return {
            "session_id": session.id,
            "event_id": event.id,
            "r2_target": r2_session_target(event.id, session.id),
            "upload_status": session.upload_status,
        }

    def _commit(self, session: Session, event: Event) -> Session:
        self.storage.mark_session_finalized(session.id)
        refreshed = self.storage.get_session(session.id) or session
        meta = self._repair_meta(refreshed, event)
        if refreshed.upload_status != "complete":
            self.uploads.enqueue_best_effort(
                UploadJob(
                    session_id=refreshed.id,
                    event_id=event.id,
                    session_dir=Path(refreshed.local_path),
                    cloud_target=meta["r2_target"],
                )
            )
        return refreshed

    def _repair_meta(self, session: Session, event: Event) -> dict:
        patch = self._meta(session, event)
        current = self.storage.get_session_meta(session)
        if any(current.get(key) != value for key, value in patch.items()):
            return self.storage.merge_session_meta(session, patch)
        return current
