"""Append-only local audit log (no secrets)."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .paths import AUDIT_PATH, ensure_factory_dirs

_LOCK = threading.Lock()


def audit(action: str, **fields: Any) -> None:
    if not ensure_factory_dirs():
        print(f"audit skipped ({action}): factory dirs unavailable", flush=True)
        return
    row = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "action": action,
        **{k: v for k, v in fields.items() if v is not None},
    }
    # strip likely secrets
    for key in list(row.keys()):
        lk = key.lower()
        if any(s in lk for s in ("password", "token", "secret", "api_key", "authorization")):
            row[key] = "[redacted]"
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        with _LOCK:
            with open(AUDIT_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError as e:
        print(f"audit write failed ({action}): {e}", flush=True)


def read_audit(limit: int = 100) -> List[Dict[str, Any]]:
    if not os.path.isfile(AUDIT_PATH):
        return []
    rows: List[Dict[str, Any]] = []
    with _LOCK:
        with open(AUDIT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows))
