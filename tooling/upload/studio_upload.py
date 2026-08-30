"""Artwork Studio — Upload existing prints as singles or a bundle.

Preserves native aspect (no force-crop to 4:5). Detects print families from
pixels and filenames, optionally infers subject via Gemini vision, then writes
the same candidate shape used by AI Generate / Public Domain so finalize,
mockups, Drive, SEO, and Etsy stay on the existing pipeline.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from io import BytesIO

from pd_prep import prep_image_bytes, prep_image_file

MAX_FILES = 40
# Local print masters (16x20 PNG/TIFF) routinely exceed 100–250 MB each.
# Cap is only a sanity check — Drive is not involved until after finalize.
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
STAGING_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".upload_staging")
_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()
SESSION_TTL_SEC = 6 * 60 * 60

# Pixel aspect (from classify_aspect) → buyer-facing print sizes.
ASPECT_PRINTS = {
    "4:5": ["4x5", "8x10", "16x20", "20x25"],
    "2:3": ["4x6", "8x12", "12x18", "16x24", "20x30", "24x36"],
    "3:2": ["6x4", "12x8", "18x12", "24x16", "30x20", "36x24"],
    "16:9": ["wide landscape"],
    "1:1": ["10x10", "12x12", "16x16"],
    "11:14": ["11x14"],
}

# Filename tokens the seller already used when exporting print sizes.
SIZE_TOKEN_RE = re.compile(
    r"(?:^|[_\-\s.])("
    r"\d{1,2}\s?[x×]\s?\d{1,2}"
    r"|a[1-5]"
    r"|iso[\-_]?a\d?"
    r")(?:$|[_\-\s.])",
    re.I,
)

FILENAME_SIZE_FAMILY = {
    "4x5": "4:5",
    "8x10": "4:5",
    "16x20": "4:5",
    "20x25": "4:5",
    "4x6": "2:3",
    "8x12": "2:3",
    "12x18": "2:3",
    "16x24": "2:3",
    "20x30": "2:3",
    "24x36": "2:3",
    "5x7": "5:7",
    "10x14": "5:7",
    "11x14": "11:14",
    "6x8": "3:4",
    "9x12": "3:4",
    "12x16": "3:4",
    "a4": "ISO_A",
    "a3": "ISO_A",
    "a5": "ISO_A",
}


def _norm_size_token(raw: str) -> str:
    t = (raw or "").lower().replace("×", "x").replace(" ", "")
    t = t.replace("iso-a", "a").replace("iso_a", "a").replace("isoa", "a")
    return t


def extract_size_token(filename: str) -> str:
    """Return a normalized size token from a filename, or ''."""
    name = os.path.splitext(os.path.basename(filename or ""))[0]
    m = SIZE_TOKEN_RE.search(" " + name + " ")
    if not m:
        return ""
    return _norm_size_token(m.group(1))


def stem_key(filename: str) -> str:
    """Group print-size variants of the same artwork (roses_8x10 + roses_16x20)."""
    name = os.path.splitext(os.path.basename(filename or ""))[0]
    name = SIZE_TOKEN_RE.sub(" ", " " + name + " ")
    return re.sub(r"[^a-z0-9]+", "", name.lower()) or "artwork"


def humanize_filename(filename: str) -> str:
    name = os.path.splitext(os.path.basename(filename or ""))[0]
    name = SIZE_TOKEN_RE.sub(" ", " " + name + " ")
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "Uploaded Artwork"
    return name.title()


def print_family_for(aspect: str, orientation: str, filename: str = "") -> dict:
    """Buyer-facing print sizes from pixels, with filename size token if present."""
    aspect = (aspect or "4:5").strip()
    orientation = (orientation or "portrait").strip() or "portrait"
    token = extract_size_token(filename)
    sizes = list(ASPECT_PRINTS.get(aspect) or [])
    filename_family = FILENAME_SIZE_FAMILY.get(token, "")
    if token and token not in {s.lower() for s in sizes}:
        sizes = [token] + sizes
    if filename_family and filename_family != aspect and filename_family in ASPECT_PRINTS:
        for s in ASPECT_PRINTS[filename_family]:
            if s not in sizes:
                sizes.append(s)
    label = f"{orientation} {aspect}"
    if token:
        label = f"{label} · file {token}"
    return {
        "aspect": aspect,
        "orientation": orientation,
        "filename_size": token,
        "print_sizes": sizes,
        "print_family": label,
        "print_sizes_label": ", ".join(sizes[:6]) if sizes else aspect,
    }


def parse_multipart_form(content_type: str, body: bytes):
    """Parse multipart/form-data into (fields dict, files list)."""
    from email import policy
    from email.parser import BytesParser

    ctype = content_type or ""
    if "multipart/form-data" not in ctype.lower():
        return {}, []
    header = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    msg = BytesParser(policy=policy.HTTP).parsebytes(header + (body or b""))
    fields = {}
    files = []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""
        if filename:
            files.append({
                "filename": os.path.basename(str(filename)),
                "data": payload,
                "content_type": part.get_content_type(),
            })
        elif name:
            fields[str(name)] = payload.decode("utf-8", errors="replace")
    return fields, files


def files_from_json_payload(data: dict) -> list:
    """Accept JSON {files:[{filename, data_b64}]} for tests / small payloads."""
    out = []
    for item in (data or {}).get("files") or []:
        raw = item.get("data_b64") or item.get("data") or ""
        if isinstance(raw, str) and raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            blob = base64.b64decode(raw) if isinstance(raw, str) else (raw or b"")
        except Exception:
            blob = b""
        out.append({
            "filename": os.path.basename(item.get("filename") or "upload.png"),
            "data": blob,
            "content_type": item.get("content_type") or "image/png",
        })
    return out


def _truthy(val) -> bool:
    if val is True:
        return True
    s = str(val or "").strip().lower()
    return s in ("1", "true", "yes", "on")


def _safe_slug(text: str, fallback: str = "upload") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return slug or fallback


def _safe_filename(text: str, fallback: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", (text or "").strip()).strip("._")
    return (stem[:80] or fallback)[:80]


def _nbytes(item: dict) -> int:
    path = item.get("path") or ""
    if path and os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    return len(item.get("data") or b"")


def _has_payload(item: dict) -> bool:
    path = item.get("path") or ""
    if path and os.path.isfile(path):
        return True
    return bool(item.get("data"))


def group_upload_files(files: list) -> list:
    """Collapse size-variant exports of the same artwork; keep the largest file as master."""
    buckets = {}
    order = []
    for i, f in enumerate(files or []):
        name = f.get("filename") or f"file-{i}"
        key = stem_key(name)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append({**f, "filename": name, "_i": i, "_n": _nbytes(f)})
    grouped = []
    for key in order:
        members = sorted(buckets[key], key=lambda x: (-x["_n"], x["_i"]))
        master = dict(members[0])
        extras = [m.get("filename") for m in members[1:]]
        master["group_key"] = key
        master["size_siblings"] = extras
        grouped.append(master)
    return grouped


def infer_visual_concept(image_paths, gemini_key: str, filenames=None) -> str:
    """One Gemini vision pass over 1–3 thumbs → short Etsy subject line."""
    if not gemini_key or not image_paths:
        return ""
    try:
        import requests
        from PIL import Image
    except Exception:
        return ""

    parts = [{
        "text": (
            "You describe wall-art prints for an Etsy listing. "
            "In 8 to 14 words, name the subject, setting, and style. "
            "No quotes, no numbering, no marketing adjectives like stunning."
        )
    }]
    names = filenames or []
    if names:
        parts[0]["text"] += " Filenames: " + ", ".join(names[:8])

    for path in list(image_paths)[:3]:
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((768, 768), Image.LANCZOS)
                buf = BytesIO()
                im.save(buf, format="JPEG", quality=72)
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(buf.getvalue()).decode("ascii"),
                }
            })
        except Exception:
            continue
    if len(parts) < 2:
        return ""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={gemini_key}"
    )
    try:
        r = requests.post(
            url,
            json={"contents": [{"parts": parts}]},
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            return ""
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.split("\n")[0].strip().strip('"').strip("'")
        return text[:160]
    except Exception as e:
        print(f"studio_upload vision: {e}")
        return ""


def import_files_to_run(
    files,
    runs_dir,
    root_dir,
    listing_kind="single",
    name="",
    trim_borders=False,
    infer_context=True,
    title_fn=None,
    gemini_key=None,
    max_files=MAX_FILES,
):
    """Write uploaded files into an artwork-run `_candidates` folder.

    Returns (run_dir, candidates, errors, meta).
    """
    listing_kind = "bundle" if str(listing_kind or "").strip().lower() == "bundle" else "single"
    files = [f for f in (files or []) if _has_payload(f)]
    if not files:
        raise ValueError("Choose at least one image file.")
    if len(files) > max_files:
        files = files[:max_files]

    accepted = []
    errors = []
    for f in files:
        fn = f.get("filename") or "upload.png"
        ext = os.path.splitext(fn)[1].lower()
        size = _nbytes(f)
        if ext not in ALLOWED_EXT:
            errors.append({"filename": fn, "error": f"Unsupported type {ext or '(none)'}"})
            continue
        if size > MAX_FILE_BYTES:
            errors.append({"filename": fn, "error": "File exceeds 2 GB"})
            continue
        accepted.append({**f, "filename": fn})

    if not accepted:
        raise ValueError(errors[0]["error"] if errors else "No valid image files.")

    grouped = group_upload_files(accepted)
    concept_hint = (name or "").strip() or humanize_filename(grouped[0]["filename"])
    slug = _safe_slug(concept_hint, "studio_upload")
    run_dir = os.path.join(runs_dir, slug)
    counter = 1
    while os.path.exists(run_dir):
        run_dir = os.path.join(runs_dir, f"{slug}_{counter}")
        counter += 1
    candidates_dir = os.path.join(run_dir, "_candidates")
    os.makedirs(candidates_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    product_type = "upload_bundle" if listing_kind == "bundle" else "print"
    candidates = []

    for i, item in enumerate(grouped):
        fn = item["filename"]
        label = f"upload-{i + 1}"
        dest = os.path.join(candidates_dir, f"{ts}_{label}.png")
        try:
            src_path = item.get("path") or ""
            if src_path and os.path.isfile(src_path):
                prep = prep_image_file(src_path, dest, trim_borders=bool(trim_borders))
            else:
                prep = prep_image_bytes(item.get("data") or b"", dest, trim_borders=bool(trim_borders))
        except Exception as e:
            errors.append({"filename": fn, "error": str(e)})
            continue

        family = print_family_for(
            prep.get("aspect") or "4:5",
            prep.get("orientation") or "portrait",
            fn,
        )
        art_title = humanize_filename(fn)
        file_stem = _safe_filename(art_title, label)
        rel_path = os.path.relpath(dest, root_dir).replace("\\", "/")
        cand = {
            "label": label,
            "path": dest.replace("\\", "/"),
            "rel_path": rel_path,
            "prompt": f"Studio upload: {art_title}",
            "model": "studio-upload",
            "aspect": family["aspect"],
            "orientation": family["orientation"],
            "aspect_ratio": prep.get("aspect_ratio"),
            "art_title": art_title,
            "file_stem": file_stem,
            "product_type": product_type,
            "listing_kind": listing_kind,
            "source_filename": fn,
            "size_siblings": item.get("size_siblings") or [],
            "print_family": family["print_family"],
            "print_sizes": family["print_sizes"],
            "print_sizes_label": family["print_sizes_label"],
            "filename_size": family["filename_size"],
            "prep": prep,
        }
        sidecar = dest + ".json"
        with open(sidecar, "w", encoding="utf-8") as fh:
            json.dump(cand, fh, indent=2, ensure_ascii=False)
        candidates.append(cand)

    if not candidates:
        raise ValueError(errors[0]["error"] if errors else "Could not read any uploaded images.")

    vision_concept = ""
    if infer_context and gemini_key:
        vision_concept = infer_visual_concept(
            [c["path"] for c in candidates],
            gemini_key,
            filenames=[c.get("source_filename") or c.get("art_title") for c in candidates],
        )

    concept = (name or "").strip() or vision_concept or concept_hint
    for c in candidates:
        c["prompt"] = f"Studio upload: {concept}"
        if vision_concept and listing_kind == "single" and len(candidates) == 1:
            c["art_title"] = humanize_filename(vision_concept) if len(vision_concept) < 80 else c["art_title"]

    suggested = []
    if callable(title_fn):
        try:
            suggested = list(title_fn(concept, f"Studio upload: {concept}") or [])
        except Exception as e:
            print(f"studio_upload titles: {e}")
            suggested = []
    if len(suggested) < 3:
        n = len(candidates)
        pack = f"Set of {n}" if n > 1 else "Printable Wall Art"
        suggested = (suggested + [
            f"{concept} — {pack}, Vintage Digital Print Decor",
            f"{concept} Wall Art, Printable Gallery Print",
            f"Moody {concept} Artwork, Digital Download",
        ])[:3]

    if listing_kind == "bundle":
        pack_title = (name or "").strip() or suggested[0]
    else:
        pack_title = (name or "").strip()
        for i, c in enumerate(candidates):
            if suggested:
                c["suggested_title"] = suggested[min(i, len(suggested) - 1)]

    manifest = {
        "source": "studio_upload",
        "product_type": product_type,
        "listing_kind": listing_kind,
        "concept": concept,
        "vision_concept": vision_concept,
        "pack_title": pack_title,
        "imported_at": datetime.now().isoformat(),
        "count": len(candidates),
        "grouped_from": len(accepted),
        "note": "Native aspect preserved. Staging originals are discarded after prep; listing masters stay until you delete the Catalog piece.",
        "orientations": {
            "portrait": sum(1 for c in candidates if c.get("orientation") == "portrait"),
            "landscape": sum(1 for c in candidates if c.get("orientation") == "landscape"),
            "square": sum(1 for c in candidates if c.get("orientation") == "square"),
        },
    }
    with open(os.path.join(run_dir, "studio_upload_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    return run_dir, candidates, errors, {
        **manifest,
        "suggested_titles": suggested,
    }


def _purge_stale_sessions():
    now = time.time()
    with _SESSIONS_LOCK:
        stale = [sid for sid, s in _SESSIONS.items() if now - s.get("created", 0) > SESSION_TTL_SEC]
    for sid in stale:
        abort_upload_session(sid)


def _session_dir(session_id: str) -> str:
    return os.path.join(STAGING_ROOT, session_id)


def begin_upload_session(listing_kind="single", name="", trim_borders=False, infer_context=True):
    _purge_stale_sessions()
    sid = uuid.uuid4().hex
    dest = _session_dir(sid)
    os.makedirs(dest, exist_ok=True)
    rec = {
        "id": sid,
        "dir": dest,
        "listing_kind": "bundle" if str(listing_kind).strip().lower() == "bundle" else "single",
        "name": (name or "").strip(),
        "trim_borders": bool(trim_borders),
        "infer_context": bool(infer_context),
        "files": [],
        "created": time.time(),
    }
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = rec
    return rec


def abort_upload_session(session_id: str):
    with _SESSIONS_LOCK:
        rec = _SESSIONS.pop(session_id, None)
    folder = (rec or {}).get("dir") or _session_dir(session_id)
    try:
        shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass
    return True


def add_upload_file(session_id: str, filename: str, data: bytes):
    with _SESSIONS_LOCK:
        rec = _SESSIONS.get(session_id)
    if not rec:
        raise ValueError("Upload session expired. Start the import again.")
    if len(rec["files"]) >= MAX_FILES:
        raise ValueError(f"Too many files (max {MAX_FILES}).")
    fn = os.path.basename(filename or "upload.png")
    ext = os.path.splitext(fn)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Unsupported type {ext or '(none)'}")
    blob = data or b""
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError("File exceeds 2 GB")
    if not blob:
        raise ValueError(f"{fn} is empty.")
    os.makedirs(rec["dir"], exist_ok=True)
    stem = _safe_filename(os.path.splitext(fn)[0], "upload")
    dest = os.path.join(rec["dir"], f"{len(rec['files']):03d}_{stem}{ext or '.png'}")
    with open(dest, "wb") as fh:
        fh.write(blob)
    rec["files"].append({"filename": fn, "path": dest})
    return {"filename": fn, "bytes": len(blob), "count": len(rec["files"])}


def commit_upload_session(session_id, runs_dir, root_dir, title_fn=None, gemini_key=None):
    with _SESSIONS_LOCK:
        rec = _SESSIONS.get(session_id)
    if not rec:
        raise ValueError("Upload session expired. Start the import again.")
    if not rec["files"]:
        abort_upload_session(session_id)
        raise ValueError("Choose at least one image file.")
    try:
        run_dir, candidates, errors, meta = import_files_to_run(
            rec["files"],
            runs_dir,
            root_dir,
            listing_kind=rec["listing_kind"],
            name=rec["name"],
            trim_borders=rec["trim_borders"],
            infer_context=rec["infer_context"],
            title_fn=title_fn,
            gemini_key=gemini_key,
        )
        return run_dir, candidates, errors, meta
    finally:
        abort_upload_session(session_id)


def _ok_payload(candidates, errors, meta, run_dir):
    warn = None
    if errors and candidates:
        warn = f"Imported {len(candidates)}; {len(errors)} file(s) skipped."
    return {
        "success": True,
        "product_type": meta.get("product_type"),
        "listing_kind": meta.get("listing_kind"),
        "pack_title": meta.get("pack_title") or "",
        "concept": meta.get("concept") or "",
        "vision_concept": meta.get("vision_concept") or "",
        "candidates": candidates,
        "suggested_titles": meta.get("suggested_titles") or [],
        "run_dir": (run_dir or "").replace("\\", "/"),
        "manifest": meta,
        "errors": errors,
        "warning": warn,
        "error": None,
    }


def handle_studio_upload(
    content_type,
    body,
    runs_dir,
    root_dir,
    title_fn=None,
    gemini_key=None,
    json_data=None,
    path="/api/studio_upload",
):
    """Parse HTTP body (multipart or JSON) and import. Returns (status, payload)."""
    path = (path or "/api/studio_upload").split("?")[0].rstrip("/")
    ctype = (content_type or "").lower()
    action = ""
    if json_data and isinstance(json_data, dict):
        action = str(json_data.get("action") or "").strip().lower()

    if path.endswith("/begin") or action == "begin":
        data = json_data if isinstance(json_data, dict) else {}
        if not data:
            try:
                data = json.loads((body or b"{}").decode("utf-8") or "{}")
            except Exception:
                data = {}
        rec = begin_upload_session(
            listing_kind=data.get("listing_kind") or "single",
            name=data.get("name") or data.get("concept") or "",
            trim_borders=_truthy(data.get("trim_borders")),
            infer_context=True if data.get("infer_context") in (None, "") else _truthy(data.get("infer_context")),
        )
        return 200, {"success": True, "session_id": rec["id"]}

    if path.endswith("/abort") or action == "abort":
        data = json_data if isinstance(json_data, dict) else {}
        if not data:
            try:
                data = json.loads((body or b"{}").decode("utf-8") or "{}")
            except Exception:
                data = {}
        abort_upload_session((data.get("session_id") or "").strip())
        return 200, {"success": True}

    if path.endswith("/file") or action == "file":
        fields, files = {}, []
        if "multipart/form-data" in ctype:
            fields, files = parse_multipart_form(content_type, body or b"")
        else:
            return 400, {"success": False, "error": "Send each artwork as a multipart file."}
        sid = (fields.get("session_id") or "").strip()
        if not sid:
            return 400, {"success": False, "error": "Missing upload session."}
        if not files:
            return 400, {"success": False, "error": "No file in this request."}
        added = []
        try:
            for f in files:
                added.append(add_upload_file(sid, f.get("filename") or "upload.png", f.get("data") or b""))
        except ValueError as e:
            return 400, {"success": False, "error": str(e)}
        except Exception as e:
            return 500, {"success": False, "error": str(e)}
        last = added[-1] if added else {}
        return 200, {"success": True, "session_id": sid, "count": last.get("count", len(added)), "filename": last.get("filename")}

    if path.endswith("/commit") or action == "commit":
        data = json_data if isinstance(json_data, dict) else {}
        if not data:
            try:
                data = json.loads((body or b"{}").decode("utf-8") or "{}")
            except Exception:
                data = {}
        sid = (data.get("session_id") or "").strip()
        if not sid:
            return 400, {"success": False, "error": "Missing upload session."}
        try:
            run_dir, candidates, errors, meta = commit_upload_session(
                sid, runs_dir, root_dir, title_fn=title_fn, gemini_key=gemini_key
            )
        except ValueError as e:
            return 400, {"success": False, "error": str(e)}
        except Exception as e:
            return 500, {"success": False, "error": str(e)}
        return 200, _ok_payload(candidates, errors, meta, run_dir)

    fields = {}
    files = []
    if "multipart/form-data" in ctype:
        fields, files = parse_multipart_form(content_type, body or b"")
    elif json_data is not None:
        fields = {
            "listing_kind": json_data.get("listing_kind") or "single",
            "name": json_data.get("name") or json_data.get("concept") or "",
            "trim_borders": json_data.get("trim_borders"),
            "infer_context": json_data.get("infer_context"),
        }
        files = files_from_json_payload(json_data)
    else:
        try:
            data = json.loads((body or b"{}").decode("utf-8") or "{}")
        except Exception:
            return 400, {"success": False, "error": "Expected multipart form data or JSON."}
        fields = {
            "listing_kind": data.get("listing_kind") or "single",
            "name": data.get("name") or data.get("concept") or "",
            "trim_borders": data.get("trim_borders"),
            "infer_context": data.get("infer_context"),
        }
        files = files_from_json_payload(data)

    listing_kind = (fields.get("listing_kind") or "single").strip().lower()
    name = (fields.get("name") or "").strip()
    trim_borders = _truthy(fields.get("trim_borders"))
    infer_raw = fields.get("infer_context")
    infer_context = True if infer_raw in (None, "") else _truthy(infer_raw)

    try:
        run_dir, candidates, errors, meta = import_files_to_run(
            files,
            runs_dir,
            root_dir,
            listing_kind=listing_kind,
            name=name,
            trim_borders=trim_borders,
            infer_context=infer_context,
            title_fn=title_fn,
            gemini_key=gemini_key,
        )
    except ValueError as e:
        return 400, {"success": False, "error": str(e)}
    except Exception as e:
        return 500, {"success": False, "error": str(e)}

    return 200, _ok_payload(candidates, errors, meta, run_dir)
