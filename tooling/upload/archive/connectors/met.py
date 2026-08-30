"""The Met Open Access. Independent of Art Studio's public_domain.py search."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from ..http_util import get_json
from ..schema import (
    SOURCE_MET,
    NormalizedRecord,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}"


def _record(obj: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(obj, dict):
        return None
    if not obj.get("isPublicDomain"):
        return None
    image = first_text(obj.get("primaryImage") or obj.get("primaryImageSmall"))
    if not image:
        return None
    tags = []
    for tag in obj.get("tags") or []:
        if isinstance(tag, dict):
            tags.append(first_text(tag.get("term")))
        else:
            tags.append(first_text(tag))
    date_display = first_text(obj.get("objectDate"))
    oid = str(obj.get("objectID") or "")
    return NormalizedRecord(
        source=SOURCE_MET,
        source_object_id=oid,
        source_url=first_text(obj.get("objectURL")) or f"https://www.metmuseum.org/art/collection/search/{oid}",
        source_image_url=image,
        thumbnail_url=first_text(obj.get("primaryImageSmall") or image),
        title=first_text(obj.get("title")) or f"Met object {oid}",
        artist=first_text(obj.get("artistDisplayName") or obj.get("culture")) or "Unknown",
        year=year_from_text(date_display) or first_text(obj.get("objectBeginDate")),
        date_display=date_display,
        description=first_text(obj.get("creditLine") or obj.get("medium")),
        rights_status=classify_rights("public domain (Met Open Access)", is_public_domain=True),
        licence_type="Public Domain (Met Open Access)",
        is_public_domain=True,
        media_type=first_text(obj.get("classification") or obj.get("objectName")),
        medium=first_text(obj.get("medium")),
        orientation="unknown",
        categories=[first_text(obj.get("department")), first_text(obj.get("classification"))],
        tags=[t for t in tags if t][:16],
        extra={
            "dimensions": obj.get("dimensions"),
            "credit": obj.get("creditLine"),
            "repository": obj.get("repository"),
        },
    )


def _fetch_id(oid: Any) -> Optional[NormalizedRecord]:
    data, err, _status = get_json(OBJECT.format(oid=oid), source=SOURCE_MET, min_interval=0.05, timeout=20, retries=2)
    if err or not data:
        return None
    return _record(data)


class MetConnector:
    id = SOURCE_MET
    name = "The Met"

    def health(self) -> ConnectorHealth:
        t0 = time.time()
        data, err, status = get_json(
            SEARCH,
            params={"q": "sunflower", "isPublicDomain": "true", "hasImages": "true"},
            source=self.id,
            timeout=14,
            retries=2,
        )
        ok = bool(data) and not err
        return ConnectorHealth(
            source=self.id,
            ok=ok,
            configured=True,
            needs_key=False,
            message="Collection API reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        data, err, _status = get_json(
            SEARCH,
            params={
                "q": query.q or "painting",
                "isPublicDomain": "true",
                "hasImages": "true",
            },
            source=self.id,
            min_interval=0.2,
            timeout=30,
        )
        if err or not data:
            return SearchPage(records=[], warning=err or "Met search failed", source=self.id)
        ids: List[Any] = list(data.get("objectIDs") or [])
        total = int(data.get("total") or len(ids))
        offset = max(0, int(query.offset or 0))
        limit = max(1, min(int(query.limit or 24), 40))
        slice_ids = ids[offset : offset + limit]
        records: List[NormalizedRecord] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {pool.submit(_fetch_id, oid): oid for oid in slice_ids}
            for fut in as_completed(futs):
                rec = fut.result()
                if rec:
                    records.append(rec)
        records.sort(key=lambda r: slice_ids.index(int(r.source_object_id)) if r.source_object_id.isdigit() else 0)
        has_more = offset + limit < len(ids)
        return SearchPage(
            records=records,
            total=total,
            offset=offset,
            has_more=has_more,
            source=self.id,
        )

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        return _fetch_id(source_object_id)
