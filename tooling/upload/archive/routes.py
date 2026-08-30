"""HTTP API for Archive Studio. Prefix: /api/archive/*

Does not claim any existing factory, public_domain, drive, or Etsy routes.
"""
from __future__ import annotations

import json
import mimetypes
import os
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import download, drive_sync, ingest, jobs, pipeline, qc, rules, store, worker
from .connectors import list_source_summaries
from .http_util import get_bytes, host_allowed
from .log import log_event
from .schema import SOURCE_ORDER


def boot_archive() -> None:
    store.init_db()
    worker.start_worker()
    log_event("archive.booted")


def _json(handler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _bytes(handler, data: bytes, content_type: str, cache: str = "private, max-age=120") -> None:
    handler.send_response(200)
    handler.send_header("Content-type", content_type)
    handler.send_header("Cache-Control", cache)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _qs(handler) -> Dict[str, str]:
    parsed = urlparse(handler.path)
    raw = parse_qs(parsed.query)
    return {k: (v[0] if v else "") for k, v in raw.items()}


def _bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def _csv(value: str):
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def handle_get(handler, path: str) -> bool:
    if not path.startswith("/api/archive"):
        return False
    try:
        return _handle_get(handler, path)
    except Exception as e:
        log_event("api.get_error", level="error", message=str(e), path=path)
        _json(handler, {"ok": False, "error": str(e)}, 500)
        return True


def _handle_get(handler, path: str) -> bool:
    qs = _qs(handler)

    if path == "/api/archive/sources":
        ping = (qs.get("health") or qs.get("ping") or "") in ("1", "true", "yes")
        summaries = list_source_summaries(ping=ping)
        counts = store.stats().get("by_source") or {}
        for item in summaries:
            item["library_count"] = int(counts.get(item.get("id"), 0) or 0)
        _json(handler, {"ok": True, "sources": summaries, "order": SOURCE_ORDER})
        return True

    if path == "/api/archive/stats":
        _json(handler, {"ok": True, **store.stats(), "settings": store.load_settings()})
        return True

    if path == "/api/archive/settings":
        _json(handler, {"ok": True, "settings": store.load_settings()})
        return True

    if path == "/api/archive/search":
        result = ingest.search_sources(
            qs.get("q") or "",
            sources=_csv(qs.get("sources") or ""),
            limit=int(qs.get("limit") or 24),
            offset=int(qs.get("offset") or 0),
            filters={
                "rights": _csv(qs.get("rights") or ""),
                "orientation": qs.get("orientation") or "",
                "media_type": qs.get("media_type") or qs.get("artwork_type") or "",
                "min_width": int(qs["min_width"]) if qs.get("min_width") else None,
                "has_image": _bool(qs.get("has_image")) if qs.get("has_image") != "" else True,
            },
        )
        _json(handler, {"ok": True, **result})
        return True

    if path == "/api/archive/assets":
        result = store.list_assets(
            q=qs.get("q") or "",
            source=qs.get("source") or "",
            sources=_csv(qs.get("sources") or ""),
            rights=_csv(qs.get("rights") or ""),
            orientation=qs.get("orientation") or "",
            processing_status=qs.get("status") or qs.get("processing_status") or "",
            collection_id=qs.get("collection_id") or "",
            has_fullres=_bool(qs.get("has_fullres")),
            has_image=_bool(qs.get("has_image")),
            min_width=int(qs["min_width"]) if qs.get("min_width") else None,
            qc_flag=qs.get("qc_flag") or "",
            tags=_csv(qs.get("tags") or ""),
            limit=int(qs.get("limit") or 48),
            offset=int(qs.get("offset") or 0),
        )
        _json(handler, {"ok": True, **result})
        return True

    if path.startswith("/api/archive/assets/") and path.endswith("/thumbnail"):
        aid = path[len("/api/archive/assets/") : -len("/thumbnail")]
        asset = store.get_asset(aid)
        if not asset:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        path_local = download.local_preview_path(asset)
        if path_local:
            mime = mimetypes.guess_type(path_local)[0] or "image/jpeg"
            with open(path_local, "rb") as f:
                _bytes(handler, f.read(), mime)
            return True
        url = asset.get("thumbnail_url") or asset.get("source_image_url")
        if not url:
            _json(handler, {"ok": False, "error": "no image"}, 404)
            return True
        data, mime, err = get_bytes(url, source=asset.get("source") or "default", timeout=20)
        if err or not data:
            _json(handler, {"ok": False, "error": err or "fetch failed"}, 502)
            return True
        _bytes(handler, data, mime or "image/jpeg")
        return True

    if path.startswith("/api/archive/assets/") and path.endswith("/image"):
        aid = path[len("/api/archive/assets/") : -len("/image")]
        asset = store.get_asset(aid)
        if not asset:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        local = asset.get("local_file_path") or download.local_preview_path(asset)
        if local and os.path.isfile(local):
            mime = mimetypes.guess_type(local)[0] or "image/jpeg"
            with open(local, "rb") as f:
                _bytes(handler, f.read(), mime, cache="private, max-age=600")
            return True
        url = asset.get("source_image_url")
        data, mime, err = get_bytes(url or "", source=asset.get("source") or "default", timeout=40)
        if err or not data:
            _json(handler, {"ok": False, "error": err or "fetch failed"}, 502)
            return True
        _bytes(handler, data, mime or "image/jpeg")
        return True

    if path.startswith("/api/archive/assets/"):
        aid = path.split("/")[-1]
        asset = store.get_asset(aid)
        if not asset:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        _json(handler, {"ok": True, "asset": asset})
        return True

    if path == "/api/archive/collections":
        _json(handler, {"ok": True, "collections": store.list_collections()})
        return True

    if path.startswith("/api/archive/collections/"):
        cid = path.split("/")[-1]
        col = store.get_collection(cid)
        if not col:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        page = store.list_assets(collection_id=cid, limit=int(qs.get("limit") or 60), offset=int(qs.get("offset") or 0))
        _json(handler, {"ok": True, "collection": col, **page})
        return True

    if path == "/api/archive/jobs":
        _json(handler, {"ok": True, "jobs": store.list_jobs(limit=int(qs.get("limit") or 80))})
        return True

    if path.startswith("/api/archive/jobs/"):
        jid = path.split("/")[-1]
        job = store.get_job(jid)
        if not job:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        _json(handler, {"ok": True, "job": job})
        return True

    if path == "/api/archive/rules":
        _json(handler, {"ok": True, "rules": store.list_rules()})
        return True

    if path == "/api/archive/logs":
        _json(handler, {"ok": True, "logs": store.list_logs(limit=int(qs.get("limit") or 120))})
        return True

    if path == "/api/archive/drive/status":
        payload = {"connected": False}
        try:
            import drive_delivery

            payload = drive_delivery.status()
        except Exception as e:
            payload = {"connected": False, "error": str(e)}
        payload["folders"] = store.load_settings().get("drive_folders") or {}
        _json(handler, {"ok": True, **payload})
        return True

    if path == "/api/archive/proxy-image":
        url = qs.get("url") or ""
        if not url or not host_allowed(url):
            _json(handler, {"ok": False, "error": "url not allowlisted"}, 400)
            return True
        data, mime, err = get_bytes(url, source="proxy", timeout=25)
        if err or not data:
            _json(handler, {"ok": False, "error": err or "fetch failed"}, 502)
            return True
        _bytes(handler, data, mime or "image/jpeg")
        return True

    return False


def handle_post(handler, path: str, data: Optional[Dict[str, Any]] = None) -> bool:
    if not path.startswith("/api/archive"):
        return False
    data = data or {}
    try:
        return _handle_post(handler, path, data)
    except Exception as e:
        log_event("api.post_error", level="error", message=str(e), path=path)
        _json(handler, {"ok": False, "error": str(e)}, 500)
        return True


def _handle_post(handler, path: str, data: Dict[str, Any]) -> bool:
    if path == "/api/archive/settings":
        _json(handler, {"ok": True, "settings": store.save_settings(data)})
        return True

    if path == "/api/archive/import":
        records = data.get("records") or data.get("objects") or []
        result = ingest.import_records(
            records,
            import_batch_id=data.get("import_batch_id"),
            collection_id=data.get("collection_id"),
            skip_duplicates=bool(data.get("skip_duplicates", True)),
            require_clear_rights=bool(data.get("require_clear_rights")),
        )
        if data.get("sync_thumbs"):
            jobs.enqueue("thumbnail_sync", {"asset_ids": result.get("imported_ids") or []})
        _json(handler, {"ok": True, **result})
        return True

    if path in ("/api/archive/import/search", "/api/archive/jobs/search-ingest"):
        job = jobs.enqueue(
            "search_ingest",
            {
                "query": data.get("query") or data.get("q") or "",
                "sources": data.get("sources") or [],
                "filters": data.get("filters") or {},
                "max_records": int(data.get("max_records") or data.get("limit") or 100),
                "collection_id": data.get("collection_id"),
                "skip_duplicates": bool(data.get("skip_duplicates", True)),
                "sync_thumbs": bool(data.get("sync_thumbs", True)),
            },
        )
        _json(handler, {"ok": True, "job": job})
        return True

    if path == "/api/archive/assets/bulk":
        ids = list(data.get("ids") or data.get("asset_ids") or [])
        action = (data.get("action") or "").lower()
        result: Dict[str, Any] = {"action": action, "count": len(ids)}
        if action in ("download", "fullres"):
            result["job"] = jobs.enqueue("fullres_download", {"asset_ids": ids})
        elif action in ("thumbs", "thumbnail"):
            result["job"] = jobs.enqueue("thumbnail_sync", {"asset_ids": ids})
        elif action in ("drive", "drive_sync"):
            result["job"] = jobs.enqueue(
                "drive_sync",
                {
                    "asset_ids": ids,
                    "folder_kind": data.get("folder_kind") or "source_archive",
                    "collection_name": data.get("collection_name") or "",
                },
            )
        elif action in ("pipeline", "listing"):
            result["job"] = jobs.enqueue(
                "pipeline_handoff",
                {
                    "asset_ids": ids,
                    "concept": data.get("concept") or "",
                    "collection_id": data.get("collection_id"),
                },
            )
        elif action in ("collect", "collection"):
            cid = data.get("collection_id")
            if not cid:
                _json(handler, {"ok": False, "error": "collection_id required"}, 400)
                return True
            store.add_assets_to_collection(cid, ids)
            result["collection_id"] = cid
        elif action == "tag":
            tags = data.get("tags") or []
            for aid in ids:
                asset = store.get_asset(aid)
                if not asset:
                    continue
                merged = list(dict.fromkeys((asset.get("tags") or []) + list(tags)))
                store.update_asset(aid, tags=merged)
        elif action == "theme":
            for aid in ids:
                store.update_asset(aid, theme=data.get("theme") or "")
        elif action == "approve":
            for aid in ids:
                store.update_asset(aid, processing_status="approved")
        elif action == "delete":
            result["deleted"] = store.delete_assets(ids)
        elif action == "dedupe":
            result["job"] = jobs.enqueue("dedupe_scan", {"asset_ids": ids})
        elif action == "qc":
            settings = store.load_settings()
            for aid in ids:
                asset = store.get_asset(aid)
                if not asset:
                    continue
                flags = qc.evaluate(
                    asset,
                    min_width=int(settings.get("min_width") or 1200),
                    min_height=int(settings.get("min_height") or 1200),
                    expected_orientation=data.get("orientation") or "",
                )
                status = "qc_flagged" if flags else asset.get("processing_status")
                store.update_asset(aid, qc_flags=flags, processing_status=status)
        else:
            _json(handler, {"ok": False, "error": f"unknown action: {action}"}, 400)
            return True
        _json(handler, {"ok": True, **result})
        return True

    if path.startswith("/api/archive/assets/") and path.endswith("/update"):
        aid = path.split("/")[-2]
        asset = store.update_asset(aid, **{k: v for k, v in data.items() if k != "id"})
        if not asset:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        _json(handler, {"ok": True, "asset": asset})
        return True

    if path == "/api/archive/collections":
        name = (data.get("name") or "").strip()
        if not name:
            _json(handler, {"ok": False, "error": "name required"}, 400)
            return True
        col = store.create_collection(
            name, description=data.get("description") or "", drive_folder=data.get("drive_folder") or ""
        )
        ids = data.get("asset_ids") or []
        if ids:
            store.add_assets_to_collection(col["id"], ids)
            col = store.get_collection(col["id"])
        _json(handler, {"ok": True, "collection": col})
        return True

    if path.startswith("/api/archive/collections/") and path.endswith("/assets"):
        cid = path.split("/")[-2]
        store.add_assets_to_collection(cid, data.get("asset_ids") or data.get("ids") or [])
        _json(handler, {"ok": True, "collection": store.get_collection(cid)})
        return True

    if path.startswith("/api/archive/collections/") and path.endswith("/remove"):
        cid = path.split("/")[-2]
        store.remove_assets_from_collection(cid, data.get("asset_ids") or data.get("ids") or [])
        _json(handler, {"ok": True, "collection": store.get_collection(cid)})
        return True

    if path.startswith("/api/archive/collections/") and path.endswith("/delete"):
        cid = path.split("/")[-2]
        _json(handler, {"ok": True, "deleted": store.delete_collection(cid)})
        return True

    if path.startswith("/api/archive/collections/") and path.endswith("/update"):
        cid = path.split("/")[-2]
        col = store.update_collection(cid, **data)
        _json(handler, {"ok": True, "collection": col})
        return True

    if path == "/api/archive/jobs":
        kind = data.get("kind")
        if not kind:
            _json(handler, {"ok": False, "error": "kind required"}, 400)
            return True
        job = jobs.enqueue(kind, data.get("payload") or data)
        _json(handler, {"ok": True, "job": job})
        return True

    if path.startswith("/api/archive/jobs/") and path.endswith("/retry"):
        jid = path.split("/")[-2]
        job = store.get_job(jid)
        if not job:
            _json(handler, {"ok": False, "error": "not found"}, 404)
            return True
        store.update_job(jid, status="queued", error="", message="retry")
        _json(handler, {"ok": True, "job": store.get_job(jid)})
        return True

    if path.startswith("/api/archive/jobs/") and path.endswith("/cancel"):
        jid = path.split("/")[-2]
        store.update_job(jid, status="cancelled", completed_at=__import__("time").time(), message="cancelled")
        _json(handler, {"ok": True, "job": store.get_job(jid)})
        return True

    if path == "/api/archive/rules":
        rule = store.create_rule(data)
        _json(handler, {"ok": True, "rule": rule})
        return True

    if path.startswith("/api/archive/rules/") and path.endswith("/run"):
        rid = path.split("/")[-2]
        job = jobs.enqueue("rule_run", {"rule_id": rid})
        _json(handler, {"ok": True, "job": job})
        return True

    if path.startswith("/api/archive/rules/") and path.endswith("/delete"):
        rid = path.split("/")[-2]
        _json(handler, {"ok": True, "deleted": store.delete_rule(rid)})
        return True

    if path == "/api/archive/pipeline/handoff":
        result = pipeline.handoff(
            data.get("asset_ids") or data.get("ids") or [],
            concept=data.get("concept") or "",
            collection_id=data.get("collection_id"),
            download_missing=bool(data.get("download_missing", True)),
        )
        status = 200 if result.get("ok") else 400
        _json(handler, result, status)
        return True

    if path == "/api/archive/drive/sync":
        job = jobs.enqueue(
            "drive_sync",
            {
                "asset_ids": data.get("asset_ids") or data.get("ids") or [],
                "folder_kind": data.get("folder_kind") or "source_archive",
                "collection_name": data.get("collection_name") or "",
            },
        )
        _json(handler, {"ok": True, "job": job})
        return True

    return False
