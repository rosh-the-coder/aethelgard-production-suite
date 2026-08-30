"""Library of Congress JSON search. Rights vary — never auto-assume PD."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from ..http_util import get_json
from ..schema import (
    SOURCE_LOC,
    NormalizedRecord,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

SEARCH = "https://www.loc.gov/search/"
HEADERS = {"Accept": "application/json"}


def _abs(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin("https://www.loc.gov/", url)
    return url


def _record(item: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(item, dict):
        return None
    image = ""
    thumb = ""
    image_field = item.get("image")
    if isinstance(image_field, dict):
        image = _abs(first_text(image_field.get("full") or image_field.get("large")))
        thumb = _abs(first_text(image_field.get("thumb") or image_field.get("small") or image))
    elif isinstance(image_field, str):
        image = _abs(image_field)
        thumb = image
    if not image:
        resources = item.get("resources") or []
        if resources and isinstance(resources, list):
            image = _abs(first_text(resources[0].get("url") if isinstance(resources[0], dict) else resources[0]))
    if not image:
        return None
    inner = item.get("item") if isinstance(item.get("item"), dict) else {}
    rights_text = " ".join(
        [
            first_text(item.get("rights")),
            first_text(inner.get("rights_advisory")),
            first_text(inner.get("restriction")),
            " ".join(first_text(x) for x in (item.get("rights_information") or [])[:2]),
        ]
    )
    title = first_text(item.get("title") or inner.get("title"))
    oid = first_text(item.get("id") or item.get("url") or title)
    page = _abs(first_text(item.get("url") or item.get("id") or inner.get("link")))
    contributors = item.get("contributor") or inner.get("contributors") or []
    artist = first_text(contributors[0] if contributors else "") or first_text(inner.get("created_published"))
    date_display = first_text(item.get("date") or inner.get("created_published_date") or inner.get("date"))
    return NormalizedRecord(
        source=SOURCE_LOC,
        source_object_id=oid,
        source_url=page,
        source_image_url=image,
        thumbnail_url=thumb or image,
        title=title or "Library of Congress item",
        artist=artist or "Library of Congress",
        year=year_from_text(date_display or title),
        date_display=date_display,
        description=first_text(item.get("description") or inner.get("notes")),
        rights_status=classify_rights(rights_text),
        licence_type=rights_text.strip() or "Library of Congress — verify before commercial use",
        is_public_domain=False,
        media_type=first_text(item.get("original_format") or item.get("type")),
        medium=first_text(item.get("original_format")),
        orientation="unknown",
        tags=[first_text(s) for s in (item.get("subject") or [])[:12]],
        extra={"partof": item.get("partof"), "rights_raw": rights_text},
    )


class LocConnector:
    id = SOURCE_LOC
    name = "Library of Congress"

    def health(self) -> ConnectorHealth:
        t0 = time.time()
        data, err, status = get_json(
            SEARCH,
            params={"q": "map", "fo": "json", "c": 1},
            headers=HEADERS,
            source=self.id,
            timeout=14,
            retries=2,
            min_interval=0.8,
        )
        ok = bool(data) and not err
        return ConnectorHealth(
            source=self.id,
            ok=ok,
            configured=True,
            needs_key=False,
            message="JSON search reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        page_size = max(1, min(int(query.limit or 24), 50))
        sp = (max(0, int(query.offset or 0)) // page_size) + 1
        params = {
            "q": query.q or "print",
            "fo": "json",
            "c": page_size,
            "sp": sp,
            "fa": "online-format:image",
        }
        data, err, _status = get_json(
            SEARCH, params=params, headers=HEADERS, source=self.id, min_interval=0.9, timeout=30
        )
        if err or not data:
            return SearchPage(records=[], warning=err or "LoC search failed", source=self.id)
        records = []
        for item in data.get("results") or []:
            rec = _record(item)
            if not rec:
                continue
            if query.rights:
                if rec.rights_status not in query.rights and "unclear" not in query.rights:
                    continue
            records.append(rec)
        total = None
        search_info = data.get("search") or data.get("pagination") or {}
        if isinstance(search_info, dict):
            total = search_info.get("hits") or search_info.get("total")
        offset = int(query.offset or 0)
        has_more = len(records) >= page_size
        return SearchPage(
            records=records,
            total=total,
            offset=offset,
            has_more=has_more,
            warning="LoC rights vary. Filter to Public Domain / CC0 before listing.",
            source=self.id,
        )

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        url = source_object_id if str(source_object_id).startswith("http") else f"https://www.loc.gov/item/{source_object_id}/"
        data, err, _status = get_json(
            url, params={"fo": "json"}, headers=HEADERS, source=self.id, min_interval=0.9
        )
        if err or not data:
            return None
        item = data.get("item") if isinstance(data.get("item"), dict) else data
        if isinstance(item, dict) and "id" not in item:
            item = {**item, "id": source_object_id, "url": url}
        return _record(item or {})
