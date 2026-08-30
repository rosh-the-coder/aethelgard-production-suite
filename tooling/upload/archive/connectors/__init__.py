"""Extensible source-connector registry."""
from __future__ import annotations

from typing import Dict, List, Optional
import time

from ..schema import SOURCE_ORDER, SOURCES
from .artic import ArticConnector
from .base import Connector, ConnectorHealth, SearchPage, SearchQuery
from .cleveland import ClevelandConnector
from .europeana import EuropeanaConnector
from .loc import LocConnector
from .met import MetConnector
from .rijksmuseum import RijksmuseumConnector
from .smithsonian import SmithsonianConnector

_CONNECTORS: Dict[str, Connector] = {}
_HEALTH_CACHE: Dict[str, tuple] = {}
_HEALTH_TTL = 90.0


def _build() -> Dict[str, Connector]:
    instances: List[Connector] = [
        ClevelandConnector(),
        RijksmuseumConnector(),
        SmithsonianConnector(),
        LocConnector(),
        ArticConnector(),
        MetConnector(),
        EuropeanaConnector(),
    ]
    return {c.id: c for c in instances}


def all_connectors() -> Dict[str, Connector]:
    global _CONNECTORS
    if not _CONNECTORS:
        _CONNECTORS = _build()
    return _CONNECTORS


def get_connector(source_id: str) -> Optional[Connector]:
    return all_connectors().get(source_id)


def probe_health(source_id: str, *, ping: bool = False) -> ConnectorHealth:
    conn = get_connector(source_id)
    meta = SOURCES.get(source_id) or {}
    env_key = meta.get("env_key")
    if env_key:
        from ..paths import read_env

        key = read_env(env_key)
        if not key and meta.get("auth") == "api_key":
            return ConnectorHealth(
                source=source_id,
                ok=False,
                configured=False,
                needs_key=True,
                message=f"Set {env_key} in ~/.config/ai-images/env",
            )
    if not ping:
        cached = _HEALTH_CACHE.get(source_id)
        if cached and (time.time() - cached[0]) < _HEALTH_TTL:
            return cached[1]
        configured = True
        needs_key = False
        if env_key and meta.get("auth") == "api_key":
            from ..paths import read_env

            configured = bool(read_env(env_key))
            needs_key = not configured
        return ConnectorHealth(
            source=source_id,
            ok=configured,
            configured=configured,
            needs_key=needs_key,
            message="Ready (live ping on Sources tab)" if configured else f"Set {env_key}",
        )
    if not conn:
        return ConnectorHealth(source=source_id, ok=False, configured=False, message="not loaded")
    try:
        health = conn.health()
    except Exception as e:
        health = ConnectorHealth(source=source_id, ok=False, configured=False, message=str(e))
    _HEALTH_CACHE[source_id] = (time.time(), health)
    return health


def list_source_summaries(*, ping: bool = False) -> List[dict]:
    out = []
    for sid in SOURCE_ORDER:
        meta = dict(SOURCES.get(sid) or {})
        health = probe_health(sid, ping=ping)
        meta["health"] = {
            "ok": bool(health and health.ok),
            "configured": bool(health and health.configured),
            "needs_key": bool(health and health.needs_key),
            "message": (health.message if health else "not loaded"),
            "latency_ms": health.latency_ms if health else None,
        }
        out.append(meta)
    return out


__all__ = [
    "SearchQuery",
    "SearchPage",
    "ConnectorHealth",
    "get_connector",
    "all_connectors",
    "list_source_summaries",
]
