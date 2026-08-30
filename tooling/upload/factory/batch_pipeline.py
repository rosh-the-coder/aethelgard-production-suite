"""Per-artwork batch pipeline stages (dry-run + optional live hooks)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

from . import draft_history
from . import events
from . import job_store
from .audit import audit
from .paths import ROOT_DIR, RUNS_DIR, UPLOAD_DIR, ensure_factory_dirs


PIPELINE_STAGES = [
    ("validating", "Validating"),
    ("acquiring", "Acquiring artwork"),
    ("normalising", "Normalising"),
    ("awaiting_selection", "Selection"),
    ("preparing_master", "Preparing master"),
    ("creating_prints", "Creating prints"),
    ("creating_mockups", "Creating mockups"),
    ("generating_seo", "Generating SEO"),
    ("packaging", "Packaging"),
    ("creating_etsy_draft", "Creating Etsy draft"),
    ("awaiting_review", "Awaiting review"),
    ("complete", "Complete"),
]


def _slug(s: str) -> str:
    out = []
    for ch in (s or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in "-_ " and (not out or out[-1] != "-"):
            out.append("-")
    return "".join(out).strip("-")[:60] or "piece"


def _write_placeholder_image(path: str, label: str, size=(800, 1000), tint=(40, 36, 30)) -> None:
    img = Image.new("RGB", size, tint)
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, size[0] - 40, size[1] - 40], outline=(197, 168, 128), width=4)
    text = f"DRY-RUN\n{label}"
    draw.multiline_text((60, size[1] // 2 - 40), text, fill=(239, 236, 230), spacing=8)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")


def process_job(job: Dict[str, Any], *, suite_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run one artwork job through the pipeline. Dry-run creates marked placeholders."""
    ensure_factory_dirs()
    job_id = job["id"]
    batch_id = job["batch_id"]
    row = job.get("row") or {}
    dry_run = False
    batch = job_store.get_batch(batch_id) or {}
    dry_run = bool(batch.get("dry_run"))
    meta = batch.get("meta") or {}
    if meta.get("dry_run"):
        dry_run = True

    total = len(PIPELINE_STAGES)
    listing_id = job.get("listing_id") or row.get("listing_id") or "listing"
    artwork_id = job.get("artwork_id") or row.get("artwork_id") or job_id[:8]
    count = int(row.get("artwork_count") or 1)
    policy = (row.get("selection_policy") or "first_success").lower()

    run_name = _slug(f"batch_{batch_id}_{listing_id}")
    if dry_run:
        run_name = _slug(f"dryrun_{batch_id}_{listing_id}")
    run_dir = os.path.join(RUNS_DIR, run_name)
    piece_slug = _slug(f"{artwork_id}")
    piece_dir = os.path.join(run_dir, piece_slug)

    def set_stage(stage: str, message: str, unit_index: int) -> None:
        pct = round(100.0 * unit_index / total, 1)
        status = "running"
        if stage == "awaiting_selection":
            status = "awaiting_selection"
        elif stage == "awaiting_review":
            status = "awaiting_review"
        elif stage == "complete":
            status = "complete"
        elif stage == "failed":
            status = "failed"
        job_store.update_job(
            job_id,
            status=status,
            current_stage=stage,
            completed_units=unit_index,
            total_units=total,
            percentage=pct,
            message=message,
            piece_path=piece_dir if os.path.isdir(piece_dir) else None,
            run_name=run_name,
            completed_at=time.time() if stage in ("complete", "failed") else None,
        )
        events.publish(
            "job.progress",
            {
                "job_id": job_id,
                "batch_id": batch_id,
                "stage": stage,
                "percentage": pct,
                "message": message,
            },
        )
        events.invalidate("job.progress", batch_id=batch_id)
        job_store.recompute_batch_progress(batch_id)
        events.publish("batch.progress", {"batch_id": batch_id})

    try:
        for i, (stage, label) in enumerate(PIPELINE_STAGES, start=1):
            if stage == "awaiting_selection":
                if count > 1 and policy == "manual_review":
                    set_stage(stage, "Paused for human selection", i)
                    audit("job.selection_required", job_id=job_id, batch_id=batch_id)
                    events.publish("review.required", {"job_id": job_id, "batch_id": batch_id})
                    return job_store.get_job(job_id)
                # first_success / single: continue
                set_stage(stage, "Auto-selected first success", i)
                time.sleep(0.05)
                continue

            set_stage(stage, label, i)

            if stage == "acquiring":
                os.makedirs(piece_dir, exist_ok=True)
                master = os.path.join(piece_dir, "master.png")
                if dry_run:
                    _write_placeholder_image(
                        master,
                        f"{row.get('concept') or artwork_id}"[:48],
                    )
                else:
                    set_stage(stage, "Calling image provider…", i)
                    _try_live_acquire(row, piece_dir, master)
                    if not os.path.isfile(master):
                        raise RuntimeError("Live generation finished but master.png is missing")
                    set_stage(stage, "Artwork acquired", i)

            elif stage == "normalising":
                # Ensure master exists
                master = os.path.join(piece_dir, "master.png")
                if not os.path.isfile(master):
                    raise RuntimeError("Master missing after acquire")

            elif stage == "preparing_master":
                listing_product_type = _map_product_type(row.get("product_type"))
                is_bundle_member = listing_product_type in ("bundle", "pd_bundle")
                # Bundle members are components only — Catalog shows one assembled listing later.
                meta = {
                    "title": row.get("artwork_title") or row.get("listing_title") or row.get("listing_name") or artwork_id,
                    "slug": piece_slug,
                    "product_type": "print" if is_bundle_member else listing_product_type,
                    "listing_product_type": listing_product_type if is_bundle_member else None,
                    "batch_role": "bundle_member" if is_bundle_member else "listing",
                    "exclude_from_catalog": bool(is_bundle_member),
                    "product_kind": "graphic_poster" if row.get("acquisition_mode") == "graphic_poster" else None,
                    "orientation": row.get("orientation") or "portrait",
                    "aspect": row.get("aspect_ratio") or "4:5",
                    "batch_id": batch_id,
                    "listing_id": listing_id,
                    "artwork_id": artwork_id,
                    "dry_run": dry_run,
                    "price": row.get("price_eur") or ((suite_settings or {}).get("prices") or {}).get(
                        "bundle" if is_bundle_member else "single", 2.99
                    ),
                    "quantity": (suite_settings or {}).get("default_quantity", 999),
                    "prompt": row.get("concept") or "",
                    "seo": {},
                    "quality_warnings": ["DRY-RUN TEST DATA — not a real artwork"] if dry_run else [],
                }
                with open(os.path.join(piece_dir, "meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                events.publish("product.created", {"piece_path": piece_dir, "batch_id": batch_id})

            elif stage == "creating_prints":
                from print_exports import export_print_set

                prints_dir = os.path.join(piece_dir, "prints")
                labels = export_print_set(
                    os.path.join(piece_dir, "master.png"),
                    prints_dir,
                    piece_slug,
                    orientation=row.get("orientation") or "portrait",
                    aspect=row.get("aspect_ratio") or "4:5",
                    dry_run=dry_run,
                )
                meta_path = os.path.join(piece_dir, "meta.json")
                if os.path.isfile(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    from print_exports import PRINT_PACK_VERSION, ETSY_RATIO_PACK, ratio_size_summary

                    meta["sizes"] = labels
                    meta["print_dpi"] = 300
                    meta["print_pack"] = PRINT_PACK_VERSION
                    meta["print_ratios"] = list(ETSY_RATIO_PACK.keys())
                    meta["sizes_summary"] = ratio_size_summary(
                        row.get("orientation") or "portrait"
                    )
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta, f, indent=2)

            elif stage == "creating_mockups":
                mock = os.path.join(piece_dir, "mockup_dryrun_frame.jpg")
                img = Image.open(os.path.join(piece_dir, "master.png")).convert("RGB")
                canvas = Image.new("RGB", (1200, 900), (30, 28, 26))
                img = img.resize((420, 525))
                canvas.paste(img, (390, 180))
                draw = ImageDraw.Draw(canvas)
                draw.text((40, 40), "DRY-RUN MOCKUP" if dry_run else "BATCH MOCKUP", fill=(197, 168, 128))
                canvas.save(mock, "JPEG", quality=90)

            elif stage == "generating_seo":
                title = row.get("listing_title") or row.get("listing_name") or artwork_id
                tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()][:13]
                listing = {
                    "title": title[:140],
                    "tags": tags,
                    "description": (row.get("description_notes") or row.get("concept") or title)[:500],
                    "materials": ["digital download"],
                }
                with open(os.path.join(piece_dir, "listing.json"), "w", encoding="utf-8") as f:
                    json.dump(listing, f, indent=2)
                meta_path = os.path.join(piece_dir, "meta.json")
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["seo"] = listing
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)

            elif stage == "packaging":
                # Minimal delivery marker PDF-like text file + flag
                pdf_marker = os.path.join(piece_dir, "Download_Links.pdf")
                # Write a tiny valid-enough placeholder file (not a real PDF parser needed)
                with open(pdf_marker, "wb") as f:
                    f.write(b"%PDF-1.1\n% Aethelgard dry-run package\ntrailer\n%%EOF\n")
                with open(meta_path := os.path.join(piece_dir, "meta.json"), "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["pdf_path"] = pdf_marker
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)

            elif stage == "creating_etsy_draft":
                listing_product_type = _map_product_type(row.get("product_type"))
                if listing_product_type in ("bundle", "pd_bundle"):
                    # One Etsy draft per listing — created when the bundle is assembled.
                    status = {
                        "status": "deferred",
                        "message": "Bundle member — Etsy draft waits for full set assembly",
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "piece_dir": piece_dir.replace("\\", "/"),
                        "dry_run": dry_run,
                        "publish": False,
                    }
                    with open(os.path.join(piece_dir, "upload_status.json"), "w", encoding="utf-8") as f:
                        json.dump(status, f, indent=2)
                else:
                    prev = draft_history.current_draft_id(piece_dir)
                    draft_id = f"{'dryrun-' if dry_run else 'draft-'}{batch_id}-{artwork_id}"
                    draft_history.record_draft(
                        piece_dir,
                        draft_id=draft_id,
                        batch_id=batch_id,
                        product_id=piece_slug,
                        uploaded_files=["master.png"],
                        status="draft",
                        replaces_draft_id=prev,
                        dry_run=dry_run,
                    )
                    status = {
                        "status": "draft",
                        "message": "Dry-run draft created" if dry_run else "Draft created",
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "piece_dir": piece_dir.replace("\\", "/"),
                        "draft_id": draft_id,
                        "dry_run": dry_run,
                        "publish": False,
                    }
                    with open(os.path.join(piece_dir, "upload_status.json"), "w", encoding="utf-8") as f:
                        json.dump(status, f, indent=2)
                    job_store.update_job(job_id, draft_id=draft_id, replaces_draft_id=prev)
                    events.publish("etsy.draft_created", {"draft_id": draft_id, "piece_path": piece_dir})

            elif stage == "awaiting_review":
                set_stage(stage, "Awaiting human review", i)
                events.publish("review.required", {"job_id": job_id, "batch_id": batch_id})
                # continue to complete for dry-run operator visibility of terminal state
                continue

            elif stage == "complete":
                set_stage(stage, "Complete", i)
                audit("job.completed", job_id=job_id, batch_id=batch_id, piece_path=piece_dir)
                events.publish("job.completed", {"job_id": job_id, "batch_id": batch_id})
                return job_store.get_job(job_id)

            time.sleep(0.08)

        set_stage("complete", "Complete", total)
        return job_store.get_job(job_id)
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            current_stage="failed",
            error=str(e),
            message=str(e),
            completed_at=time.time(),
        )
        audit("job.failed", job_id=job_id, batch_id=batch_id, error=str(e))
        events.publish("job.failed", {"job_id": job_id, "batch_id": batch_id, "error": str(e)})
        job_store.recompute_batch_progress(batch_id)
        events.invalidate("job.failed", batch_id=batch_id)
        return job_store.get_job(job_id)


