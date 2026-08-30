"""High-level batch create / start / cancel / retry operations."""
from __future__ import annotations

import os
import shutil
import time
from typing import Any, Dict, List, Optional

from . import batch_parser
from . import events
from . import job_store
from . import quota
from .audit import audit
from .paths import BATCHES_DIR, ensure_factory_dirs, resolve_under, safe_batch_id


def save_source_file(batch_id: str, filename: str, data: bytes) -> str:
    ensure_factory_dirs()
    bid = safe_batch_id(batch_id)
    dest_dir = resolve_under(BATCHES_DIR, bid)
    os.makedirs(dest_dir, exist_ok=True)
    # sanitize filename
    base = os.path.basename(filename or "batch.csv").replace("..", "_")
    path = resolve_under(dest_dir, base)
    with open(path, "wb") as f:
        f.write(data)
    return path


def create_batch_from_validation(
    *,
    filename: str,
    data: bytes,
    validation: Dict[str, Any],
    dry_run: bool = False,
    exclude_invalid: bool = False,
) -> Dict[str, Any]:
    if validation.get("blocking") and not exclude_invalid:
        raise ValueError("Batch has blocking validation errors")
    rows = list(validation.get("rows") or [])
    if not rows:
        raise ValueError("No valid rows to process")
    artwork_total = batch_parser.expand_artwork_units(rows)
    check = quota.can_accept(artwork_total)
    if not check["ok"]:
        raise ValueError(check["error"])

    batch_id = job_store.next_batch_id()
    source_path = save_source_file(batch_id, filename, data)
    listings = batch_parser.group_by_listing(rows)

    batch = job_store.create_batch(
        batch_id=batch_id,
        source_filename=os.path.basename(filename),
        source_path=source_path,
        artwork_total=artwork_total,
        listing_total=len(listings),
        dry_run=dry_run,
        meta={
            "dry_run": dry_run,
            "grouping": validation.get("grouping_preview") or [],
            "warnings": validation.get("warnings") or [],
        },
    )

    # Expand artwork_count into individual jobs
    for row in rows:
        count = int(row.get("artwork_count") or 1)
        base_id = row.get("artwork_id") or "art"
        for n in range(count):
            art_id = base_id if count == 1 else f"{base_id}_{n+1}"
            unit = dict(row)
            unit["artwork_id"] = art_id
            unit["artwork_count"] = 1
            # selection policy applies to candidate variations — for expanded units use first_success
            if count == 1 and int(row.get("artwork_count") or 1) > 1:
                unit["selection_policy"] = row.get("selection_policy") or "manual_review"
            from .batch_pipeline import PIPELINE_STAGES

            job_store.create_job(
                batch_id=batch_id,
                listing_id=row["listing_id"],
                artwork_id=art_id,
                row=unit,
                total_units=len(PIPELINE_STAGES),
            )

    audit(
        "batch.created",
        batch_id=batch_id,
        artworks=artwork_total,
        listings=len(listings),
        dry_run=dry_run,
        filename=filename,
    )
    events.publish("batch.created", {"batch_id": batch_id, "dry_run": dry_run})
    events.invalidate("batch.created", batch_id=batch_id)
    return job_store.recompute_batch_progress(batch_id)


def start_batch(batch_id: str) -> Dict[str, Any]:
    bid = safe_batch_id(batch_id)
    batch = job_store.get_batch(bid)
    if not batch:
        raise ValueError("Batch not found")
    if batch.get("status") in ("processing", "complete", "partial"):
        # allow restart of queued only
        pass

    jobs = job_store.list_jobs(batch_id=bid, limit=5000)
    artwork_total = len(jobs)
    # Live batches consume daily quota on start. Dry-run is practice only — no quota.
    meta = batch.get("meta") or {}
    dry_run = bool(batch.get("dry_run") or meta.get("dry_run"))
    if dry_run:
        meta["quota_consumed"] = False
        meta["quota_skipped_dry_run"] = True
        job_store.update_batch(bid, status="processing", meta=meta)
    elif not meta.get("quota_consumed"):
        listing_ids = sorted({j["listing_id"] for j in jobs})
        quota.accept(artwork_total, batch_id=bid, listing_ids=listing_ids)
        meta["quota_consumed"] = True
        job_store.update_batch(bid, status="processing", meta=meta)
    else:
        job_store.update_batch(bid, status="processing")

    audit("batch.started", batch_id=bid, artworks=artwork_total)
    events.publish("batch.progress", {"batch_id": bid, "event": "started"})
    events.invalidate("batch.started", batch_id=bid)
    return job_store.recompute_batch_progress(bid)


def cancel_batch(batch_id: str) -> Dict[str, Any]:
    bid = safe_batch_id(batch_id)
    n = job_store.cancel_queued_jobs(bid)
    if n:
        quota.restore_cancelled(n, batch_id=bid)
    progress = job_store.recompute_batch_progress(bid)
    audit("batch.cancelled", batch_id=bid, cancelled_jobs=n)
    events.publish("batch.progress", {"batch_id": bid, "event": "cancelled"})
    events.invalidate("batch.cancelled", batch_id=bid)
    return progress


def retry_failed(batch_id: str) -> Dict[str, Any]:
    bid = safe_batch_id(batch_id)
    jobs = job_store.list_jobs(batch_id=bid, limit=5000)
    n = 0
    for j in jobs:
        if j.get("status") == "failed":
            job_store.update_job(
                j["id"],
                status="retry",
                current_stage="queued",
                error=None,
                message="Queued for retry",
                completed_at=None,
            )
            n += 1
            quota.record_retry(batch_id=bid)
    if n:
        job_store.update_batch(bid, status="processing")
    audit("batch.retry", batch_id=bid, count=n)
    events.publish("job.retried", {"batch_id": bid, "count": n})
    events.invalidate("batch.retry", batch_id=bid)
    progress = job_store.recompute_batch_progress(bid)
    progress["retried_count"] = n
    return progress


def batches_by_date() -> Dict[str, List[Dict[str, Any]]]:
    batches = job_store.list_batches(limit=200)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for b in batches:
        day = time.strftime("%Y-%m-%d", time.localtime(b.get("created_at") or time.time()))
        detail = job_store.recompute_batch_progress(b["id"])
        grouped.setdefault(day, []).append(detail)
    return grouped
