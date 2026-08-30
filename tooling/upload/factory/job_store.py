"""SQLite-backed persistent job + batch store."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from .paths import JOBS_DB_PATH, ensure_factory_dirs

_LOCK = threading.RLock()
_INIT = False

STAGES = [
    "queued",
    "validating",
    "acquiring",
    "normalising",
    "awaiting_selection",
    "preparing_master",
    "creating_prints",
    "creating_mockups",
    "generating_seo",
    "packaging",
    "creating_etsy_draft",
    "awaiting_review",
    "complete",
    "failed",
    "cancelled",
]


def _connect() -> sqlite3.Connection:
    ensure_factory_dirs()
    conn = sqlite3.connect(JOBS_DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db():
    with _LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    global _INIT
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                status TEXT NOT NULL,
                source_filename TEXT,
                source_path TEXT,
                dry_run INTEGER NOT NULL DEFAULT 0,
                artwork_total INTEGER NOT NULL DEFAULT 0,
                listing_total INTEGER NOT NULL DEFAULT 0,
                completed_artworks INTEGER NOT NULL DEFAULT 0,
                failed_artworks INTEGER NOT NULL DEFAULT 0,
                etsy_drafts INTEGER NOT NULL DEFAULT 0,
                email_status TEXT,
                meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                artwork_id TEXT,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                completed_units INTEGER NOT NULL DEFAULT 0,
                total_units INTEGER NOT NULL DEFAULT 1,
                percentage REAL NOT NULL DEFAULT 0,
                message TEXT,
                error TEXT,
                started_at REAL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                piece_path TEXT,
                run_name TEXT,
                row_json TEXT,
                replaces_draft_id TEXT,
                draft_id TEXT,
                UNIQUE(batch_id, listing_id, artwork_id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_batches_created ON batches(created_at);
            """
        )
    _INIT = True


def ensure_init() -> None:
    if not _INIT:
        init_db()


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    for key in ("meta_json", "row_json"):
        if key in d and d[key]:
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except Exception:
                d[key.replace("_json", "")] = {}
        elif key in d:
            d[key.replace("_json", "")] = {}
    if "dry_run" in d:
        d["dry_run"] = bool(d["dry_run"])
    return d


def next_batch_id(date: Optional[str] = None) -> str:
    ensure_init()
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    prefix = date
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM batches WHERE id LIKE ? ORDER BY id",
            (prefix + "-%",),
        ).fetchall()
    n = 1
    existing = {r["id"] for r in rows}
    while True:
        bid = f"{prefix}-{n:02d}"
        if bid not in existing:
            return bid
        n += 1


def create_batch(
    *,
    batch_id: str,
    source_filename: str,
    source_path: str,
    artwork_total: int,
    listing_total: int,
    dry_run: bool = False,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_init()
    now = time.time()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO batches (
                id, created_at, updated_at, status, source_filename, source_path,
                dry_run, artwork_total, listing_total, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                now,
                now,
                "validated",
                source_filename,
                source_path,
                1 if dry_run else 0,
                artwork_total,
                listing_total,
                json.dumps(meta or {}),
            ),
        )
    return get_batch(batch_id)


