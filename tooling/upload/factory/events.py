"""In-process event bus for Factory Dashboard SSE / invalidation."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

_LOCK = threading.Lock()
_SEQ = 0
_HISTORY: Deque[Dict[str, Any]] = deque(maxlen=500)
_SUBSCRIBERS: List["queue.Queue"] = []

# late import for typing
import queue  # noqa: E402


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def publish(event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Publish a factory event. Returns the event dict."""
    event = {
        "id": _next_seq(),
        "type": event_type,
        "ts": time.time(),
        "payload": payload or {},
    }
    with _LOCK:
        _HISTORY.append(event)
        dead = []
        for q in _SUBSCRIBERS:
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in _SUBSCRIBERS:
                _SUBSCRIBERS.remove(q)
    return event


def subscribe(maxsize: int = 64) -> "queue.Queue":
    q: queue.Queue = queue.Queue(maxsize=maxsize)
    with _LOCK:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q: "queue.Queue") -> None:
    with _LOCK:
        if q in _SUBSCRIBERS:
            _SUBSCRIBERS.remove(q)


def recent(since_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    with _LOCK:
        items = [e for e in _HISTORY if e["id"] > since_id]
    return items[-limit:]


def invalidate(reason: str = "state_changed", **extra: Any) -> Dict[str, Any]:
    """Generic dashboard invalidation signal."""
    payload = {"reason": reason, **extra}
    return publish("dashboard.invalidate", payload)
