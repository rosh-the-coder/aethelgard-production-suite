"""Semi-automated import / tagging / grouping rules."""
from __future__ import annotations

from typing import Any, Dict, List

from . import ingest, store
from .log import log_event


def run_rule(rule_id: str) -> Dict[str, Any]:
    rule = store.get_rule(rule_id)
    if not rule:
        return {"ok": False, "error": "rule not found"}
    query = rule.get("query") or ""
    sources = rule.get("sources") or []
    filters = rule.get("filters") or {}
    actions = rule.get("actions") or []
    page_size = int(filters.get("limit") or 48)
    result = ingest.search_sources(query, sources=sources, limit=page_size, offset=0, filters=filters)
    records = result.get("results") or []
    require_clear = bool(filters.get("require_clear_rights") or filters.get("public_domain_only"))
    imported = ingest.import_records(
        records,
        skip_duplicates=True,
        require_clear_rights=require_clear,
    )
    asset_ids = imported.get("imported_ids") or []
    applied: List[str] = []
    for action in actions:
        kind = (action.get("type") or action.get("action") or "").lower()
        if kind in ("collect", "collection") and action.get("collection_id") and asset_ids:
            store.add_assets_to_collection(action["collection_id"], asset_ids)
            applied.append("collect")
        elif kind in ("tag", "auto_tag") and asset_ids:
            tags = action.get("tags") or []
            for aid in asset_ids:
                asset = store.get_asset(aid)
                if not asset:
                    continue
                merged = list(dict.fromkeys((asset.get("tags") or []) + list(tags)))
                store.update_asset(aid, tags=merged)
            applied.append("tag")
        elif kind in ("theme", "group") and asset_ids:
            theme = action.get("theme") or action.get("value") or query
            for aid in asset_ids:
                store.update_asset(aid, theme=theme)
            applied.append("theme")
        elif kind in ("download", "fullres") and asset_ids:
            from . import jobs as jobmod

            jobmod.enqueue("fullres_download", {"asset_ids": asset_ids})
            applied.append("download")
        elif kind in ("pipeline", "listing") and asset_ids:
            from . import jobs as jobmod

            jobmod.enqueue(
                "pipeline_handoff",
                {"asset_ids": asset_ids, "concept": action.get("concept") or query},
            )
            applied.append("pipeline")
        elif kind in ("drive", "drive_sync") and asset_ids:
            from . import jobs as jobmod

            jobmod.enqueue("drive_sync", {"asset_ids": asset_ids})
            applied.append("drive")
    summary = {
        "ok": True,
        "searched": len(records),
        "imported": imported,
        "actions": applied,
    }
    store.update_rule(rule_id, {"last_run_at": __import__("time").time(), "last_result": summary})
    log_event("rule.ran", message=rule.get("name"), **{k: summary[k] for k in ("searched", "actions")})
    return summary
