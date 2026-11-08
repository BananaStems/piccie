from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from engine.atomicio import jpeg_is_intact
from engine.config import ConfigStore
from engine.paths import r2_session_target
from engine.r2 import R2Uploader
from engine.storage import Storage

logger = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 50
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 2
RESCAN_INTERVAL_SECONDS = 30


@dataclass
class UploadJob:
    session_id: str
    event_id: str
    session_dir: Path


class UploadQueue:
    def __init__(self, storage: Storage, config_store: ConfigStore) -> None:
        self.storage = storage
        self.config_store = config_store
        self._queue: queue.Queue[UploadJob | None] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._uploader: R2Uploader | None = None
        self._cloud_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._cloud_reachable: bool | None = None
        self._cloud_error: str | None = None
        self._stop_event = threading.Event()
        # Session ids currently queued or being processed — so the periodic
        # rescan never double-enqueues a job that is already in flight.
        self._inflight: set[str] = set()
        self._inflight_events: dict[str, str] = {}
        self._inflight_lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._rescan_thread = threading.Thread(target=self._rescan_loop, daemon=True)
        self._rescan_thread.start()

    @property
    def cloud_health(self) -> tuple[bool | None, str | None]:
        with self._cloud_lock:
            return self._cloud_reachable, self._cloud_error

    def _set_cloud_health(self, reachable: bool, error: str | None = None) -> None:
        with self._cloud_lock:
            self._cloud_reachable = reachable
            self._cloud_error = error

    def check_cloud_health(self) -> tuple[bool, str | None]:
        """Exercise the same R2 upload and public download route guests use."""
        from engine.provisioning import _r2_probe

        with self._probe_lock:
            config = self.config_store.load()
            if not config or not config.r2:
                error = "Cloud photo delivery is not configured."
                self._set_cloud_health(False, error)
                return False, error
            try:
                _r2_probe(config.r2)
            except Exception as exc:  # noqa: BLE001 - surfaced as a readiness diagnostic
                error = str(exc) or type(exc).__name__
                self._set_cloud_health(False, error)
                return False, error
            self._set_cloud_health(True)
            return True, None

    def check_cloud_health_async(self) -> None:
        threading.Thread(target=self.check_cloud_health, daemon=True).start()

    def enqueue(self, job: UploadJob, block: bool = True, timeout: float = 30) -> None:
        with self._inflight_lock:
            if job.session_id in self._inflight:
                return  # already queued/processing; don't duplicate
            self._inflight.add(job.session_id)
            self._inflight_events[job.session_id] = job.event_id
        try:
            self._queue.put(job, block=block, timeout=timeout)
        except queue.Full as exc:
            with self._inflight_lock:
                self._inflight.discard(job.session_id)
                self._inflight_events.pop(job.session_id, None)
            raise RuntimeError("Upload queue is full; try again shortly") from exc

    def enqueue_best_effort(self, job: UploadJob) -> bool:
        """Non-blocking enqueue that never raises. Returns False if the queue is
        full — the periodic rescan will retry the session later, so finalize can
        still return the local strip to the guest instead of erroring."""
        try:
            self.enqueue(job, block=False)
            return True
        except RuntimeError:
            logger.warning("Upload queue full; session %s deferred to rescan", job.session_id)
            return False

    def retry_pending_deletions_async(self) -> None:
        """Delete R2 objects off the request thread — a slow/offline R2 must not
        freeze the admin UI on a delete."""
        threading.Thread(
            target=self.retry_pending_deletions, daemon=True
        ).start()

    def retry_pending_deletions(self) -> int:
        targets = self.storage.pending_r2_deletions()
        if not targets:
            return 0
        config = self.config_store.load()
        uploader = self.uploader(config)
        if uploader is None:
            logger.warning("R2 not configured; deferred deleting %s session(s)", len(targets))
            return 0
        deleted = 0
        for target in targets:
            if self._deletion_conflicts_with_upload(target):
                logger.info("Deferred R2 deletion while upload is active: %s", target)
                continue
            try:
                uploader.delete_target(target)
                self.storage.complete_r2_deletion(target)
                deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete R2 session %s: %s", target, exc)
        return deleted

    def _deletion_conflicts_with_upload(self, target: str) -> bool:
        with self._inflight_lock:
            inflight = dict(self._inflight_events)
        if target.startswith("event-session:"):
            return target.split(":", 2)[2] in inflight
        # Only a whole-event delete also removes strips; gallery pages and zips
        # never race a strip upload.
        if target.startswith("event:"):
            return target.split(":", 1)[1] in inflight.values()
        return False

    def resume_pending(self) -> int:
        sessions = self.storage.list_sessions_needing_upload()
        resumed = 0
        for session in sessions:
            try:
                self.enqueue(
                    UploadJob(
                        session_id=session.id,
                        event_id=session.event_id,
                        session_dir=Path(session.local_path),
                    ),
                    block=False,
                )
                resumed += 1
            except RuntimeError:
                logger.warning("Upload queue full; stopped resuming at %s", session.id)
                break
        if resumed:
            logger.info("Resumed %s upload job(s)", resumed)
        return resumed

    def _rescan_loop(self) -> None:
        """Re-enqueue pending/failed sessions periodically. Without this a WiFi
        outage during a party permanently strands every session it touched until
        a power cycle (the upload thread only ran resume_pending once at boot)."""
        while not self._stop_event.wait(RESCAN_INTERVAL_SECONDS):
            try:
                self.resume_pending()
                self.retry_pending_deletions()
                self.storage.prune_abandoned_sessions()
            except Exception as exc:  # noqa: BLE001 - a rescan error must not kill the loop
                logger.warning("Upload rescan failed: %s", exc)

    def uploader(self, config) -> R2Uploader | None:
        if not config or not config.r2:
            return None
        if self._uploader is None or self._uploader.config != config.r2:
            self._uploader = R2Uploader(config.r2)
        return self._uploader

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                self._process_with_retry(job)
            except Exception as exc:
                logger.exception("Upload failed for %s: %s", job.session_id, exc)
                self.storage.update_session_upload(
                    job.session_id,
                    "failed",
                    error=str(exc) or type(exc).__name__,
                )
                self._set_cloud_health(False, str(exc) or type(exc).__name__)
            finally:
                with self._inflight_lock:
                    self._inflight.discard(job.session_id)
                    self._inflight_events.pop(job.session_id, None)
                self._queue.task_done()

    def _process_with_retry(self, job: UploadJob) -> None:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                self._process(job)
                return
            except Exception as exc:
                last_exc = exc
                self.storage.update_session_upload(
                    job.session_id,
                    "failed",
                    error=str(exc) or type(exc).__name__,
                    increment_attempt=True,
                )
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_SECONDS * (2**attempt)
                    logger.warning(
                        "Upload attempt %s failed for %s, retry in %ss: %s",
                        attempt + 1,
                        job.session_id,
                        delay,
                        exc,
                    )
                    if getattr(self, "_stop_event", threading.Event()).wait(delay):
                        return
        if last_exc:
            raise last_exc

    def _process(self, job: UploadJob) -> None:
        config = self.config_store.load()
        uploader = self.uploader(config)
        if uploader is None:
            raise RuntimeError("Cloud photo delivery is not configured.")
        event = self.storage.get_event(job.event_id)
        if not event:
            raise RuntimeError("The event no longer exists.")
        target = r2_session_target(job.event_id, job.session_id)
        if self.storage.r2_deletion_pending(target):
            return
        # Never upload a strip truncated by a power yank — it would live on
        # R2 as a permanently-broken image behind the guest's QR code.
        strip = job.session_dir / "strip.jpg"
        if not jpeg_is_intact(strip):
            logger.error(
                "Session %s has a corrupt/missing strip.jpg; marking failed, not uploading",
                job.session_id,
            )
            self.storage.update_session_upload(
                job.session_id,
                "corrupt",
                error="Corrupt or missing upload file(s): strip.jpg",
            )
            return
        self.storage.update_session_upload(job.session_id, "uploading")
        download_url = uploader.upload_session(job.session_dir, event.id, job.session_id)
        # Deletion may have been requested while the network upload was active.
        # Delete again after upload so the final cloud state is always empty.
        if self.storage.r2_deletion_pending(target):
            uploader.delete_target(target)
            self.storage.complete_r2_deletion(target)
            return
        uploader.verify_guest_download(download_url, strip)
        # The guest-link verification itself can take several seconds. Repeat
        # the tombstone check so an admin deletion during that window still wins.
        if self.storage.r2_deletion_pending(target):
            uploader.delete_target(target)
            self.storage.complete_r2_deletion(target)
            return
        self.storage.update_session_upload(
            job.session_id,
            "complete",
            download_url,
            error=None,
        )
        self._set_cloud_health(True)
        logger.info("Upload complete for session %s", job.session_id)

    def close(self, timeout: float = 10) -> None:
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        self._rescan_thread.join(timeout=timeout)