def create_job(
    *,
    batch_id: str,
    listing_id: str,
    artwork_id: str,
    row: Dict[str, Any],
    total_units: int = 10,
) -> Dict[str, Any]:
    ensure_init()
    now = time.time()
    job_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, batch_id, listing_id, artwork_id, status, current_stage,
                completed_units, total_units, percentage, message, updated_at, row_json
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?)
            """,
            (
                job_id,
                batch_id,
                listing_id,
                artwork_id,
                "queued",
                "queued",
                total_units,
                "Queued",
                now,
                json.dumps(row),
            ),
        )
    return get_job(job_id)


def get_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    return _row_to_dict(row)


def list_batches(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def list_jobs(
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    ensure_init()
    q = "SELECT * FROM jobs WHERE 1=1"
    args: List[Any] = []
    if batch_id:
        q += " AND batch_id = ?"
        args.append(batch_id)
    if status:
        q += " AND status = ?"
        args.append(status)
    q += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    with db() as conn:
        rows = conn.execute(q, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def claim_next_job(allowed_statuses: Iterable[str] = ("queued", "retry")) -> Optional[Dict[str, Any]]:
    """Atomically claim one job for processing."""
    ensure_init()
    now = time.time()
    statuses = list(allowed_statuses)
    with db() as conn:
        placeholders = ",".join("?" * len(statuses))
        row = conn.execute(
            f"""
            SELECT * FROM jobs
            WHERE status IN ({placeholders})
            ORDER BY updated_at ASC
            LIMIT 1
            """,
            statuses,
        ).fetchone()
        if not row:
            return None
        job_id = row["id"]
        conn.execute(
            """
            UPDATE jobs SET status = ?, current_stage = ?, message = ?,
                started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE id = ? AND status IN ({})
            """.format(placeholders),
            ("running", "validating", "Starting", now, now, job_id, *statuses),
        )
        changed = conn.total_changes
        if changed == 0:
            return None
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def update_job(job_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    ensure_init()
    allowed = {
        "status",
        "current_stage",
        "completed_units",
        "total_units",
        "percentage",
        "message",
        "error",
        "started_at",
        "completed_at",
        "piece_path",
        "run_name",
        "draft_id",
        "replaces_draft_id",
        "row_json",
    }
    sets = []
    args: List[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "row" or k == "row_json":
            sets.append("row_json = ?")
            args.append(json.dumps(v if k == "row" else (v if isinstance(v, str) else v)))
            continue
        sets.append(f"{k} = ?")
        args.append(v)
    if not sets:
        return get_job(job_id)
    sets.append("updated_at = ?")
    args.append(time.time())
    args.append(job_id)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", args)
    return get_job(job_id)


def update_batch(batch_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    ensure_init()
    allowed = {
        "status",
        "completed_artworks",
        "failed_artworks",
        "etsy_drafts",
        "email_status",
        "meta_json",
        "artwork_total",
        "listing_total",
    }
    sets = []
    args: List[Any] = []
    for k, v in fields.items():
        if k == "meta":
            sets.append("meta_json = ?")
            args.append(json.dumps(v))
            continue
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        args.append(v)
    if not sets:
        return get_batch(batch_id)
    sets.append("updated_at = ?")
    args.append(time.time())
    args.append(batch_id)
    with db() as conn:
        conn.execute(f"UPDATE batches SET {', '.join(sets)} WHERE id = ?", args)
    return get_batch(batch_id)


def recompute_batch_progress(batch_id: str) -> Dict[str, Any]:
    ensure_init()
    jobs = list_jobs(batch_id=batch_id, limit=2000)
    total = len(jobs) or 1
    completed = sum(1 for j in jobs if j["status"] == "complete")
    failed = sum(1 for j in jobs if j["status"] == "failed")
    cancelled = sum(1 for j in jobs if j["status"] == "cancelled")
    running = sum(1 for j in jobs if j["status"] == "running")
    awaiting = sum(
        1
        for j in jobs
        if j["status"] in ("awaiting_selection", "awaiting_review")
        or j.get("current_stage") in ("awaiting_selection", "awaiting_review")
    )
    etsy = sum(1 for j in jobs if j.get("draft_id"))
    pct = round(100.0 * completed / total, 1) if jobs else 0.0
    units_done = sum(int(j.get("completed_units") or 0) for j in jobs)
    units_total = sum(int(j.get("total_units") or 1) for j in jobs) or 1
    unit_pct = round(100.0 * units_done / units_total, 1)

    # listing aggregation
    by_listing: Dict[str, List[Dict[str, Any]]] = {}
    for j in jobs:
        by_listing.setdefault(j["listing_id"], []).append(j)
    listings_ready = 0
    listings_processing = 0
    listings_attention = 0
    for lid, items in by_listing.items():
        if all(i["status"] == "complete" for i in items):
            listings_ready += 1
        elif any(i["status"] in ("failed", "awaiting_selection", "awaiting_review") for i in items):
            listings_attention += 1
            if any(i["status"] == "running" for i in items):
                listings_processing += 1
        elif any(i["status"] in ("running", "queued", "retry") for i in items):
            listings_processing += 1

    status = "complete"
    if running or any(j["status"] in ("queued", "retry") for j in jobs):
        status = "processing"
    elif failed and completed:
        status = "partial"
    elif failed and not completed:
        status = "failed"
    elif awaiting:
        status = "awaiting_attention"
    elif cancelled and not completed:
        status = "cancelled"

    update_batch(
        batch_id,
        status=status,
        completed_artworks=completed,
        failed_artworks=failed,
        etsy_drafts=etsy,
    )
    batch = get_batch(batch_id) or {}
    return {
        **batch,
        "jobs": jobs,
        "progress": {
            "status": status,
            "artworks_completed": completed,
            "artworks_total": len(jobs),
            "artworks_failed": failed,
            "artworks_cancelled": cancelled,
            "listings_ready": listings_ready,
            "listings_processing": listings_processing,
            "listings_attention": listings_attention,
            "listings_total": len(by_listing),
            "etsy_drafts": etsy,
            "percentage": unit_pct if jobs else pct,
            "completed_units": units_done,
            "total_units": units_total,
        },
        "listings": {
            lid: {
                "listing_id": lid,
                "jobs": items,
                "completed": sum(1 for i in items if i["status"] == "complete"),
                "total": len(items),
                "percentage": round(
                    100.0 * sum(int(i.get("completed_units") or 0) for i in items)
                    / max(1, sum(int(i.get("total_units") or 1) for i in items)),
                    1,
                ),
            }
            for lid, items in by_listing.items()
        },
    }


def cancel_queued_jobs(batch_id: str) -> int:
    """Cancel jobs that have not started provider work."""
    ensure_init()
    now = time.time()
    with db() as conn:
        cur = conn.execute(
            """
            UPDATE jobs SET status = 'cancelled', current_stage = 'cancelled',
                message = 'Cancelled before start', completed_at = ?, updated_at = ?
            WHERE batch_id = ? AND status IN ('queued', 'retry') AND started_at IS NULL
            """,
            (now, now, batch_id),
        )
        return cur.rowcount
