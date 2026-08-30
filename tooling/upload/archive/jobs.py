"""Enqueue helpers for Archive Studio background jobs."""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import store


def enqueue(kind: str, payload: Optional[Dict[str, Any]] = None, *, total: int = 0) -> Dict[str, Any]:
    payload = dict(payload or {})
    if not total:
        ids = payload.get("asset_ids") or payload.get("records") or []
        total = len(ids) if isinstance(ids, list) else 0
        if kind == "search_ingest":
            total = int(payload.get("max_records") or payload.get("limit") or 100)
    return store.create_job(kind, payload, total=total)
