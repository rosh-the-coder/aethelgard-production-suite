"""Artifact dependency invalidation for editable products."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Set

# What becomes stale when an upstream artifact changes
INVALIDATION_MAP = {
    "artwork": ["master", "prints", "mockups", "delivery_pdf", "etsy_draft"],
    "master": ["prints", "mockups", "delivery_pdf", "etsy_draft"],
    "prints": ["delivery_pdf", "etsy_draft"],
    "mockups": ["etsy_draft"],
    "seo": ["etsy_draft"],
    "package": ["etsy_draft"],
}


def stale_path(piece_dir: str) -> str:
    return os.path.join(piece_dir, "stale_artifacts.json")


def load_stale(piece_dir: str) -> Dict[str, Any]:
    path = stale_path(piece_dir)
    if not os.path.isfile(path):
        return {"stale": [], "updated_at": None, "reason": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stale": [], "updated_at": None, "reason": None}


def mark_stale(piece_dir: str, changed: str, reason: str = "") -> Dict[str, Any]:
    targets: Set[str] = set(INVALIDATION_MAP.get(changed, []))
    data = load_stale(piece_dir)
    stale = set(data.get("stale") or [])
    stale |= targets
    payload = {
        "stale": sorted(stale),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": reason or f"{changed} changed",
        "changed": changed,
        "rebuild_required": sorted(stale),
    }
    path = stale_path(piece_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    # also stamp meta
    meta_path = os.path.join(piece_dir, "meta.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["stale_artifacts"] = payload["stale"]
            meta["stale_reason"] = payload["reason"]
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass
    return payload


def clear_stale(piece_dir: str, rebuilt: List[str]) -> Dict[str, Any]:
    data = load_stale(piece_dir)
    stale = [s for s in (data.get("stale") or []) if s not in set(rebuilt)]
    payload = {
        "stale": stale,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": data.get("reason"),
        "rebuild_required": stale,
    }
    with open(stale_path(piece_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload
