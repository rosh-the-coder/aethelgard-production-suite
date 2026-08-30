"""Cleveland Museum of Art Open Access (CC0) — no API key."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..http_util import get_json
from ..schema import (
    SOURCE_CLEVELAND,
    NormalizedRecord,
    RIGHTS_CC0,
    classify_orientation,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

API = "https://openaccess-api.clevelandart.org/api/artworks/"


def _record(item: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(item, dict):
        return None
    images = item.get("images") or {}
    full = ((images.get("full") or {}) if isinstance(images, dict) else {}).get("url") or ""
    print_url = ((images.get("print") or {}) if isinstance(images, dict) else {}).get("url") or ""
    web = ((images.get("web") or {}) if isinstance(images, dict) else {}).get("url") or ""
    image = full or print_url or web
    if not image:
        return None
    creators = item.get("creators") or []
    artist = ""
    if creators and isinstance(creators, list):
        artist = first_text(creators[0].get("description") or creators[0].get("name"))
    date_display = first_text(item.get("creation_date") or item.get("creation_date_earliest"))
    width = height = None
    meas = images.get("full") or images.get("print") or images.get("web") or {}
    if isinstance(meas, dict):
        try:
            width = int(meas.get("width") or 0) or None
            height = int(meas.get("height") or 0) or None
        except (TypeError, ValueError):
            pass
    licence = first_text(item.get("share_license_status") or "CC0")
    tags = []
    for key in ("tombstone", "type", "technique", "department"):
        val = first_text(item.get(key))
        if val:
            tags.append(val)
    for subj in item.get("subject_matter") or []:
        tags.append(first_text(subj))
    return NormalizedRecord(
        source=SOURCE_CLEVELAND,
        source_object_id=str(item.get("id") or item.get("accession_number") or ""),
        source_url=first_text(item.get("url") or item.get("citation")),
        source_image_url=image,
        thumbnail_url=web or image,
        title=first_text(item.get("title")) or f"Cleveland {item.get('id')}",
        artist=artist or "Unknown",
        year=year_from_text(date_display),
        date_display=date_display,
        description=first_text(item.get("description") or item.get("fun_fact") or item.get("tombstone")),
        rights_status=classify_rights(licence, is_public_domain=True) or RIGHTS_CC0,
        licence_type=licence or "CC0",
        is_public_domain=True,
        media_type=first_text(item.get("type")) or "Artwork",
        medium=first_text(item.get("technique") or item.get("medium")),
        width=width,
        height=height,
        orientation=classify_orientation(width, height),
        categories=[first_text(item.get("department")), first_text(item.get("type"))],
        tags=[t for t in tags if t],
        extra={
            "accession_number": item.get("accession_number"),
            "measurements": item.get("measurements"),
            "credit": item.get("creditline"),
        },
    )


class ClevelandConnector:
    id = SOURCE_CLEVELAND
    name = "Cleveland Museum of Art"

    def health(self) -> ConnectorHealth:
        t0 = time.time()
        data, err, status = get_json(
            API, params={"limit": 1, "cc0": 1, "has_image": 1}, source=self.id, timeout=12, retries=2
        )
        ok = bool(data) and not err
        return ConnectorHealth(
            source=self.id,
            ok=ok,
            configured=True,
            needs_key=False,
            message="Open Access reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        params: Dict[str, Any] = {
            "q": query.q or "",
            "cc0": 1,
            "has_image": 1 if query.has_image else 0,
            "limit": max(1, min(int(query.limit or 24), 100)),
            "skip": max(0, int(query.offset or 0)),
        }
        if query.media_type:
            params["type"] = query.media_type
        data, err, _status = get_json(API, params=params, source=self.id, min_interval=0.2)
        if err or not data:
            return SearchPage(records=[], warning=err or "Cleveland search failed", source=self.id)
        records = []
        for item in data.get("data") or []:
            rec = _record(item)
            if rec:
                if query.min_width and (rec.width or 0) and rec.width < query.min_width:
                    continue
                if query.orientation and rec.orientation not in ("unknown", query.orientation):
                    continue
                records.append(rec)
        info = data.get("info") or {}
        total = info.get("total")
        offset = int(query.offset or 0)
        has_more = bool(total is not None and offset + len(records) < int(total))
        if total is None:
            has_more = len(records) >= int(query.limit or 24)
        return SearchPage(
            records=records,
            total=total,
            offset=offset,
            has_more=has_more,
            source=self.id,
        )

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        data, err, _status = get_json(f"{API}{source_object_id}", source=self.id)
        if err or not data:
            return None
        item = data.get("data") if isinstance(data.get("data"), dict) else data
        return _record(item or {})
