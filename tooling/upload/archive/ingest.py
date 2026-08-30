"""Live multi-source search and metadata-first import."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Sequence

from . import store
from .connectors import SearchQuery, get_connector, all_connectors
from .log import log_event
from .schema import SOURCE_ORDER, NormalizedRecord, rights_is_clear_reuse


def _query_from_filters(q: str, filters: Optional[Dict[str, Any]], *, limit: int, offset: int) -> SearchQuery:
    filters = filters or {}
    rights = filters.get("rights")
    if isinstance(rights, str):
        rights = [rights] if rights else None
    return SearchQuery(
        q=q or "",
        limit=limit,
        offset=offset,
        rights=rights,
        media_type=str(filters.get("media_type") or filters.get("artwork_type") or ""),
        orientation=str(filters.get("orientation") or ""),
        min_width=int(filters["min_width"]) if filters.get("min_width") else None,
        has_image=bool(filters.get("has_image", True)),
    )


def search_sources(
    q: str,
    *,
    sources: Optional[Sequence[str]] = None,
    limit: int = 24,
    offset: int = 0,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wanted = [s for s in (sources or SOURCE_ORDER) if s in all_connectors()]
    if not wanted:
        wanted = list(SOURCE_ORDER)
    per_source = max(8, int(limit or 24) // max(1, len(wanted)))
    pages = []

    def _one(sid: str):
        conn = get_connector(sid)
        if not conn:
            return {"source": sid, "records": [], "warning": "unknown source"}
        try:
            page = conn.search(_query_from_filters(q, filters, limit=per_source, offset=offset))
            return {
                "source": sid,
                "records": [r.to_dict() for r in page.records],
                "total": page.total,
                "has_more": page.has_more,
                "warning": page.warning,
            }
        except Exception as e:
            log_event("search.failed", level="error", source=sid, message=str(e), query=q)
            return {"source": sid, "records": [], "warning": str(e)}

    with ThreadPoolExecutor(max_workers=min(7, len(wanted))) as pool:
        futs = [pool.submit(_one, sid) for sid in wanted]
        for fut in as_completed(futs):
            pages.append(fut.result())

    pages.sort(key=lambda p: wanted.index(p["source"]) if p["source"] in wanted else 99)
    records: List[Dict[str, Any]] = []
    for page in pages:
        records.extend(page.get("records") or [])

    rights = (filters or {}).get("rights") or []
    if isinstance(rights, str):
        rights = [rights]
    if rights:
        allowed = set(rights)
        records = [r for r in records if r.get("rights_status") in allowed]

    orientation = (filters or {}).get("orientation")
    if orientation:
        records = [r for r in records if r.get("orientation") in ("unknown", orientation)]

    return {
        "query": q,
        "sources": wanted,
        "pages": pages,
        "results": records,
        "count": len(records),
        "offset": offset,
        "has_more": any(p.get("has_more") for p in pages),
    }


def import_records(
    records: Sequence[Any],
    *,
    import_batch_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    skip_duplicates: bool = True,
    require_clear_rights: bool = False,
) -> Dict[str, Any]:
    created = 0
    updated = 0
    skipped = 0
    imported_ids: List[str] = []
    errors: List[Dict[str, Any]] = []
    for raw in records:
        try:
            rec = raw if isinstance(raw, NormalizedRecord) else NormalizedRecord(
                source=str(raw.get("source") or ""),
                source_object_id=str(raw.get("source_object_id") or raw.get("object_id") or ""),
                source_url=str(raw.get("source_url") or raw.get("object_url") or ""),
                source_image_url=str(raw.get("source_image_url") or raw.get("image") or ""),
                thumbnail_url=str(raw.get("thumbnail_url") or raw.get("image_small") or raw.get("image") or ""),
                title=str(raw.get("title") or ""),
                artist=str(raw.get("artist") or ""),
                year=str(raw.get("year") or ""),
                date_display=str(raw.get("date_display") or raw.get("date") or ""),
                description=str(raw.get("description") or ""),
                rights_status=str(raw.get("rights_status") or "unclear"),
                licence_type=str(raw.get("licence_type") or raw.get("rights") or ""),
                is_public_domain=bool(raw.get("is_public_domain")),
                media_type=str(raw.get("media_type") or ""),
                medium=str(raw.get("medium") or ""),
                width=raw.get("width"),
                height=raw.get("height"),
                orientation=str(raw.get("orientation") or "unknown"),
                categories=list(raw.get("categories") or []),
                tags=list(raw.get("tags") or []),
                theme=str(raw.get("theme") or ""),
                extra=dict(raw.get("extra") or {}),
            )
            if not rec.source or not rec.source_object_id:
                skipped += 1
                continue
            if require_clear_rights and not rights_is_clear_reuse(rec.rights_status):
                skipped += 1
                continue
            existing = store.get_asset_by_source(rec.source, rec.source_object_id)
            if existing and skip_duplicates:
                imported_ids.append(existing["id"])
                skipped += 1
                continue
            asset, was_created = store.upsert_record(
                rec,
                import_batch_id=import_batch_id,
                allow_duplicate=not skip_duplicates,
            )
            if was_created:
                created += 1
            else:
                updated += 1
            imported_ids.append(asset["id"])
        except Exception as e:
            errors.append({"error": str(e), "record": getattr(raw, "source_object_id", None)})
            log_event("import.record_failed", level="error", message=str(e))
    if collection_id and imported_ids:
        store.add_assets_to_collection(collection_id, imported_ids)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "imported_ids": imported_ids,
        "errors": errors,
    }
