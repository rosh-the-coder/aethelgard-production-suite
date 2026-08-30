"""Handoff Archive Studio assets into the existing Artwork Studio PD import path.

Uses public_domain.import_objects_to_run so mockup / SEO / listing / Drive
packaging stay on the current production pipeline.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from . import download, store
from .log import log_event
from .paths import RUNS_DIR


def assets_to_import_objects(assets: Sequence[dict]) -> List[dict]:
    objects = []
    for asset in assets:
        image = asset.get("local_file_path") or asset.get("source_image_url") or asset.get("thumbnail_url")
        objects.append(
            {
                "source": asset.get("source"),
                "object_id": asset.get("source_object_id") or asset.get("id"),
                "title": asset.get("title"),
                "artist": asset.get("artist"),
                "date": asset.get("date_display") or asset.get("year"),
                "medium": asset.get("medium"),
                "rights": asset.get("licence_type") or asset.get("rights_status"),
                "object_url": asset.get("source_url"),
                "image": image,
                "image_small": asset.get("thumbnail_url") or image,
                "tags": asset.get("tags") or [],
                "archive_asset_id": asset.get("id"),
                "is_public_domain": asset.get("is_public_domain"),
            }
        )
    return objects


def handoff(
    asset_ids: Sequence[str],
    *,
    concept: str = "",
    collection_id: Optional[str] = None,
    download_missing: bool = True,
) -> Dict:
    ids = [str(a) for a in asset_ids if a]
    if collection_id and not ids:
        page = store.list_assets(collection_id=collection_id, limit=200, offset=0)
        ids = [a["id"] for a in page.get("items") or []]
    assets = []
    errors = []
    for aid in ids:
        asset = store.get_asset(aid)
        if not asset:
            errors.append({"id": aid, "error": "not found"})
            continue
        if download_missing and not (asset.get("local_file_path") and os.path.isfile(asset.get("local_file_path") or "")):
            result = download.download_fullres(aid)
            if not result.get("ok"):
                errors.append({"id": aid, "error": result.get("error")})
                continue
            asset = store.get_asset(aid)
        assets.append(asset)
    if not assets:
        return {"ok": False, "error": "No assets ready for listing pipeline.", "errors": errors}

    name = (concept or "").strip()
    if not name and collection_id:
        col = store.get_collection(collection_id)
        name = (col or {}).get("name") or ""
    if not name:
        name = assets[0].get("theme") or assets[0].get("title") or "archive pack"

    from public_domain import import_objects_to_run

    objects = assets_to_import_objects(assets)
    run_dir, candidates, import_errors, manifest = import_objects_to_run(
        objects, RUNS_DIR, concept=name, trim_borders=True
    )
    for asset in assets:
        store.update_asset(
            asset["id"],
            listing_status="handed_off",
            processing_status=asset.get("processing_status") or "fullres_ready",
            extra={**(asset.get("extra") or {}), "run_dir": run_dir},
        )
    log_event(
        "pipeline.handoff",
        message=name,
        run_dir=run_dir,
        count=len(candidates),
        failed=len(import_errors or []),
    )
    pack_title = name.title() if name else "Vintage Print Pack"
    return {
        "ok": bool(candidates),
        "product_type": "pd_bundle",
        "pack_title": pack_title,
        "run_dir": (run_dir or "").replace("\\", "/"),
        "candidates": candidates,
        "manifest": manifest,
        "errors": (errors or []) + (import_errors or []),
        "suggested_titles": [
            f"{pack_title} — {len(candidates)}+ Vintage Digital Prints Bundle",
            f"{pack_title} Gallery Wall Set, Printable Public Domain Art Pack",
            f"Vintage Art Bundle ({len(candidates)} Prints), Eclectic Gallery Wall Download",
        ],
    }
