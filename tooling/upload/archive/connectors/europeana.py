"""Europeana Search API. Requires EUROPEANA_API_KEY."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..http_util import get_json
from ..paths import read_env
from ..schema import (
    SOURCE_EUROPEANA,
    NormalizedRecord,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

API = "https://api.europeana.eu/record/v2/search.json"


def _key() -> str:
    return read_env("EUROPEANA_API_KEY")


def _record(item: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(item, dict):
        return None
    image = first_text(item.get("edmIsShownBy") or item.get("edmPreview"))
    thumb = first_text(item.get("edmPreview") or image)
    if not image:
        return None
    rights = first_text(item.get("rights"))
    title = first_text(item.get("title") or item.get("dcTitle"))
    oid = first_text(item.get("id") or title)
    page = first_text(item.get("guid") or item.get("edmIsShownAt"))
    if page and not page.startswith("http"):
        page = f"https://www.europeana.eu/item{oid}" if oid.startswith("/") else page
    status = classify_rights(rights)
    return NormalizedRecord(
        source=SOURCE_EUROPEANA,
        source_object_id=oid,
        source_url=page or f"https://www.europeana.eu/item{oid}",
        source_image_url=image,
        thumbnail_url=thumb,
        title=title or f"Europeana {oid}",
        artist=first_text(item.get("dcCreator") or item.get("dataProvider")) or "Unknown",
        year=year_from_text(first_text(item.get("year") or title)),
        date_display=first_text(item.get("year")),
        description=first_text(item.get("dcDescription") or item.get("dataProvider")),
        rights_status=status,
        licence_type=rights or "Europeana — verify rights",
        is_public_domain=status in ("public_domain", "cc0"),
        media_type=first_text(item.get("type")) or "IMAGE",
        medium="",
        orientation="unknown",
        categories=[first_text(x) for x in (item.get("dataProvider") or [])[:3]]
        if isinstance(item.get("dataProvider"), list)
        else [first_text(item.get("dataProvider"))],
        tags=[first_text(x) for x in (item.get("dcSubject") or [])[:12]],
        extra={"provider": item.get("provider"), "rights": rights},
    )


class EuropeanaConnector:
    id = SOURCE_EUROPEANA
    name = "Europeana"

    def health(self) -> ConnectorHealth:
        key = _key()
        if not key:
            return ConnectorHealth(
                source=self.id,
                ok=False,
                configured=False,
                needs_key=True,
                message="Set EUROPEANA_API_KEY in ~/.config/ai-images/env",
            )
        t0 = time.time()
        data, err, status = get_json(
            API,
            params={"wskey": key, "query": "*", "rows": 1, "media": "true"},
            source=self.id,
            timeout=12,
            retries=2,
        )
        ok = bool(data) and not err
        return ConnectorHealth(
            source=self.id,
            ok=ok,
            configured=True,
            needs_key=False,
            message="Search API reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        key = _key()
        if not key:
            return SearchPage(
                records=[],
                warning="Europeana requires EUROPEANA_API_KEY",
                source=self.id,
            )
        rows = max(1, min(int(query.limit or 24), 100))
        start = max(0, int(query.offset or 0)) + 1  # 1-indexed
        qf = ["TYPE:IMAGE", "MEDIA:true"]
        rights = query.rights or []
        if "cc0" in rights:
            qf.append("RIGHTS:*zero*")
        elif "public_domain" in rights:
            qf.append("RIGHTS:*publicdomain*")
        params: Dict[str, Any] = {
            "wskey": key,
            "query": query.q or "*",
            "rows": rows,
            "start": start,
            "media": "true",
            "qf": qf,
        }
        data, err, _status = get_json(API, params=params, source=self.id, min_interval=0.35)
        if err or not data:
            return SearchPage(records=[], warning=err or "Europeana search failed", source=self.id)
        records = []
        for item in data.get("items") or []:
            rec = _record(item)
            if rec:
                records.append(rec)
        total = data.get("totalResults")
        offset = int(query.offset or 0)
        has_more = bool(total is not None and offset + rows < int(total))
        return SearchPage(records=records, total=total, offset=offset, has_more=has_more, source=self.id)

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        key = _key()
        if not key:
            return None
        data, err, _status = get_json(
            API,
            params={"wskey": key, "query": f'europeana_id:"{source_object_id}"', "rows": 1},
            source=self.id,
        )
        if err or not data:
            return None
        items = data.get("items") or []
        return _record(items[0]) if items else None
