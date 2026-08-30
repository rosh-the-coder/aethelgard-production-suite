"""Art Institute of Chicago IIIF / Open Access. No API key."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..http_util import get_json
from ..schema import (
    SOURCE_ARTIC,
    NormalizedRecord,
    classify_orientation,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

SEARCH = "https://api.artic.edu/api/v1/artworks/search"
DETAIL = "https://api.artic.edu/api/v1/artworks/{oid}"
IIIF_BASE = "https://www.artic.edu/iiif/2/{image_id}"
FIELDS = ",".join(
    [
        "id",
        "title",
        "artist_display",
        "date_display",
        "date_start",
        "medium_display",
        "image_id",
        "is_public_domain",
        "thumbnail",
        "api_link",
        "artwork_type_title",
        "department_title",
        "style_title",
        "term_titles",
        "dimensions",
        "credit_line",
        "latitude",
        "longitude",
    ]
)


def _iiif(image_id: str, size: str = "843,") -> str:
    if not image_id:
        return ""
    return f"{IIIF_BASE.format(image_id=image_id)}/full/{size}/0/default.jpg"


def _record(item: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(item, dict):
        return None
    image_id = first_text(item.get("image_id"))
    if not image_id:
        return None
    is_pd = bool(item.get("is_public_domain"))
    thumb_meta = item.get("thumbnail") or {}
    width = height = None
    if isinstance(thumb_meta, dict):
        try:
            width = int(thumb_meta.get("width") or 0) or None
            height = int(thumb_meta.get("height") or 0) or None
        except (TypeError, ValueError):
            pass
    lq = first_text(thumb_meta.get("lqip") if isinstance(thumb_meta, dict) else "")
    date_display = first_text(item.get("date_display"))
    tags = [first_text(t) for t in (item.get("term_titles") or [])]
    return NormalizedRecord(
        source=SOURCE_ARTIC,
        source_object_id=str(item.get("id") or ""),
        source_url=f"https://www.artic.edu/artworks/{item.get('id')}",
        source_image_url=_iiif(image_id, "max"),
        thumbnail_url=_iiif(image_id, "400,"),
        title=first_text(item.get("title")) or f"Art Institute {item.get('id')}",
        artist=first_text(item.get("artist_display")) or "Unknown",
        year=year_from_text(date_display) or first_text(item.get("date_start")),
        date_display=date_display,
        description=first_text(item.get("credit_line") or item.get("dimensions")),
        rights_status=classify_rights("public domain" if is_pd else "", is_public_domain=is_pd),
        licence_type="CC0 / Public Domain (Art Institute of Chicago)" if is_pd else "Not public domain",
        is_public_domain=is_pd,
        media_type=first_text(item.get("artwork_type_title")),
        medium=first_text(item.get("medium_display")),
        width=width,
        height=height,
        orientation=classify_orientation(width, height),
        categories=[first_text(item.get("department_title")), first_text(item.get("style_title"))],
        tags=[t for t in tags if t][:16],
        extra={"image_id": image_id, "lqip": lq, "dimensions": item.get("dimensions")},
    )


class ArticConnector:
    id = SOURCE_ARTIC
    name = "Art Institute of Chicago"

    def health(self) -> ConnectorHealth:
        t0 = time.time()
        data, err, status = get_json(
            SEARCH,
            params={"q": "painting", "limit": 1, "fields": "id,title,is_public_domain,image_id"},
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
            message="AIC API reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        page_size = max(1, min(int(query.limit or 24), 100))
        page = (max(0, int(query.offset or 0)) // page_size) + 1
        params: Dict[str, Any] = {
            "q": query.q or "painting",
            "limit": page_size,
            "page": page,
            "fields": FIELDS,
            "query[term][is_public_domain]": "true",
        }
        data, err, _status = get_json(SEARCH, params=params, source=self.id, min_interval=0.25)
        if err or not data:
            return SearchPage(records=[], warning=err or "Art Institute search failed", source=self.id)
        records = []
        for item in data.get("data") or []:
            rec = _record(item)
            if not rec:
                continue
            if query.min_width and rec.width and rec.width < query.min_width:
                continue
            if query.orientation and rec.orientation not in ("unknown", query.orientation):
                continue
            records.append(rec)
        pagination = data.get("pagination") or {}
        total = pagination.get("total")
        offset = int(query.offset or 0)
        has_more = bool(pagination.get("next_url")) or (
            total is not None and offset + page_size < int(total)
        )
        return SearchPage(records=records, total=total, offset=offset, has_more=has_more, source=self.id)

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        data, err, _status = get_json(
            DETAIL.format(oid=source_object_id),
            params={"fields": FIELDS},
            source=self.id,
        )
        if err or not data:
            return None
        return _record(data.get("data") or {})
