"""Google Drive sync for Archive Studio using existing drive_delivery helpers."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from . import store
from .log import log_event
from .paths import DEFAULT_DRIVE_FOLDERS


def _service():
    try:
        import drive_delivery
    except Exception as e:
        raise RuntimeError(f"drive_delivery unavailable: {e}") from e
    if not drive_delivery.status().get("connected"):
        raise RuntimeError("Google Drive is not connected. Use Connect Google Drive in the top bar.")
    return drive_delivery.get_service(), drive_delivery


def _ensure_path(service, drive_delivery, root_id: str, rel_path: str) -> str:
    current = root_id
    parts = [p for p in (rel_path or "").replace("\\", "/").split("/") if p]
    for part in parts:
        current = drive_delivery.ensure_folder(service, current, part)
    return current


def folder_plan(asset: dict, *, kind: str = "source_archive", collection_name: str = "") -> str:
    settings = store.load_settings()
    folders = settings.get("drive_folders") or DEFAULT_DRIVE_FOLDERS
    base = folders.get(kind) or folders.get("source_archive") or "Aethelgard/Source Archive"
    theme = collection_name or asset.get("theme") or "unsorted"
    source = asset.get("source") or "unknown"
    return f"{base}/{source}/{theme}"


def sync_asset(asset_id: str, *, kind: str = "source_archive", collection_name: str = "") -> dict:
    asset = store.get_asset(asset_id)
    if not asset:
        return {"ok": False, "error": "asset not found"}
    local = asset.get("local_file_path") or asset.get("local_thumb_path")
    if not local or not os.path.isfile(local):
        return {"ok": False, "error": "no local file — download full-res first"}
    try:
        service, drive_delivery = _service()
        status = drive_delivery.status()
        root_id = status.get("root_folder_id") or drive_delivery.DEFAULT_ROOT_FOLDER_ID
        rel = folder_plan(asset, kind=kind, collection_name=collection_name)
        parent = _ensure_path(service, drive_delivery, root_id, rel)
        fname = os.path.basename(local)
        file_id = drive_delivery.upload_file(service, local, parent, name=fname)
        drive_path = f"{rel}/{fname}"
        store.update_asset(
            asset_id,
            drive_path=drive_path,
            drive_file_id=file_id,
            drive_status="synced",
        )
        log_event("drive.synced", asset_id=asset_id, message=drive_path, file_id=file_id)
        return {"ok": True, "drive_path": drive_path, "file_id": file_id}
    except Exception as e:
        store.update_asset(asset_id, drive_status="failed")
        log_event("drive.failed", level="error", asset_id=asset_id, message=str(e))
        return {"ok": False, "error": str(e)}


def sync_many(asset_ids: List[str], *, kind: str = "source_archive", collection_name: str = "") -> dict:
    ok = 0
    failed = []
    for aid in asset_ids:
        result = sync_asset(aid, kind=kind, collection_name=collection_name)
        if result.get("ok"):
            ok += 1
        else:
            failed.append({"id": aid, "error": result.get("error")})
    return {"ok_count": ok, "failed": failed, "total": len(asset_ids)}