def _map_product_type(pt: Optional[str]) -> str:
    pt = (pt or "single").lower()
    if pt in ("public_domain_pack", "pd_bundle"):
        return "pd_bundle"
    if pt in ("poster", "graphic_poster"):
        return "print"
    if pt == "bundle":
        return "bundle"
    return "print"


STYLE_SPINES = {
    "tonal_oil": (
        "painted as a small late-19th-century plein-air oil sketch on panel, "
        "somber muted tonal palette, soft grey overcast sky, textured impasto, "
        "full-bleed artwork, no frame, no text, no watermark"
    ),
    "japandi": (
        "abstract plaster texture art, organic arches, wabi-sabi Japandi, "
        "warm neutral beige and clay, full-bleed, no frame, no text"
    ),
    "botanical": (
        "detailed botanical specimen illustration in vintage lithograph style, "
        "aged parchment paper, muted sage and sepia, full-bleed, no text, no labels"
    ),
    "moody_coastal": (
        "soft fog, low-contrast desaturated blue-greys, atmospheric depth, "
        "full-bleed artwork, no frame, no text"
    ),
    "dark_academia": (
        "moody 19th-century Victorian oil painting sketch, dark academia candlelit study, "
        "deep umbers and forest greens, chiaroscuro, full-bleed, no frame, no text"
    ),
    "graphic_poster": (
        "clean painted-anime graphic poster, crisp outlines, smooth flat fills, "
        "limited palette, no text, no frame, no mockup"
    ),
    "custom": "full-bleed artwork, no frame, no text, no watermark",
}


