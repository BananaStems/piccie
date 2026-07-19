from __future__ import annotations

import logging
import queue
import threading
import time
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
    cloud_target: str | None = None


class UploadQueue:
    def __init__(self, storage: Storage, config_store: ConfigStore) -> None:
        self.storage = storage
        self.config_store = config_store
        self._queue: queue.Queue[UploadJob | None] = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._uploader: R2Uploader | None = None
        self._uploader_key: tuple[str, str] | None = None
        # Session ids currently queued or being processed — so the periodic
        # rescan never double-enqueues a job that is already in flight.
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._rescan_thread = threading.Thread(target=self._rescan_loop, daemon=True)
        self._rescan_thread.start()

    @property
    def backlog(self) -> int:
        return self._queue.qsize()

    def enqueue(self, job: UploadJob, block: bool = True, timeout: float = 30) -> None:
        with self._inflight_lock:
            if job.session_id in self._inflight:
                return  # already queued/processing; don't duplicate
            self._inflight.add(job.session_id)
        try:
            self._queue.put(job, block=block, timeout=timeout)
        except queue.Full as exc:
            with self._inflight_lock:
                self._inflight.discard(job.session_id)
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
            try:
                uploader.delete_target(target)
                self.storage.complete_r2_deletion(target)
                deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete R2 session %s: %s", target, exc)
        return deleted

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
        a power cycle (the worker only ran resume_pending once at boot)."""
        while True:
            time.sleep(RESCAN_INTERVAL_SECONDS)
            try:
                self.resume_pending()
                self.retry_pending_deletions()
                self.storage.prune_abandoned_sessions()
            except Exception as exc:  # noqa: BLE001 - a rescan error must not kill the loop
                logger.warning("Upload rescan failed: %s", exc)

    def _get_uploader(self, config) -> R2Uploader | None:
        if not config or not config.r2:
            return None
        key = (config.r2.account_id, config.r2.bucket)
        if self._uploader is None or self._uploader_key != key:
            self._uploader = R2Uploader(config.r2)
            self._uploader_key = key
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
                self.storage.update_session_upload(job.session_id, "failed")
            finally:
                with self._inflight_lock:
                    self._inflight.discard(job.session_id)
                self._queue.task_done()

    def _process_with_retry(self, job: UploadJob) -> None:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                self._process(job)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_SECONDS * (2**attempt)
                    logger.warning(
                        "Upload attempt %s failed for %s, retry in %ss: %s",
                        attempt + 1,
                        job.session_id,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
        if last_exc:
            raise last_exc

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
            self.storage.update_session_upload(job.session_id, "skipped")
            return
        event = self.storage.get_event(job.event_id)
        if not event:
            self.storage.update_session_upload(job.session_id, "failed")
            return
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
            self.storage.update_session_upload(job.session_id, "failed")
            return
        self.storage.update_session_upload(job.session_id, "uploading")
        session = self.storage.get_session(job.session_id)
        meta = self.storage.get_session_meta(session) if session else {}
        download_url, strip_image_url, share_token = uploader.upload_session(
            job.session_dir,
            event.id,
            job.session_id,
            event.strip_line1(),
            event.date,
            share_token=meta.get("share_token"),
        )
        # Deletion may have been requested while the network upload was active.
        # Delete again after upload so the final cloud state is always empty.
        if self.storage.r2_deletion_pending(target):
            uploader.delete_target(target)
            self.storage.complete_r2_deletion(target)
            return
        self.storage.update_session_upload(job.session_id, "complete", download_url)
        session = self.storage.get_session(job.session_id)
        if session:
            self.storage.write_session_meta(
                session,
                {
                    "session_id": job.session_id,
                    "event_id": job.event_id,
                    "r2_target": target,
                    "download_url": download_url,
                    "strip_image_url": strip_image_url,
                    "share_token": share_token,
                    "upload_status": "complete",
                },
            )
        logger.info("Upload complete for session %s", job.session_id)
