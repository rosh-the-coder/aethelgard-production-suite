"""Rijksmuseum Collection API. Requires RIJKSMUSEUM_API_KEY."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..http_util import get_json
from ..paths import read_env
from ..schema import (
    SOURCE_RIJKSMUSEUM,
    NormalizedRecord,
    classify_orientation,
    classify_rights,
    first_text,
    year_from_text,
)
from .base import ConnectorHealth, SearchPage, SearchQuery

SEARCH = "https://www.rijksmuseum.nl/api/en/collection"
DETAIL = "https://www.rijksmuseum.nl/api/en/collection/{oid}"


def _key() -> str:
    return read_env("RIJKSMUSEUM_API_KEY")


def _record(item: Dict[str, Any]) -> Optional[NormalizedRecord]:
    if not isinstance(item, dict):
        return None
    web = item.get("webImage") or {}
    header = item.get("headerImage") or {}
    image = first_text(web.get("url") if isinstance(web, dict) else "") or first_text(
        header.get("url") if isinstance(header, dict) else ""
    )
    if not image:
        return None
    width = height = None
    if isinstance(web, dict):
        try:
            width = int(web.get("width") or 0) or None
            height = int(web.get("height") or 0) or None
        except (TypeError, ValueError):
            pass
    oid = first_text(item.get("objectNumber") or item.get("id"))
    links = item.get("links") or {}
    page = first_text(links.get("web") if isinstance(links, dict) else "") or (
        f"https://www.rijksmuseum.nl/en/collection/{oid}" if oid else ""
    )
    title = first_text(item.get("title") or item.get("longTitle"))
    artist = first_text(item.get("principalOrFirstMaker"))
    date_display = first_text(item.get("longTitle"))
    rights_blob = " ".join(
        [
            first_text(item.get("permitDownload")),
            first_text(item.get("copyrightHolder")),
            "open access" if image else "",
        ]
    )
    return NormalizedRecord(
        source=SOURCE_RIJKSMUSEUM,
        source_object_id=oid,
        source_url=page,
        source_image_url=image,
        thumbnail_url=first_text(header.get("url") if isinstance(header, dict) else "") or image,
        title=title or f"Rijksmuseum {oid}",
        artist=artist or "Unknown",
        year=year_from_text(date_display or title),
        date_display=date_display,
        description=first_text(item.get("longTitle")),
        rights_status=classify_rights(rights_blob, is_public_domain=None),
        licence_type=first_text(item.get("copyrightHolder")) or "Rijksmuseum — verify Open Access",
        is_public_domain=False,
        media_type="Artwork",
        medium="",
        width=width,
        height=height,
        orientation=classify_orientation(width, height),
        tags=[t for t in (item.get("productionPlaces") or []) if t],
        extra={"objectNumber": oid, "hasImage": True},
    )


class RijksmuseumConnector:
    id = SOURCE_RIJKSMUSEUM
    name = "Rijksmuseum"

    def health(self) -> ConnectorHealth:
        key = _key()
        if not key:
            return ConnectorHealth(
                source=self.id,
                ok=False,
                configured=False,
                needs_key=True,
                message="Set RIJKSMUSEUM_API_KEY in ~/.config/ai-images/env",
            )
        t0 = time.time()
        data, err, status = get_json(
            SEARCH,
            params={"key": key, "ps": 1, "imgonly": "true", "format": "json"},
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
            message="Collection API reachable" if ok else (err or f"HTTP {status}"),
            latency_ms=int((time.time() - t0) * 1000),
        )

    def search(self, query: SearchQuery) -> SearchPage:
        key = _key()
        if not key:
            return SearchPage(
                records=[],
                warning="Rijksmuseum requires RIJKSMUSEUM_API_KEY",
                source=self.id,
            )
        page_size = max(1, min(int(query.limit or 24), 100))
        page = (max(0, int(query.offset or 0)) // page_size) + 1
        params: Dict[str, Any] = {
            "key": key,
            "q": query.q or "",
            "imgonly": "true",
            "ps": page_size,
            "p": page,
            "format": "json",
        }
        data, err, _status = get_json(SEARCH, params=params, source=self.id, min_interval=0.35)
        if err or not data:
            return SearchPage(records=[], warning=err or "Rijksmuseum search failed", source=self.id)
        records = []
        for item in data.get("artObjects") or []:
            rec = _record(item)
            if not rec:
                continue
            if query.min_width and rec.width and rec.width < query.min_width:
                continue
            if query.orientation and rec.orientation not in ("unknown", query.orientation):
                continue
            records.append(rec)
        total = data.get("count")
        offset = int(query.offset or 0)
        has_more = bool(total is not None and offset + page_size < int(total))
        return SearchPage(records=records, total=total, offset=offset, has_more=has_more, source=self.id)

    def fetch(self, source_object_id: str) -> Optional[NormalizedRecord]:
        key = _key()
        if not key:
            return None
        data, err, _status = get_json(
            DETAIL.format(oid=source_object_id),
            params={"key": key, "format": "json"},
            source=self.id,
        )
        if err or not data:
            return None
        art = data.get("artObject") or data
        rec = _record(art)
        if rec:
            rec.medium = first_text((art.get("physicalMedium") if isinstance(art, dict) else "") or rec.medium)
            rec.description = first_text(
                ((art.get("plaqueDescriptionEnglish") if isinstance(art, dict) else "") or rec.description)
            )
            rights = ""
            if isinstance(art, dict):
                rights = first_text(art.get("copyrightHolder")) + " " + first_text(art.get("acquisition"))
            rec.rights_status = classify_rights(rights or rec.licence_type)
            rec.licence_type = rights.strip() or rec.licence_type
        return rec
