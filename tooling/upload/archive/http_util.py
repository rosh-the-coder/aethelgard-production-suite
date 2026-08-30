"""Shared HTTP client with polite rate limits and retries."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from .schema import IMAGE_HOST_ALLOWLIST

UA = {
    "User-Agent": "AethelgardArchiveStudio/1.0 (local production tool; public-domain research)",
    "Accept": "application/json, text/plain, */*",
}

_LIMITERS: Dict[str, "RateLimiter"] = {}
_LIMITERS_LOCK = threading.Lock()


class RateLimiter:
    def __init__(self, min_interval: float = 0.25):
        self.min_interval = float(min_interval)
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.time()


def limiter_for(source: str, min_interval: float = 0.25) -> RateLimiter:
    with _LIMITERS_LOCK:
        existing = _LIMITERS.get(source)
        if existing:
            return existing
        limiter = RateLimiter(min_interval)
        _LIMITERS[source] = limiter
        return limiter


def host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in IMAGE_HOST_ALLOWLIST)


def get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 25,
    source: str = "default",
    min_interval: float = 0.25,
    retries: int = 3,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
    """Return (json, error, status_code)."""
    limiter_for(source, min_interval).wait()
    hdrs = {**UA, **(headers or {})}
    last_err = None
    status = 0
    for attempt in range(max(1, retries)):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            status = r.status_code
            if status == 429 or status >= 500:
                time.sleep(0.7 * (attempt + 1))
                last_err = f"HTTP {status}"
                continue
            if status >= 400:
                return None, f"HTTP {status}: {(r.text or '')[:240]}", status
            text = (r.text or "").lstrip()
            if not text.startswith("{") and not text.startswith("["):
                return None, "Non-JSON response", status
            data = r.json()
            if isinstance(data, list):
                return {"data": data}, None, status
            return data, None, status
        except Exception as e:
            last_err = str(e)
            time.sleep(0.4 * (attempt + 1))
    return None, last_err or "request failed", status


def get_bytes(
    url: str,
    *,
    timeout: float = 40,
    source: str = "default",
    min_interval: float = 0.2,
    accept: str = "image/jpeg,image/png,image/webp,image/*,*/*;q=0.8",
    max_bytes: int = 80 * 1024 * 1024,
) -> Tuple[bytes, str, Optional[str]]:
    """Return (data, mime, error)."""
    if not url:
        return b"", "", "missing url"
    if url.startswith("http://") or url.startswith("https://"):
        if not host_allowed(url):
            return b"", "", f"host not allowlisted: {urlparse(url).hostname}"
    limiter_for(source, min_interval).wait()
    try:
        r = requests.get(
            url,
            headers={**UA, "Accept": accept},
            timeout=timeout,
            stream=True,
        )
        if r.status_code != 200:
            return b"", "", f"HTTP {r.status_code}"
        mime = (r.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
        chunks = []
        total = 0
        for chunk in r.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return b"", "", "file exceeds size cap"
            chunks.append(chunk)
        data = b"".join(chunks)
        if "html" in mime.lower() or data.lstrip()[:15].lower().startswith(b"<!doctype"):
            return b"", "", "HTML instead of image"
        if len(data) < 64:
            return b"", "", "empty or tiny payload"
        return data, mime, None
    except Exception as e:
        return b"", "", str(e)
