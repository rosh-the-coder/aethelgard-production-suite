"""JSONL + SQLite logging for Archive Studio jobs."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from .paths import LOG_PATH, ensure_archive_dirs


def log_event(
    event: str,
    *,
    level: str = "info",
    message: str = "",
    job_id: Optional[str] = None,
    asset_id: Optional[str] = None,
    source: Optional[str] = None,
    **detail: Any,
) -> None:
    try:
        ensure_archive_dirs()
    except Exception:
        pass
    payload: Dict[str, Any] = {
        "ts": time.time(),
        "level": level,
        "event": event,
        "message": message,
        "job_id": job_id,
        "asset_id": asset_id,
        "source": source,
        "detail": detail or {},
    }
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    try:
        from . import store

        store.insert_log(payload)
    except Exception:
        pass
    prefix = f"[archive:{level}] {event}"
    if message:
        prefix += f" — {message}"
    print(prefix, flush=True)
