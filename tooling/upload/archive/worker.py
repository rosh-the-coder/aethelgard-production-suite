"""Background worker for Archive Studio jobs. Separate from factory batch_worker."""
from __future__ import annotations

import threading
import time
from typing import Optional

from . import download, drive_sync, ingest, pipeline, rules, store
from .log import log_event

_WORKER: Optional["ArchiveWorker"] = None
_LOCK = threading.Lock()


def _process(job: dict) -> None:
    kind = job.get("kind")
    jid = job["id"]
    payload = job.get("payload") or {}
    if job.get("status") == "cancelled":
        return
    try:
        if kind == "search_ingest":
            _search_ingest(jid, payload)
        elif kind == "thumbnail_sync":
            _each_asset(jid, payload, download.download_thumbnail)
        elif kind == "fullres_download":
            _each_asset(jid, payload, download.download_fullres)
        elif kind == "image_prep":
            _each_asset(jid, payload, download.download_fullres)
        elif kind == "drive_sync":
            kind_folder = payload.get("folder_kind") or "source_archive"
            collection_name = payload.get("collection_name") or ""
            _each_asset(
                jid,
                payload,
                lambda aid: drive_sync.sync_asset(
                    aid, kind=kind_folder, collection_name=collection_name
                ),
            )
        elif kind == "pipeline_handoff":
            result = pipeline.handoff(
                payload.get("asset_ids") or [],
                concept=payload.get("concept") or "",
                collection_id=payload.get("collection_id"),
                download_missing=bool(payload.get("download_missing", True)),
            )
            store.update_job(
                jid,
                status="done" if result.get("ok") else "failed",
                done=len(result.get("candidates") or []),
                failed=len(result.get("errors") or []),
                completed_at=time.time(),
                result=result,
                message=result.get("pack_title") or result.get("error") or "",
                error=None if result.get("ok") else (result.get("error") or "handoff failed"),
            )
            return
        elif kind == "dedupe_scan":
            _dedupe_scan(jid, payload)
        elif kind == "rule_run":
            result = rules.run_rule(payload.get("rule_id") or "")
            store.update_job(
                jid,
                status="done" if result.get("ok") else "failed",
                completed_at=time.time(),
                result=result,
                error=None if result.get("ok") else result.get("error"),
                message="rule complete",
            )
            return
        else:
            store.update_job(jid, status="failed", error=f"unknown job kind: {kind}", completed_at=time.time())
            return
        latest = store.get_job(jid)
        if latest and latest.get("status") == "cancelled":
            return
        failed = int((latest or {}).get("failed") or 0)
        store.update_job(
            jid,
            status="done" if failed == 0 else "done",
            completed_at=time.time(),
            message="complete",
        )
    except Exception as e:
        log_event("job.failed", level="error", job_id=jid, message=str(e), kind=kind)
        store.update_job(jid, status="failed", error=str(e), completed_at=time.time())


def _search_ingest(job_id: str, payload: dict) -> None:
    q = payload.get("query") or payload.get("q") or ""
    sources = payload.get("sources") or []
    filters = payload.get("filters") or {}
    max_records = int(payload.get("max_records") or payload.get("limit") or 100)
    page_size = min(48, max_records)
    offset = int((store.get_job(job_id) or {}).get("cursor", {}).get("offset") or 0)
    imported_total = 0
    store.update_job(job_id, total=max_records)
    while imported_total < max_records:
        job = store.get_job(job_id)
        if job and job.get("status") == "cancelled":
            return
        remaining = max_records - imported_total
        page = ingest.search_sources(
            q, sources=sources, limit=min(page_size, remaining), offset=offset, filters=filters
        )
        records = page.get("results") or []
        if not records:
            break
        result = ingest.import_records(
            records,
            import_batch_id=job_id,
            collection_id=payload.get("collection_id"),
            skip_duplicates=bool(payload.get("skip_duplicates", True)),
            require_clear_rights=bool(filters.get("require_clear_rights")),
        )
        n = len(result.get("imported_ids") or [])
        imported_total += n
        store.bump_job(job_id, ok=True, message=f"imported {imported_total}", total=max_records)
        store.update_job(job_id, cursor={"offset": offset + len(records)}, done=imported_total)
        if payload.get("sync_thumbs"):
            for aid in result.get("imported_ids") or []:
                download.download_thumbnail(aid)
        offset += len(records)
        if not page.get("has_more"):
            break
    store.update_job(job_id, result={"imported": imported_total})


def _each_asset(job_id: str, payload: dict, fn) -> None:
    ids = list(payload.get("asset_ids") or [])
    store.update_job(job_id, total=len(ids))
    for aid in ids:
        job = store.get_job(job_id)
        if job and job.get("status") == "cancelled":
            return
        try:
            result = fn(aid)
            ok = bool(result.get("ok")) if isinstance(result, dict) else True
            store.add_job_item(
                job_id,
                asset_id=aid,
                status="ok" if ok else "error",
                message=(result or {}).get("path") or "",
                error=(result or {}).get("error") or "",
            )
            store.bump_job(job_id, ok=ok, message=aid)
        except Exception as e:
            store.add_job_item(job_id, asset_id=aid, status="error", error=str(e))
            store.bump_job(job_id, ok=False, message=str(e))
            log_event("job.item_failed", level="error", job_id=job_id, asset_id=aid, message=str(e))


def _dedupe_scan(job_id: str, payload: dict) -> None:
    from . import dedupe

    ids = payload.get("asset_ids") or []
    if not ids:
        page = store.list_assets(limit=200, offset=0)
        ids = [a["id"] for a in page.get("items") or []]
    store.update_job(job_id, total=len(ids))
    marked = 0
    for aid in ids:
        asset = store.get_asset(aid)
        if not asset:
            store.bump_job(job_id, ok=False)
            continue
        hits = dedupe.find_duplicates(asset)
        if hits:
            dedupe.mark_duplicate(aid, hits[0]["id"])
            marked += 1
        store.bump_job(job_id, ok=True)
    store.update_job(job_id, result={"marked": marked})


class ArchiveWorker:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="aethelgard-archive-worker", daemon=True)
        self._thread.start()
        log_event("worker.started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = store.claim_next_job()
                if not job:
                    time.sleep(0.6)
                    continue
                log_event("job.started", job_id=job["id"], kind=job.get("kind"))
                _process(job)
            except Exception as e:
                try:
                    log_event("worker.loop_error", level="error", message=str(e))
                except Exception:
                    print(f"archive worker loop error: {e}", flush=True)
                time.sleep(2.0)


def start_worker() -> ArchiveWorker:
    global _WORKER
    with _LOCK:
        if _WORKER is None:
            _WORKER = ArchiveWorker()
        _WORKER.start()
        return _WORKER
