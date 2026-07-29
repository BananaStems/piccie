from __future__ import annotations

import itertools
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
HISTORICAL_QUEUE_LIMIT = 40
RESCAN_INTERVAL_SECONDS = 30


@dataclass
class UploadJob:
    session_id: str
    event_id: str
    session_dir: Path
    cloud_target: str | None = None


class UploadQueue:
    def __init__(self, storage: Storage, config_store: ConfigStore) -> None:
        self.storage = storage
        self.config_store = config_store
        self._queue: queue.PriorityQueue[
            tuple[int, int, UploadJob]
        ] = queue.PriorityQueue(maxsize=MAX_QUEUE_SIZE)
        self._sequence = itertools.count()
        self._uploader: R2Uploader | None = None
        self._uploader_key: tuple[str, ...] | None = None
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
    def backlog(self) -> int:
        summary = self.storage.upload_summary()
        return summary["pending"] + summary["failed"]

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

    def enqueue(
        self,
        job: UploadJob,
        block: bool = True,
        timeout: float = 30,
        *,
        historical: bool = False,
    ) -> None:
        with self._inflight_lock:
            if job.session_id in self._inflight:
                return  # already queued/processing; don't duplicate
            self._inflight.add(job.session_id)
            self._inflight_events[job.session_id] = job.event_id
        try:
            self._queue.put(
                (1 if historical else 0, next(self._sequence), job),
                block=block,
                timeout=timeout,
            )
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
        uploader = self._get_uploader(config)
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
            _, _event_id, session_id = target.split(":", 2)
            return session_id in inflight
        if target.startswith(("event:", "event-content:", "event-share:")):
            event_id = target.split(":", 2)[1]
            return event_id in inflight.values()
        return False

    def resume_pending(self) -> int:
        sessions = self.storage.list_sessions_needing_upload()
        resumed = 0
        for session in sessions:
            # Leave ten slots for strips being made now. Historical recovery
            # must never make a current guest wait behind an old outage.
            if self._queue.qsize() >= HISTORICAL_QUEUE_LIMIT:
                break
            try:
                self.enqueue(
                    UploadJob(
                        session_id=session.id,
                        event_id=session.event_id,
                        session_dir=Path(session.local_path),
                    ),
                    block=False,
                    historical=True,
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

    def _get_uploader(self, config) -> R2Uploader | None:
        if not config or not config.r2:
            return None
        key = (
            config.r2.account_id,
            config.r2.access_key,
            config.r2.secret_key,
            config.r2.bucket,
            config.r2.jurisdiction,
        )
        if self._uploader is None or self._uploader_key != key:
            self._uploader = R2Uploader(config.r2)
            self._uploader_key = key
        return self._uploader

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                _priority, _sequence, job = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._process(job)
            except Exception as exc:
                logger.exception("Upload failed for %s: %s", job.session_id, exc)
                self.storage.update_session_upload(
                    job.session_id,
                    "failed",
                    error=str(exc) or type(exc).__name__,
                    increment_attempt=True,
                )
                self._set_cloud_health(False, str(exc) or type(exc).__name__)
            finally:
                with self._inflight_lock:
                    self._inflight.discard(job.session_id)
                    self._inflight_events.pop(job.session_id, None)
                self._queue.task_done()

    def _resolve_target(self, job: UploadJob) -> str:
        if job.cloud_target:
            return job.cloud_target
        stored = self.storage.get_session_target(job.session_id)
        if stored:
            return stored
        return r2_session_target(job.event_id, job.session_id)

    def _process(self, job: UploadJob) -> None:
        config = self.config_store.load()
        uploader = self._get_uploader(config)
        if uploader is None:
            raise RuntimeError("Cloud photo delivery is not configured.")
        event = self.storage.get_event(job.event_id)
        if not event:
            raise RuntimeError("The event no longer exists.")
        target = self._resolve_target(job)
        if self.storage.r2_deletion_pending(target):
            return
        # Never upload a strip truncated by a power yank — it would live on
        # R2 as a permanently-broken image behind the guest's QR code.
        files = [job.session_dir / "strip.jpg"]
        broken = [f.name for f in files if not jpeg_is_intact(f)]
        if broken:
            logger.error(
                "Session %s has corrupt/missing file(s) %s; marking failed, not uploading",
                job.session_id,
                ", ".join(broken),
            )
            self.storage.update_session_upload(
                job.session_id,
                "corrupt",
                error=f"Corrupt or missing upload file(s): {', '.join(broken)}",
            )
            return
        self.storage.update_session_upload(job.session_id, "uploading")
        download_url = uploader.upload_session(
            job.session_dir,
            event.id,
            job.session_id,
        )
        # Deletion may have been requested while the network upload was active.
        # Delete again after upload so the final cloud state is always empty.
        if self.storage.r2_deletion_pending(target):
            uploader.delete_target(target)
            self.storage.complete_r2_deletion(target)
            return
        uploader.verify_guest_download(
            download_url,
            job.session_dir / "strip.jpg",
        )
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
        session = self.storage.get_session(job.session_id)
        if session:
            self.storage.merge_session_meta(
                session,
                {
                    "r2_target": target,
                    "download_url": download_url,
                    "upload_status": "complete",
                },
            )
        logger.info("Upload complete for session %s", job.session_id)

    def close(self, timeout: float = 10) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._rescan_thread.join(timeout=timeout)
