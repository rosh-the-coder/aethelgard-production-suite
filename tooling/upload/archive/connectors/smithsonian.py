"""Smithsonian Open Access. Uses SMITHSONIAN_API_KEY or DEMO_KEY."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..http_util import get_json
from ..paths import read_env
from ..schema import (
    SOURCE_SMITHSONIAN,
    NormalizedRecord,
    RIGHTS_CC0,
    classify_orientation,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

API = "https://api.si.edu/openaccess/api/v1.0/search"


def _key() -> str:
    return read_env("SMITHSONIAN_API_KEY") or "DEMO_KEY"


def _media(content: Dict[str, Any]) -> Dict[str, Any]:
    dnr = (content or {}).get("descriptiveNonRepeating") or {}
    media_wrap = dnr.get("online_media") or {}
    media = media_wrap.get("media") or []
    if not media:
        return {}
    preferred = None
    for item in media:
        usage = ((item.get("usage") or {}).get("access") or "").upper()
        if usage in ("CC0", "CC-0"):
            preferred = item
            break
    return preferred or media[0]


def _record(row: Dict[str, Any]) -> Optional[NormalizedRecord]:
    content = row.get("content") or {}
    dnr = content.get("descriptiveNonRepeating") or {}
    media = _media(content)
    image = first_text(media.get("content") or media.get("ids") or "")
    thumb = first_text(media.get("thumbnail") or "")
    if not image and not thumb:
        return None
    usage = first_text((media.get("usage") or {}).get("access") if isinstance(media.get("usage"), dict) else "")
    freetext = content.get("freetext") or {}
    artist = ""
    for name in freetext.get("name") or []:
        artist = first_text(name)
        if artist:
            break
    date_display = first_text((freetext.get("date") or [None])[0] if freetext.get("date") else "")
    medium = first_text((freetext.get("physicalDescription") or [None])[0] if freetext.get("physicalDescription") else "")
    notes = " ".join(first_text(n) for n in (freetext.get("notes") or [])[:3])
    title = first_text(dnr.get("title") or row.get("title"))
    page = first_text(dnr.get("record_link") or row.get("url"))
    oid = first_text(row.get("id") or dnr.get("guid") or title)
    rights = classify_rights(usage or first_text(dnr.get("metadata_usage")), is_public_domain=("CC0" in usage.upper()))
    tags = []
    indexed = content.get("indexedStructured") or {}
    for key in ("object_type", "topic", "name"):
        for val in indexed.get(key) or []:
            tags.append(first_text(val))
    return NormalizedRecord(
        source=SOURCE_SMITHSONIAN,
        source_object_id=oid,
        source_url=page,
        source_image_url=image or thumb,
        thumbnail_url=thumb or image,
        title=title or f"Smithsonian {oid}",
        artist=artist or first_text(dnr.get("data_source")) or "Unknown",
        year=year_from_text(date_display),
        date_display=date_display,
        description=notes,
        rights_status=rights if rights else (RIGHTS_CC0 if "CC0" in usage.upper() else rights),
        licence_type=usage or "Smithsonian Open Access — verify",
        is_public_domain="CC0" in usage.upper() or rights in ("cc0", "public_domain"),
        media_type=first_text((indexed.get("object_type") or [None])[0]) or "Artwork",
        medium=medium,
        orientation="unknown",
        categories=[first_text(dnr.get("data_source"))],
        tags=[t for t in tags if t][:16],
        extra={"unitCode": row.get("unitCode"), "usage": usage},
    )


class SmithsonianConnector:
    id = SOURCE_SMITHSONIAN
    name = "Smithsonian Open Access"

    def health(self) -> ConnectorHealth:
        t0 = time.time()
        data, err, status = get_json(
            API,
            params={"api_key": _key(), "q": "online_media_type:Images", "rows": 1},
            source=self.id,
            timeout=12,
            retries=2,
        )
        ok = bool(data) and not err
        using_demo = _key() == "DEMO_KEY"
        msg = "Open Access reachable"
        if using_demo:
            msg += " (DEMO_KEY — set SMITHSONIAN_API_KEY for higher limits)"
        if not ok:
            msg = err or f"HTTP {status}"
        return ConnectorHealth(
            source=self.id,
            ok=ok,
            configured=True,
            needs_key=False,
            message=msg,
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        q = (query.q or "").strip() or "*"
        terms = [f"({q})", "online_media_type:Images"]
        rights = query.rights or []
        if "cc0" in rights or "public_domain" in rights:
            terms.append("usage_flag:CC0")
        params = {
            "api_key": _key(),
            "q": " AND ".join(terms),
            "rows": max(1, min(int(query.limit or 24), 100)),
            "start": max(0, int(query.offset or 0)),
        }
        data, err, _status = get_json(API, params=params, source=self.id, min_interval=0.4)
        if err or not data:
            return SearchPage(records=[], warning=err or "Smithsonian search failed", source=self.id)
        response = data.get("response") or data
        records = []
        for row in response.get("rows") or []:
            rec = _record(row)
            if rec:
                if query.orientation and rec.orientation not in ("unknown", query.orientation):
                    continue
                records.append(rec)
        total = response.get("rowCount")
        offset = int(query.offset or 0)
        has_more = bool(total is not None and offset + len(records) < int(total))
        return SearchPage(records=records, total=total, offset=offset, has_more=has_more, source=self.id)

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        data, err, _status = get_json(
            API,
            params={"api_key": _key(), "q": f'id:"{source_object_id}"', "rows": 1},
            source=self.id,
        )
        if err or not data:
            return None
        rows = ((data.get("response") or {}).get("rows")) or []
        return _record(rows[0]) if rows else None
