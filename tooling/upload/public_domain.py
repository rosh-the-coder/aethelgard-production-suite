"""Public-domain art search + download (Met Museum Open Access).

Only returns objects marked isPublicDomain=true by The Met.
Users remain responsible for verifying license for commercial Etsy use.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

import requests

MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}"
UA = {"User-Agent": "AethelgardArtCo/1.2 (local production tool; public-domain research)"}


def search_met(query, limit=24):
    """Search Met Open Access collection. Returns list of card dicts."""
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 24), 48))
    r = requests.get(
        MET_SEARCH,
        params={"q": q, "isPublicDomain": "true", "hasImages": "true"},
        headers=UA,
        timeout=45,
    )
    r.raise_for_status()
    ids = (r.json() or {}).get("objectIDs") or []
    out = []
    for oid in ids[: limit * 3]:  # oversample; some lack primaryImage
        try:
            card = fetch_met_object(oid)
        except Exception:
            continue
        if not card or not card.get("image"):
            continue
        out.append(card)
        if len(out) >= limit:
            break
        time.sleep(0.05)  # be polite to Met API
    return out


def fetch_met_object(oid):
    r = requests.get(MET_OBJECT.format(oid=oid), headers=UA, timeout=30)
    if r.status_code != 200:
        return None
    o = r.json() or {}
    if not o.get("isPublicDomain"):
        return None
    image = o.get("primaryImage") or o.get("primaryImageSmall") or ""
    if not image:
        return None
    return {
        "source": "met",
        "object_id": str(o.get("objectID") or oid),
        "title": o.get("title") or f"Met object {oid}",
        "artist": o.get("artistDisplayName") or o.get("culture") or "Unknown",
        "date": o.get("objectDate") or "",
        "department": o.get("department") or "",
        "medium": o.get("medium") or "",
        "credit": o.get("creditLine") or "",
        "rights": "Public Domain (Met Open Access)",
        "object_url": o.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{oid}",
        "image": image,
        "image_small": o.get("primaryImageSmall") or image,
    }


def download_image(url, dest_path):
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    data = r.content
    if not data or len(data) < 200:
        raise RuntimeError("Downloaded image is empty/tiny")
    # Normalize to PNG via Pillow when possible
    try:
        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.save(dest_path, format="PNG", optimize=True)
    except Exception:
        with open(dest_path, "wb") as f:
            f.write(data)
    return dest_path


def import_objects_to_run(objects, runs_dir, concept="public domain vintage"):
    """Download selected PD objects into a new artwork run _candidates folder."""
    slug = re.sub(r"[^a-z0-9]+", "_", (concept or "public_domain").strip().lower()).strip("_") or "public_domain"
    run_dir = os.path.join(runs_dir, slug)
    counter = 1
    while os.path.exists(run_dir):
        run_dir = os.path.join(runs_dir, f"{slug}_{counter}")
        counter += 1
    candidates_dir = os.path.join(run_dir, "_candidates")
    os.makedirs(candidates_dir, exist_ok=True)

    candidates = []
    errors = []
    for i, obj in enumerate(objects):
        try:
            oid = obj.get("object_id") or obj.get("objectID") or f"item{i}"
            img_url = obj.get("image") or obj.get("primaryImage")
            if not img_url:
                # refresh from Met if only id given
                if obj.get("object_id") or obj.get("objectID"):
                    refreshed = fetch_met_object(obj.get("object_id") or obj.get("objectID"))
                    if refreshed:
                        obj = refreshed
                        img_url = obj.get("image")
            if not img_url:
                errors.append({"object_id": oid, "error": "No image URL"})
                continue
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            label = f"pd-{oid}"
            dest = os.path.join(candidates_dir, f"{ts}_{label}-{i}.png")
            download_image(img_url, dest)
            # sidecar attribution
            meta_path = dest + ".json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)
            rel = dest  # caller relativizes
            candidates.append({
                "label": label,
                "path": dest.replace("\\", "/"),
                "rel_path": None,  # filled by server
                "prompt": f"Public domain import: {obj.get('title')} — {obj.get('artist')} ({obj.get('rights')})",
                "model": "public-domain-met",
                "aspect": "4:5",
                "attribution": obj,
            })
        except Exception as e:
            errors.append({"object_id": obj.get("object_id"), "error": str(e)})

    manifest = {
        "source": "met_open_access",
        "concept": concept,
        "imported_at": datetime.now().isoformat(),
        "count": len(candidates),
        "note": "Verify Open Access / public-domain status before commercial Etsy use.",
    }
    with open(os.path.join(run_dir, "public_domain_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return run_dir, candidates, errors
