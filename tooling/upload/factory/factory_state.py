"""Derived Factory Dashboard aggregate — single projection of product + job state."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from . import job_store
from . import quota
from .audit import read_audit
from .paths import RUNS_DIR


def _upload_status(piece: Dict[str, Any]) -> str:
    st = piece.get("upload_status")
    if not st:
        return ""
    if isinstance(st, str):
        return st.lower()
    return str(st.get("status") or "").lower()


def derive_status(piece: Dict[str, Any]) -> str:
    st = _upload_status(piece)
    if st in ("failed", "error"):
        return "error"
    if st in ("done", "uploaded", "success", "succeeded", "draft") or piece.get("uploaded_at"):
        return "draft"
    if piece.get("stale_artifacts"):
        return "stale"
    if piece.get("has_pdf") and (piece.get("mockups") or []) and piece.get("seo_title"):
        return "pending_review"
    if piece.get("master_image") or piece.get("master_preview"):
        mocks = piece.get("mockups") or []
        if not mocks or not piece.get("has_pdf") or not piece.get("seo_title"):
            return "in_progress"
    return "queue"


def stage_of(piece: Dict[str, Any]) -> str:
    if derive_status(piece) == "draft":
        return "Etsy draft"
    if piece.get("has_pdf") and (piece.get("mockups") or []) and piece.get("seo_title"):
        return "Review"
    if piece.get("seo_title") and (piece.get("mockups") or []):
        return "Package"
    if piece.get("mockups"):
        return "Mockups"
    if (piece.get("print_jpg_count") or 0) > 0:
        return "Print"
    if piece.get("master_image") or piece.get("master_preview"):
        return "Master"
    return "Acquire"


def flatten_pieces(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat = []
    for run_idx, run in enumerate(runs or []):
        for piece_idx, piece in enumerate(run.get("pieces") or []):
            item = dict(piece)
            item["runIdx"] = run_idx
            item["pieceIdx"] = piece_idx
            item["run_name"] = piece.get("run_name") or run.get("name") or ""
            flat.append(item)
    flat.sort(key=lambda p: p.get("mtime") or 0, reverse=True)
    return flat


def build_dashboard(
    *,
    scan_runs: Callable[[], List[Dict[str, Any]]],
    preflight: Optional[Dict[str, Any]] = None,
    auth: Optional[Dict[str, Any]] = None,
    etsy_api: Optional[Dict[str, Any]] = None,
    research_count: Optional[int] = None,
) -> Dict[str, Any]:
    job_store.ensure_init()
    runs = scan_runs() or []
    pieces = flatten_pieces(runs)
    q = quota.snapshot()

    drafts = errors = review = stale = 0
    with_mockups = with_master = with_seo = with_prints = with_pdf = 0
    total_mockups = total_prints = 0
    for p in pieces:
        status = derive_status(p)
        if status == "draft":
            drafts += 1
        if status == "error":
            errors += 1
        if status == "pending_review":
            review += 1
        if status == "stale":
            stale += 1
        if p.get("mockups"):
            with_mockups += 1
            total_mockups += len(p.get("mockups") or [])
        if p.get("master_image") or p.get("master_preview"):
            with_master += 1
        if p.get("seo_title"):
            with_seo += 1
        if (p.get("print_jpg_count") or 0) > 0:
            with_prints += 1
            total_prints += int(p.get("print_jpg_count") or 0)
        if p.get("has_pdf"):
            with_pdf += 1

    # Batch / job overlays
    batches = job_store.list_batches(limit=20)
    active_batch = None
    for b in batches:
        if b.get("status") in ("processing", "awaiting_attention", "validated", "queued"):
            active_batch = job_store.recompute_batch_progress(b["id"])
            break
    if active_batch is None and batches:
        active_batch = job_store.recompute_batch_progress(batches[0]["id"])

    jobs = job_store.list_jobs(limit=200)
    selection_needed = sum(
        1 for j in jobs if j.get("current_stage") == "awaiting_selection" or j.get("status") == "awaiting_selection"
    )
    batch_failed = sum(1 for j in jobs if j.get("status") == "failed")

    attention_parts = []
    if review:
        attention_parts.append(f"{review} product{'s' if review != 1 else ''} need review")
    if errors or batch_failed:
        n = errors + batch_failed
        attention_parts.append(f"{n} failed job{'s' if n != 1 else ''}")
    if drafts and not review:
        attention_parts.append(f"{drafts} draft{'s' if drafts != 1 else ''} waiting")
    if selection_needed:
        attention_parts.append(f"{selection_needed} manual selection{'s' if selection_needed != 1 else ''} required")
    if stale:
        attention_parts.append(f"{stale} stale artifact set{'s' if stale != 1 else ''}")

    queue = sum(1 for p in pieces if derive_status(p) not in ("draft",))

    pipeline = [
        {"id": "research", "name": "Research", "count": research_count, "status": "saved" if research_count else "idle"},
        {"id": "acquire", "name": "Acquire", "count": len(pieces), "status": "active" if pieces else "idle"},
        {"id": "select", "name": "Select", "count": with_master, "status": "active" if with_master else "idle"},
        {"id": "master", "name": "Master", "count": with_master, "status": "ready" if with_master else "idle", "tone": "ok"},
        {"id": "print", "name": "Print", "count": with_prints, "status": "ready" if with_prints else "idle"},
        {"id": "mockups", "name": "Mockups", "count": with_mockups, "status": "ready" if with_mockups else "idle"},
        {"id": "seo", "name": "SEO", "count": with_seo, "status": "ready" if with_seo else "idle"},
        {"id": "package", "name": "Package", "count": with_pdf, "status": "ready" if with_pdf else "idle"},
        {"id": "draft", "name": "Etsy draft", "count": drafts, "status": "waiting" if drafts else "idle", "tone": "ok" if drafts else ""},
        {
            "id": "review",
            "name": "Review",
            "count": review + selection_needed,
            "status": "needs human" if (review or selection_needed) else "clear",
            "tone": "warn" if (review or selection_needed) else "ok",
        },
    ]

    # Activity: merge product mtimes + audit + job updates
    activity = []
    for p in pieces[:12]:
        status = derive_status(p)
        title = p.get("title") or p.get("slug") or "Untitled"
        activity.append(
            {
                "text": f"{stage_of(p)} — {title}",
                "sub": p.get("run_name") or "",
                "time": p.get("mtime") or 0,
                "mark": "warn" if status in ("pending_review", "stale", "error") else "ok",
                "kind": "product",
            }
        )
    for entry in read_audit(limit=20):
        activity.append(
            {
                "text": entry.get("action", "event"),
                "sub": entry.get("batch_id") or entry.get("iso") or "",
                "time": entry.get("ts") or 0,
                "mark": "err" if "fail" in str(entry.get("action")) else "ok",
                "kind": "audit",
            }
        )
    activity.sort(key=lambda a: a.get("time") or 0, reverse=True)

    return {
        "generated_at": time.time(),
        "attention": " · ".join(attention_parts) if attention_parts else "",
        "kpis": {
            "products": len(pieces),
            "queue": queue,
            "drafts": drafts,
            "review": review,
            "errors": errors + batch_failed,
            "stale": stale,
            "selection_needed": selection_needed,
        },
        "quota": q,
        "pipeline": pipeline,
        "pieces": pieces,
        "active_batch": {
            "id": active_batch.get("id") if active_batch else None,
            "progress": (active_batch or {}).get("progress"),
            "status": (active_batch or {}).get("status"),
            "dry_run": (active_batch or {}).get("dry_run"),
        }
        if active_batch
        else None,
        "batches": [
            {
                "id": b["id"],
                "status": b.get("status"),
                "created_at": b.get("created_at"),
                "artwork_total": b.get("artwork_total"),
                "completed_artworks": b.get("completed_artworks"),
                "failed_artworks": b.get("failed_artworks"),
                "etsy_drafts": b.get("etsy_drafts"),
                "dry_run": b.get("dry_run"),
            }
            for b in batches[:10]
        ],
        "stats": {
            "runs": len(pieces),
            "mockups": total_mockups,
            "prints": total_prints,
            "pdfs": with_pdf,
            "drafts": drafts,
        },
        "preflight": preflight or {},
        "auth": auth or {},
        "etsy_api": etsy_api or {},
        "activity": activity[:20],
        "quick_actions": _quick_actions(active_batch, review, batch_failed),
    }


def _quick_actions(active_batch, review, batch_failed) -> List[Dict[str, str]]:
    actions = [
        {"id": "newProduct", "label": "New Product", "primary": True},
        {"id": "uploadBatch", "label": "Upload Batch"},
        {"id": "downloadTemplate", "label": "Download Template"},
    ]
    if active_batch and active_batch.get("status") in ("processing", "awaiting_attention", "partial"):
        actions.append({"id": "reviewBatch", "label": "Review Batch"})
    if batch_failed:
        actions.append({"id": "retryFailed", "label": "Retry Failed Items"})
    actions.extend(
        [
            {"id": "continueDraft", "label": "Continue Draft"},
            {"id": "research", "label": "Research Niche"},
            {"id": "mockups", "label": "Generate Mockups"},
            {"id": "openDraft", "label": "Open Etsy Draft"},
        ]
    )
    return actions