def _sanitize_concept(concept: str) -> str:
    import re

    text = (concept or "").strip()
    ban = (
        r"\b(anatomy|anatomical|chart|diagram|infographic|taxonomy|"
        r"labeled|labels|label|caption|captions|legend|typography|text)\b"
    )
    cleaned = re.sub(ban, " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned or text


def _load_env_keys() -> None:
    env_path = os.path.expanduser("~/.config/ai-images/env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k:
                os.environ[k] = v
        gemini = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if gemini and not (os.environ.get("GOOGLE_API_KEY") or "").strip():
            os.environ["GOOGLE_API_KEY"] = gemini
    except Exception as e:
        print(f"batch env load warning: {e}")


def _try_live_acquire(row: Dict[str, Any], piece_dir: str, master_path: str) -> bool:
    """Generate one artwork via generate.py into master_path. Raises RuntimeError on failure."""
    _load_env_keys()
    python_exe = os.path.join(ROOT_DIR, "tooling", "ad-creatives", ".venv", "Scripts", "python.exe")
    if not os.path.isfile(python_exe):
        python_exe = sys.executable

    concept = _sanitize_concept(row.get("concept") or row.get("artwork_title") or "")
    if not concept:
        raise RuntimeError("Live generation needs a concept")

    preset = (row.get("style_preset") or "custom").lower()
    spine = STYLE_SPINES.get(preset) or STYLE_SPINES["custom"]
    model = (row.get("generation_model") or "cf-sdxl").strip() or "cf-sdxl"
    aspect = (row.get("aspect_ratio") or "4:5").strip() or "4:5"
    no_text = (
        "pure visual artwork only, absolutely no text, no letters, no words, "
        "no typography, no labels, no captions, no diagrams, no charts"
    )
    prompt = f"{concept}, {spine}, {no_text}"

    generate_script = os.path.join(ROOT_DIR, "tooling", "ad-creatives", "generate.py")
    out_dir = os.path.join(piece_dir, "_batch_gen")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.isfile(generate_script):
        raise RuntimeError(f"generate.py missing: {generate_script}")

    # Provider preflight
    has_cf = bool(
        (os.environ.get("CLOUDFLARE_WORKER_KEY") or "").strip()
        and (os.environ.get("CLOUDFLARE_WORKER_URL") or "").strip()
    )
    has_gemini = bool((os.environ.get("GEMINI_API_KEY") or "").strip())
    if model.startswith("cf-") and not has_cf:
        raise RuntimeError(
            "Cloudflare provider not configured (CLOUDFLARE_WORKER_URL + CLOUDFLARE_WORKER_KEY). "
            "Use dry-run, or configure providers, or pick a Gemini model."
        )
    if model.startswith("nano-") and not has_gemini:
        raise RuntimeError("Gemini API key not configured for this model. Use dry-run or configure GEMINI_API_KEY.")

    cmd = [
        python_exe,
        generate_script,
        prompt,
        "--model",
        model,
        "--aspect",
        aspect,
        "--n",
        "1",
        "--label",
        "batch",
        "--out",
        out_dir,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=os.path.dirname(generate_script),
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Artwork generation timed out after 5 minutes") from e

    images = []
    if os.path.isdir(out_dir):
        images = [
            os.path.join(out_dir, f)
            for f in sorted(os.listdir(out_dir))
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]
    if not images:
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise RuntimeError(
            "Artwork generation produced no image"
            + (f": {detail}" if detail else f" (exit {proc.returncode})")
        )

    src = images[0]
    img = Image.open(src).convert("RGB")
    img.save(master_path, "PNG")
    return True


def maybe_assemble_listing_bundle(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    When every artwork for a bundle listing_id is complete, build one Catalog piece
    with bundle/ masters — matching create_library_bundle shape.
    """
    row = job.get("row") or {}
    listing_product_type = _map_product_type(row.get("product_type"))
    if listing_product_type not in ("bundle", "pd_bundle"):
        return None

    batch_id = job.get("batch_id")
    listing_id = job.get("listing_id") or row.get("listing_id")
    if not batch_id or not listing_id:
        return None

    siblings = [
        j
        for j in job_store.list_jobs(batch_id=batch_id, limit=2000)
        if j.get("listing_id") == listing_id
    ]
    if not siblings:
        return None
    if any(j.get("status") != "complete" for j in siblings):
        return None

    piece_dirs = []
    for j in sorted(siblings, key=lambda x: (x.get("artwork_id") or "")):
        p = j.get("piece_path")
        if p and os.path.isfile(os.path.join(p, "master.png")):
            piece_dirs.append(p)
    if len(piece_dirs) < 2:
        return None

    sample = siblings[0].get("row") or {}
    dry_run = bool((job_store.get_batch(batch_id) or {}).get("dry_run"))
    run_name = _slug(f"{'dryrun' if dry_run else 'batch'}_{batch_id}_{listing_id}")
    run_dir = os.path.join(RUNS_DIR, run_name)
    listing_slug = _slug(sample.get("listing_name") or listing_id)[:48] or "listing"
    listing_piece_dir = os.path.join(run_dir, f"{listing_slug}_listing")
    bundle_dir = os.path.join(listing_piece_dir, "bundle")
    os.makedirs(bundle_dir, exist_ok=True)

    # Hide member pieces from Catalog
    for p in piece_dirs:
        meta_path = os.path.join(p, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            m["exclude_from_catalog"] = True
            m["batch_role"] = "bundle_member"
            m["listing_product_type"] = listing_product_type
            if m.get("product_type") in ("bundle", "pd_bundle"):
                m["product_type"] = "print"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=2)
        except Exception:
            pass

    copied = []
    orientations = {"portrait": 0, "landscape": 0, "square": 0}
    for i, src_piece in enumerate(piece_dirs, 1):
        src_master = os.path.join(src_piece, "master.png")
        dest_name = f"{i:02d}_{os.path.basename(src_piece)}.png"
        dest = os.path.join(bundle_dir, dest_name)
        shutil.copy2(src_master, dest)
        orient = "portrait"
        try:
            with Image.open(dest) as im:
                w, h = im.size
                if abs(w - h) < max(w, h) * 0.05:
                    orient = "square"
                elif w > h:
                    orient = "landscape"
            orientations[orient] = orientations.get(orient, 0) + 1
        except Exception:
            orientations["portrait"] += 1
        copied.append(
            {
                "path": dest.replace("\\", "/"),
                "source": src_piece.replace("\\", "/"),
                "orientation": orient,
            }
        )

    master_path = os.path.join(listing_piece_dir, "master.png")
    shutil.copy2(copied[0]["path"].replace("/", os.sep), master_path)

    title = sample.get("listing_title") or sample.get("listing_name") or listing_id
    tags = [t.strip() for t in (sample.get("tags") or "").split(",") if t.strip()][:13]
    description = (sample.get("description_notes") or title)[:2000]
    price = sample.get("price_eur")
    try:
        price = float(price) if price not in (None, "") else 12.99
    except (TypeError, ValueError):
        price = 12.99
    dominant = max(orientations, key=orientations.get) if any(orientations.values()) else "portrait"

    # Prefer a multi-frame mockup from any member if present
    for p in piece_dirs:
        for name in sorted(os.listdir(p)):
            if name.lower().startswith("mockup_") and name.lower().endswith((".jpg", ".jpeg", ".png")):
                shutil.copy2(os.path.join(p, name), os.path.join(listing_piece_dir, name))

    piece_meta = {
        "run_dir": run_dir.replace("\\", "/"),
        "title": title,
        "slug": f"{listing_slug}_listing",
        "source_image": master_path.replace("\\", "/"),
        "product_type": listing_product_type,
        "bundle_dir": bundle_dir.replace("\\", "/"),
        "bundle_count": len(copied),
        "bundle_orientations": orientations,
        "bundle_sources": [c["source"] for c in copied],
        "orientation": dominant,
        "sizes": "native",
        "model": "batch-bundle",
        "prompt": sample.get("concept") or title,
        "batch_id": batch_id,
        "listing_id": listing_id,
        "batch_role": "listing",
        "exclude_from_catalog": False,
        "dry_run": dry_run,
        "price": price,
        "quantity": "999",
        "seo": {
            "title": title[:140],
            "tags": tags,
            "description": description,
            "materials": ["digital download"],
        },
        "mockup_prefs": {"disabled_mockups": [], "selected_templates": [], "include_zoom_gif": False},
        "skip_print_crops": True,
        "quality_warnings": ["DRY-RUN TEST DATA — not a real artwork"] if dry_run else [],
    }
    os.makedirs(listing_piece_dir, exist_ok=True)
    with open(os.path.join(listing_piece_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(piece_meta, f, indent=2)
    with open(os.path.join(listing_piece_dir, "listing.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": title[:140],
                "tags": tags,
                "description": description,
                "materials": ["digital download"],
            },
            f,
            indent=2,
        )
    with open(os.path.join(listing_piece_dir, "bundle_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "product_type": listing_product_type,
                "title": title,
                "count": len(copied),
                "files": copied,
                "batch_id": batch_id,
                "listing_id": listing_id,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    draft_id = f"{'dryrun-' if dry_run else 'draft-'}{batch_id}-{listing_id}"
    draft_history.record_draft(
        listing_piece_dir,
        draft_id=draft_id,
        batch_id=batch_id,
        product_id=f"{listing_slug}_listing",
        uploaded_files=["master.png"] + [os.path.basename(c["path"]) for c in copied],
        status="draft",
        replaces_draft_id=None,
        dry_run=dry_run,
    )
    with open(os.path.join(listing_piece_dir, "upload_status.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": "draft",
                "message": "Bundle listing assembled" + (" (dry-run)" if dry_run else ""),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "piece_dir": listing_piece_dir.replace("\\", "/"),
                "draft_id": draft_id,
                "dry_run": dry_run,
                "publish": False,
                "bundle_count": len(copied),
            },
            f,
            indent=2,
        )

    # Attach draft id to the last sibling job for batch progress etsy_drafts count
    last = siblings[-1]
    job_store.update_job(last["id"], draft_id=draft_id)
    audit(
        "listing.bundle_assembled",
        batch_id=batch_id,
        listing_id=listing_id,
        piece_path=listing_piece_dir,
        bundle_count=len(copied),
    )
    events.publish(
        "listing.assembled",
        {
            "batch_id": batch_id,
            "listing_id": listing_id,
            "piece_path": listing_piece_dir.replace("\\", "/"),
            "bundle_count": len(copied),
        },
    )
    events.invalidate("listing.assembled", batch_id=batch_id)
    return {"piece_dir": listing_piece_dir, "bundle_count": len(copied), "draft_id": draft_id}


def resume_selection(job_id: str, selected: bool = True) -> Optional[Dict[str, Any]]:
    job = job_store.get_job(job_id)
    if not job:
        return None
    if job.get("status") != "awaiting_selection":
        return job
    job_store.update_job(
        job_id,
        status="queued",
        current_stage="preparing_master",
        message="Selection confirmed — resuming",
    )
    events.publish("review.completed", {"job_id": job_id})
    events.invalidate("review.completed")
    return job_store.get_job(job_id)
