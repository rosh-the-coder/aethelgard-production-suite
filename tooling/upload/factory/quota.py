"""Persistent daily artwork generation quota ledger (local calendar day)."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .paths import DAILY_ARTWORK_LIMIT, QUOTA_PATH, ensure_factory_dirs
from . import events
from .audit import audit

_LOCK = threading.Lock()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _empty_day(date: str) -> Dict[str, Any]:
    return {
        "date": date,
        "limit": DAILY_ARTWORK_LIMIT,
        "accepted": 0,
        "cancelled_before_start": 0,
        "failed_attempts": 0,
        "retries": 0,
        "entries": [],
    }


def _load() -> Dict[str, Any]:
    ensure_factory_dirs()
    if not os.path.isfile(QUOTA_PATH):
        return {"days": {}, "limit": DAILY_ARTWORK_LIMIT}
    try:
        with open(QUOTA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"days": {}, "limit": DAILY_ARTWORK_LIMIT}
        data.setdefault("days", {})
        data.setdefault("limit", DAILY_ARTWORK_LIMIT)
        return data
    except Exception:
        return {"days": {}, "limit": DAILY_ARTWORK_LIMIT}


def _save(data: Dict[str, Any]) -> None:
    ensure_factory_dirs()
    tmp = QUOTA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, QUOTA_PATH)


def snapshot(date: Optional[str] = None) -> Dict[str, Any]:
    date = date or _today()
    with _LOCK:
        data = _load()
        day = data["days"].get(date) or _empty_day(date)
        accepted = int(day.get("accepted") or 0)
        cancelled = int(day.get("cancelled_before_start") or 0)
        consumed = max(0, accepted - cancelled)
        limit = int(data.get("limit") or DAILY_ARTWORK_LIMIT)
        remaining = max(0, limit - consumed)
        return {
            "date": date,
            "limit": limit,
            "accepted": accepted,
            "cancelled_before_start": cancelled,
            "consumed": consumed,
            "remaining": remaining,
            "failed_attempts": int(day.get("failed_attempts") or 0),
            "retries": int(day.get("retries") or 0),
            "entries": list(day.get("entries") or []),
            "resets_at": "00:00 local time",
            "label": f"{consumed} / {limit} artworks scheduled today",
            "remaining_label": f"{remaining} remaining",
        }


def can_accept(artwork_count: int, date: Optional[str] = None) -> Dict[str, Any]:
    snap = snapshot(date)
    count = max(0, int(artwork_count or 0))
    ok = count <= snap["remaining"]
    return {
        **snap,
        "requested": count,
        "ok": ok,
        "error": None if ok else (
            f"Artwork total {count} exceeds remaining daily quota ({snap['remaining']} of {snap['limit']})."
        ),
    }


def accept(
    artwork_count: int,
    *,
    batch_id: str,
    listing_ids: Optional[List[str]] = None,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Consume quota when a batch is accepted for processing."""
    date = date or _today()
    count = max(0, int(artwork_count or 0))
    with _LOCK:
        data = _load()
        day = data["days"].get(date) or _empty_day(date)
        accepted = int(day.get("accepted") or 0)
        cancelled = int(day.get("cancelled_before_start") or 0)
        consumed = max(0, accepted - cancelled)
        limit = int(data.get("limit") or DAILY_ARTWORK_LIMIT)
        remaining = max(0, limit - consumed)
        if count > remaining:
            raise ValueError(
                f"Artwork total {count} exceeds remaining daily quota ({remaining} of {limit})."
            )
        day["accepted"] = accepted + count
        day["entries"].append(
            {
                "ts": time.time(),
                "batch_id": batch_id,
                "listing_ids": list(listing_ids or []),
                "count": count,
                "kind": "accept",
            }
        )
        data["days"][date] = day
        _save(data)
    snap = snapshot(date)
    audit("quota.consumed", batch_id=batch_id, count=count, date=date, consumed=snap["consumed"])
    events.publish("quota.changed", snap)
    events.invalidate("quota.changed")
    return snap


def restore_cancelled(
    artwork_count: int,
    *,
    batch_id: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore quota for items cancelled before provider work started."""
    date = date or _today()
    count = max(0, int(artwork_count or 0))
    with _LOCK:
        data = _load()
        day = data["days"].get(date) or _empty_day(date)
        day["cancelled_before_start"] = int(day.get("cancelled_before_start") or 0) + count
        day["entries"].append(
            {
                "ts": time.time(),
                "batch_id": batch_id,
                "count": count,
                "kind": "cancel_restore",
            }
        )
        data["days"][date] = day
        _save(data)
    snap = snapshot(date)
    audit("quota.restored", batch_id=batch_id, count=count, date=date)
    events.publish("quota.changed", snap)
    events.invalidate("quota.changed")
    return snap


def record_failure(batch_id: str = "", date: Optional[str] = None) -> None:
    date = date or _today()
    with _LOCK:
        data = _load()
        day = data["days"].get(date) or _empty_day(date)
        day["failed_attempts"] = int(day.get("failed_attempts") or 0) + 1
        day["entries"].append({"ts": time.time(), "batch_id": batch_id, "kind": "failure"})
        data["days"][date] = day
        _save(data)
    # failure does not restore quota


def record_retry(batch_id: str = "", date: Optional[str] = None) -> None:
    date = date or _today()
    with _LOCK:
        data = _load()
        day = data["days"].get(date) or _empty_day(date)
        day["retries"] = int(day.get("retries") or 0) + 1
        day["entries"].append({"ts": time.time(), "batch_id": batch_id, "kind": "retry"})
        data["days"][date] = day
        _save(data)
    # retries do not consume extra quota


def reset_day(
    *,
    consumed: int,
    date: Optional[str] = None,
    note: str = "",
    entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Replace today's ledger with an explicit live-artwork consumed count."""
    date = date or _today()
    consumed = max(0, int(consumed or 0))
    with _LOCK:
        data = _load()
        limit = int(data.get("limit") or DAILY_ARTWORK_LIMIT)
        day = _empty_day(date)
        day["limit"] = limit
        day["accepted"] = consumed
        day["cancelled_before_start"] = 0
        day["entries"] = list(entries or [])
        if not day["entries"]:
            day["entries"].append(
                {
                    "ts": time.time(),
                    "batch_id": "manual-reset",
                    "count": consumed,
                    "kind": "reset",
                    "note": note or "Reset to live completed artworks only",
                }
            )
        data["days"][date] = day
        _save(data)
    snap = snapshot(date)
    audit("quota.reset", date=date, consumed=consumed, note=note)
    events.publish("quota.changed", snap)
    events.invalidate("quota.changed")
    return snap
