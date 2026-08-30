"""Background worker thread for batch jobs."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from . import batch_pipeline
from . import email_notify
from . import events
from . import job_store
from .audit import audit

_WORKER: Optional["BatchWorker"] = None
_LOCK = threading.Lock()


class BatchWorker:
    def __init__(
        self,
        *,
        get_settings: Callable[[], Dict[str, Any]],
        concurrency: int = 1,
    ):
        self.get_settings = get_settings
        self._concurrency = max(1, int(concurrency or 1))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active = 0
        self._active_lock = threading.Lock()

    @property
    def concurrency(self) -> int:
        try:
            settings = self.get_settings() or {}
            return max(1, int((settings.get("batch") or {}).get("concurrency") or self._concurrency))
        except Exception:
            return self._concurrency

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="aethelgard-batch-worker", daemon=True)
        self._thread.start()
        audit("worker.started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._active_lock:
                    if self._active >= self.concurrency:
                        time.sleep(0.4)
                        continue
                job = job_store.claim_next_job()
                if not job:
                    time.sleep(0.5)
                    continue
                with self._active_lock:
                    self._active += 1
                try:
                    events.publish("job.started", {"job_id": job["id"], "batch_id": job["batch_id"]})
                    suite = self.get_settings()
                    finished = batch_pipeline.process_job(job, suite_settings=suite)
                    try:
                        batch_pipeline.maybe_assemble_listing_bundle(finished or job)
                    except Exception as assemble_err:
                        audit(
                            "listing.assemble_failed",
                            batch_id=job.get("batch_id"),
                            job_id=job.get("id"),
                            error=str(assemble_err),
                        )
                    progress = job_store.recompute_batch_progress(job["batch_id"])
                    self._maybe_email(progress, suite)
                    events.invalidate("job.finished", batch_id=job["batch_id"])
                finally:
                    with self._active_lock:
                        self._active = max(0, self._active - 1)
            except Exception as e:
                try:
                    audit("worker.error", error=str(e))
                except Exception:
                    print(f"factory worker loop error: {e}", flush=True)
                time.sleep(2.0)

    def _maybe_email(self, progress: Dict[str, Any], suite: Dict[str, Any]) -> None:
        status = (progress.get("progress") or {}).get("status") or progress.get("status")
        if status not in ("complete", "partial", "failed"):
            return
        batch_id = progress.get("id")
        if not batch_id:
            return
        batch = job_store.get_batch(batch_id) or progress
        if batch.get("email_status") in ("sent", "skipped", "failed"):
            return
        jobs = job_store.list_jobs(batch_id=batch_id, limit=2000)
        if any(j["status"] in ("queued", "running", "retry", "awaiting_selection") for j in jobs):
            return
        result = email_notify.batch_completion_email(
            suite=suite,
            batch=batch,
            progress=progress.get("progress") or {},
        )
        if result.get("skipped"):
            job_store.update_batch(batch_id, email_status="skipped")
        elif result.get("ok"):
            job_store.update_batch(batch_id, email_status="sent")
            events.publish("email.sent", {"batch_id": batch_id})
        else:
            job_store.update_batch(batch_id, email_status="failed")
            events.publish("email.failed", {"batch_id": batch_id, "error": result.get("error")})


def get_worker() -> Optional[BatchWorker]:
    return _WORKER


def start_worker(get_settings: Callable[[], Dict[str, Any]], concurrency: int = 1) -> BatchWorker:
    global _WORKER
    with _LOCK:
        if _WORKER is None:
            job_store.init_db()
            _WORKER = BatchWorker(get_settings=get_settings, concurrency=concurrency)
            _WORKER.start()
        return _WORKER
