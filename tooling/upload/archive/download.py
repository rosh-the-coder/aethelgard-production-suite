"""Selective thumbnail + full-resolution downloads with local cache."""
from __future__ import annotations

import os
from typing import Optional, Tuple
from urllib.parse import urlparse

from . import dedupe, qc, store
from .http_util import get_bytes
from .log import log_event
from .paths import FILES_DIR, THUMBS_DIR, ensure_archive_dirs, resolve_under
from .schema import classify_orientation


def _ext_for(mime: str, url: str) -> str:
    mime = (mime or "").lower()
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    if "tiff" in mime or "tif" in mime:
        return ".tif"
    path = urlparse(url or "").path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def _safe_stem(asset: dict) -> str:
    raw = f"{asset.get('source')}-{asset.get('source_object_id')}"
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in raw)[:80].strip("-") or asset["id"]


def _image_size(path: str) -> Tuple[Optional[int], Optional[int]]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return None, None


def download_thumbnail(asset_id: str) -> dict:
    ensure_archive_dirs()
    asset = store.get_asset(asset_id)
    if not asset:
        return {"ok": False, "error": "asset not found"}
    url = asset.get("thumbnail_url") or asset.get("source_image_url")
    if not url:
        return {"ok": False, "error": "no thumbnail url"}
    existing = asset.get("local_thumb_path")
    if existing and os.path.isfile(existing):
        return {"ok": True, "path": existing, "cached": True}
    data, mime, err = get_bytes(url, source=asset.get("source") or "default", timeout=25)
    if err or not data:
        log_event("download.thumb_failed", level="error", asset_id=asset_id, source=asset.get("source"), message=err or "empty")
        return {"ok": False, "error": err or "empty download"}
    ext = _ext_for(mime, url)
    dest = resolve_under(THUMBS_DIR, _safe_stem(asset) + ext)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    try:
        phash = dedupe.average_hash(data)
        store.update_asset(asset_id, local_thumb_path=dest, perceptual_hash=phash, processing_status="thumb_cached")
    except Exception:
        store.update_asset(asset_id, local_thumb_path=dest, processing_status="thumb_cached")
    return {"ok": True, "path": dest, "bytes": len(data)}


def download_fullres(asset_id: str, *, force: bool = False) -> dict:
    ensure_archive_dirs()
    asset = store.get_asset(asset_id)
    if not asset:
        return {"ok": False, "error": "asset not found"}
    existing = asset.get("local_file_path")
    if existing and os.path.isfile(existing) and not force:
        return {"ok": True, "path": existing, "cached": True}
    url = asset.get("source_image_url")
    if not url:
        flags = list(asset.get("qc_flags") or [])
        if "missing_image" not in flags:
            flags.append("missing_image")
        store.update_asset(asset_id, qc_flags=flags)
        return {"ok": False, "error": "no source image url"}
    data, mime, err = get_bytes(url, source=asset.get("source") or "default", timeout=90)
    if err or not data:
        flags = list(asset.get("qc_flags") or [])
        if "corrupted_download" not in flags:
            flags.append("corrupted_download")
        store.update_asset(asset_id, qc_flags=flags)
        log_event("download.fullres_failed", level="error", asset_id=asset_id, source=asset.get("source"), message=err or "empty")
        return {"ok": False, "error": err or "empty download"}
    ext = _ext_for(mime, url)
    dest_dir = resolve_under(FILES_DIR, asset.get("source") or "misc")
    os.makedirs(dest_dir, exist_ok=True)
    dest = resolve_under(dest_dir, _safe_stem(asset) + ext)
    with open(dest, "wb") as f:
        f.write(data)
    width, height = _image_size(dest)
    hashes = dedupe.apply_hashes(asset_id, data)
    settings = store.load_settings()
    orientation = classify_orientation(width, height)
    flags = qc.evaluate(
        {
            **asset,
            "local_file_path": dest,
            "width": width,
            "height": height,
            "orientation": orientation,
            "file_sha256": hashes.get("file_sha256"),
        },
        min_width=int(settings.get("min_width") or 1200),
        min_height=int(settings.get("min_height") or 1200),
    )
    dups = dedupe.find_duplicates({**asset, **hashes, "id": asset_id})
    duplicate_of = ""
    if dups and not asset.get("allow_duplicate"):
        flags = list(dict.fromkeys(flags + ["possible_duplicate"]))
        duplicate_of = dups[0].get("id") or ""
    status = "qc_flagged" if flags else "fullres_ready"
    store.update_asset(
        asset_id,
        local_file_path=dest,
        width=width,
        height=height,
        orientation=orientation,
        qc_flags=flags,
        duplicate_of=duplicate_of or None,
        processing_status=status,
    )
    log_event(
        "download.fullres_ok",
        asset_id=asset_id,
        source=asset.get("source"),
        message=os.path.basename(dest),
        bytes=len(data),
        flags=flags,
    )
    return {
        "ok": True,
        "path": dest,
        "bytes": len(data),
        "width": width,
        "height": height,
        "qc_flags": flags,
        "duplicates": [{"id": d.get("id"), "match": d.get("match")} for d in dups[:5]],
    }


def local_preview_path(asset: dict) -> Optional[str]:
    for key in ("local_thumb_path", "local_file_path"):
        path = asset.get(key)
        if path and os.path.isfile(path):
            return path
    return None
