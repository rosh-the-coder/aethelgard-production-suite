"""Etsy draft history + resubmission records (local, never auto-publish)."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


def history_path(piece_dir: str) -> str:
    return os.path.join(piece_dir, "etsy_draft_history.json")


def load_history(piece_dir: str) -> Dict[str, Any]:
    path = history_path(piece_dir)
    if not os.path.isfile(path):
        return {"drafts": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"drafts": []}
        data.setdefault("drafts", [])
        return data
    except Exception:
        return {"drafts": []}


def save_history(piece_dir: str, data: Dict[str, Any]) -> None:
    path = history_path(piece_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def record_draft(
    piece_dir: str,
    *,
    draft_id: str,
    batch_id: str = "",
    product_id: str = "",
    uploaded_files: Optional[List[str]] = None,
    status: str = "draft",
    replaces_draft_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    data = load_history(piece_dir)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if replaces_draft_id:
        for d in data["drafts"]:
            if str(d.get("draft_id")) == str(replaces_draft_id):
                d["status"] = "superseded"
                d["superseded_at"] = now
                d["replaced_by"] = draft_id
    entry = {
        "draft_id": str(draft_id),
        "created_at": now,
        "batch_id": batch_id,
        "product_id": product_id or os.path.basename(piece_dir),
        "uploaded_files": uploaded_files or [],
        "status": status,
        "replaces_draft_id": replaces_draft_id,
        "dry_run": bool(dry_run),
        "publish": False,
    }
    data["drafts"].append(entry)
    data["current_draft_id"] = str(draft_id)
    save_history(piece_dir, data)
    return entry


def current_draft_id(piece_dir: str) -> Optional[str]:
    data = load_history(piece_dir)
    return data.get("current_draft_id")
