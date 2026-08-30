"""Filesystem paths for factory OS persistence."""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.dirname(HERE)
ROOT_DIR = os.path.abspath(os.path.join(UPLOAD_DIR, "..", ".."))
RUNS_DIR = os.path.join(ROOT_DIR, "tooling", "digital-product-research", "artwork-runs")

FACTORY_DATA_DIR = os.path.join(UPLOAD_DIR, ".factory")
BATCHES_DIR = os.path.join(FACTORY_DATA_DIR, "batches")
QUOTA_PATH = os.path.join(FACTORY_DATA_DIR, "quota_ledger.json")
AUDIT_PATH = os.path.join(FACTORY_DATA_DIR, "audit.jsonl")
JOBS_DB_PATH = os.path.join(FACTORY_DATA_DIR, "jobs.sqlite3")
EVENTS_STATE_PATH = os.path.join(FACTORY_DATA_DIR, "last_event_seq.txt")

DAILY_ARTWORK_LIMIT = 20


def ensure_factory_dirs() -> bool:
    """Create factory data dirs. Returns False if the drive is briefly unavailable."""
    try:
        os.makedirs(FACTORY_DATA_DIR, exist_ok=True)
        os.makedirs(BATCHES_DIR, exist_ok=True)
        return True
    except OSError as e:
        print(f"factory: could not ensure dirs ({e})", flush=True)
        return False


def safe_batch_id(batch_id: str) -> str:
    """Reject path traversal; allow only date-serial style ids."""
    bid = str(batch_id or "").strip()
    if not bid or ".." in bid or "/" in bid or "\\" in bid:
        raise ValueError("Invalid batch id")
    # allow alnum, dash, underscore
    for ch in bid:
        if not (ch.isalnum() or ch in "-_"):
            raise ValueError("Invalid batch id")
    return bid


def resolve_under(base: str, *parts: str) -> str:
    """Join and ensure result stays under base."""
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if not target.startswith(base_abs + os.sep) and target != base_abs:
        raise ValueError("Path escapes base directory")
    return target
