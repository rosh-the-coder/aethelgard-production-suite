"""Connector protocol and search page types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ..schema import NormalizedRecord


@dataclass
class SearchQuery:
    q: str = ""
    limit: int = 24
    offset: int = 0
    rights: Optional[List[str]] = None
    media_type: str = ""
    orientation: str = ""
    min_width: Optional[int] = None
    has_image: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchPage:
    records: List[NormalizedRecord]
    total: Optional[int] = None
    offset: int = 0
    has_more: bool = False
    cursor: Optional[str] = None
    warning: Optional[str] = None
    source: str = ""


@dataclass
class ConnectorHealth:
    source: str
    ok: bool
    configured: bool
    needs_key: bool = False
    message: str = ""
    latency_ms: Optional[int] = None


class Connector(Protocol):
    id: str
    name: str

    def health(self) -> ConnectorHealth: ...

    def search(self, query: SearchQuery) -> SearchPage: ...

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]: ...
