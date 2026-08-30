"""Groq-powered SEO pack for Etsy digital listings."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.3-70b-versatile shuts down 2026-08-16 — Groq recommends gpt-oss-120b
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _load_env():
    env_path = os.path.expanduser("~/.config/ai-images/env")
    if not os.path.isfile(env_path):
        return
    try:
        raw = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(env_path, "r", encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            return
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
    except OSError:
        pass


def get_groq_key() -> str:
    _load_env()
    return (os.environ.get("GROQ_API_KEY") or "").strip()


def _clip_tag(tag: str) -> str:
    t = re.sub(r"\s+", " ", (tag or "").strip())
    return t[:20]


def _normalize_pack(data: dict) -> dict:
    title = (data.get("title") or "").strip()[:140]
    description = (data.get("description") or "").strip()
    # Normalize newlines for Etsy readability
    description = re.sub(r"\r\n?", "\n", description)
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    tags = [_clip_tag(t) for t in (data.get("tags") or []) if str(t).strip()]
    tags = [t for t in tags if t][:13]
    materials = [str(m).strip()[:45] for m in (data.get("materials") or []) if str(m).strip()][:13]
    if not materials:
        materials = ["Digital download", "PDF", "Printable wall art"]
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "materials": materials,
    }


def _listing_mode(meta: dict) -> str:
    pt = (meta.get("product_type") or meta.get("product_kind") or meta.get("mode") or "print").lower()
    if pt in ("pd_bundle", "bundle"):
        return "bundle"
    if pt == "graphic_poster" or meta.get("product_kind") == "graphic_poster":
        return "graphic_poster"
    return "single"


def _size_list(meta: dict, piece_dir: str) -> list[str]:
    summary = meta.get("sizes_summary")
    if isinstance(summary, str) and summary.strip():
        # Prefer structured summary for the prompt (returned as one "label" blob handled below)
        return []
    sizes = meta.get("sizes")
    if isinstance(sizes, list) and sizes:
        return [str(s) for s in sizes]
    if isinstance(sizes, str) and sizes not in ("", "native", "all", "standard print ratios"):
        return [s.strip() for s in sizes.replace(";", ",").split(",") if s.strip()]
    try:
        from print_exports import size_labels_for_meta

        return size_labels_for_meta(meta.get("orientation") or "portrait", meta.get("aspect") or "4:5")
    except Exception:
        return ["4x6", "8x10", "11x14", "16x20", "A4"]


def groq_chat(messages: list[dict], temperature: float = 0.45, max_tokens: int = 4096) -> str:
    key = get_groq_key()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Add it to ~/.config/ai-images/env and restart the suite."
        )
    model = (os.environ.get("GROQ_MODEL") or DEFAULT_MODEL).strip()
    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    last_err: Exception | None = None
    payload = None
    for attempt in range(3):
        req = urllib.request.Request(
            GROQ_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AethelgardProductionSuite/2.0 (+local; seo-pack)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=75) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="replace")
            detail = raw_err[:800]
            if e.code == 403 and "1010" in detail:
                raise RuntimeError(
                    "Groq blocked the request (Cloudflare 1010). "
                    "Usually a missing User-Agent — restart the suite after updating, "
                    "or check GROQ_API_KEY in ~/.config/ai-images/env."
                ) from e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                last_err = RuntimeError(f"Groq API error {e.code}: {detail}")
                continue
            failed = ""
            try:
                err_obj = json.loads(raw_err)
                failed = ((err_obj.get("error") or {}).get("failed_generation") or "").strip()
            except Exception:
                failed = ""
            if failed:
                raise RuntimeError(f"Groq API error {e.code}: {detail}\n__FAILED_GENERATION__\n{failed}") from e
            raise RuntimeError(f"Groq API error {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise RuntimeError(
                f"Groq connection failed after retries ({e}). "
                "Check internet / GROQ_API_KEY, then try Generate SEO again."
            ) from e
    else:
        raise RuntimeError(f"Groq request failed: {last_err}")

    if not payload:
        raise RuntimeError(f"Groq request failed: {last_err}")

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"Groq returned no choices: {payload}")
    return (choices[0].get("message") or {}).get("content") or ""


def _salvage_json(text: str) -> dict:
    """Parse JSON, or repair truncated SEO JSON from Groq."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Empty SEO JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*", text)
    if not m:
        raise RuntimeError("Groq returned non-JSON SEO pack")
    chunk = m.group(0)
    # Close an open string if truncated mid-value
    if chunk.count('"') % 2 == 1:
        chunk += '"'
    # Best-effort close nested structures
    opens = chunk.count("{") - chunk.count("}")
    opens_arr = chunk.count("[") - chunk.count("]")
    chunk += "]" * max(0, opens_arr)
    chunk += "}" * max(0, opens)
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        # Minimal salvage: pull title/description/tags with regex
        title_m = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', chunk)
        desc_m = re.search(r'"description"\s*:\s*"((?:\\.|[^"\\])*)', chunk)
        title = title_m.group(1).encode("utf-8").decode("unicode_escape") if title_m else ""
        desc = ""
        if desc_m:
            desc = desc_m.group(1)
            desc = desc.encode("utf-8").decode("unicode_escape") if "\\" in desc else desc
            desc = desc.replace("\\n", "\n").rstrip(' ",')
        if not title and not desc:
            raise RuntimeError("Could not salvage truncated Groq SEO JSON")
        return {
            "title": title,
            "description": desc,
            "tags": [],
            "materials": ["Digital download", "PDF", "Printable wall art"],
        }


def generate_seo_pack_for_piece(piece_dir: str) -> dict:
    meta_path = os.path.join(piece_dir, "meta.json")
    if not os.path.isfile(meta_path):
        raise RuntimeError("meta.json missing")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # SEO must stay fast — never rebuild print JPEGs here.
    mode = _listing_mode(meta)
    # Public-domain museum packs: native masters only (no multi-ratio crop packs).
    is_pd_native = (meta.get("product_type") or "").lower() == "pd_bundle" or (
        bool(meta.get("skip_print_crops")) and (meta.get("product_type") or "").lower() == "pd_bundle"
    )

    title_hint = meta.get("title") or meta.get("slug") or "Wall art print"
    concept = (meta.get("prompt") or meta.get("seo", {}).get("description") or title_hint)[:500]
    size_labels = _size_list(meta, piece_dir)
    sizes_summary = meta.get("sizes_summary") or ""
    if not is_pd_native and not sizes_summary:
        try:
            from print_exports import ratio_size_summary

            sizes_summary = ratio_size_summary(meta.get("orientation") or "portrait")
        except Exception:
            sizes_summary = ", ".join(size_labels) if size_labels else "standard printable ratios"
    sizes_csv = sizes_summary
    bundle_count = meta.get("bundle_count")
    aspect = meta.get("aspect") or meta.get("aspect_ratio") or "4:5"
    orientation = meta.get("orientation") or "portrait"

    if is_pd_native:
        system = (
            "You write Etsy SEO for Aethelgard Art Co. (digital wall art, EUR). "
            "Return ONE compact JSON object with keys: title, description, tags, materials.\n\n"
            "This listing is a PUBLIC DOMAIN / museum open-access PACK.\n"
            "Files are delivered at NATIVE aspect ratios (original composition preserved). "
            "Do NOT claim multiple aspect-ratio print packs, 2:3/3:4/4:5 size matrices, "
            "or 'resized for every frame size'. That would be false.\n\n"
            "TITLE (critical for ranking):\n"
            "- MUST be 120–140 characters (use nearly the full Etsy limit).\n"
            "- Front-load buyer search phrases: vintage, public domain, gallery wall, printable, digital download.\n"
            "- Mention artwork count when known. Avoid '4:5' / 'multi-ratio' claims.\n"
            "- No emoji, no shop-name stuffing.\n\n"
            "DESCRIPTION:\n"
            "- Exactly 4 short paragraphs separated by \\n\\n.\n"
            "P1 mood/room hook for a cohesive vintage gallery wall.\n"
            "P2 WHAT'S INCLUDED — high-resolution PNG/JPG files at each artwork's "
            "ORIGINAL aspect ratio (museum scan / open-access master), smart-trimmed only. "
            "Buyers scale to print size while keeping the true composition. "
            f"If bundle_count given, say there are {bundle_count or 'several'} artworks.\n"
            "P3 PDF via Google Drive link after purchase; no physical ship.\n"
            "P4 print tips + personal use only; note public-domain / open-access provenance briefly.\n\n"
            "TAGS: up to 13 strings ≤20 chars — vintage, public domain, gallery wall, printable, etc.\n"
            "MATERIALS: [\"Digital download\",\"PDF\",\"Printable wall art\",\"PNG\"] or JPEG if accurate."
        )
        user = (
            f"mode=pd_native_pack; orientation={orientation}; "
            f"bundle_count={bundle_count or 1}; "
            f"title_hint={title_hint}; "
            f"concept={concept}. "
            "Write a LONG Etsy title (120-140 chars) plus honest native-file description and tags."
        )
    else:
        system = (
            "You write Etsy SEO for Aethelgard Art Co. (digital wall art, EUR). "
            "Return ONE compact JSON object with keys: title, description, tags, materials.\n\n"
            "TITLE (critical for ranking):\n"
            "- MUST be 120–140 characters (use nearly the full Etsy limit). Count carefully.\n"
            "- Front-load the strongest buyer search phrase in the first 40–60 chars.\n"
            "- Pack distinct searchable phrases: style, subject/motif, room/use, format "
            "(Printable / Digital Download / Wall Art / Poster), color/mood, and multi-size / multi-ratio cue.\n"
            "- Prefer natural separators: commas or | — not keyword spam or ALL CAPS.\n"
            "- Never end early with a short 3–5 word title. Expand with real search terms buyers type.\n"
            "- No emoji, no shop name stuffing, no 'best seller' hype.\n\n"
            "DESCRIPTION:\n"
            "- Exactly 4 short paragraphs separated by \\n\\n.\n"
            "P1 mood/room hook. "
            "P2 WHAT'S INCLUDED — say the download includes MULTIPLE ASPECT RATIOS "
            f"(2:3, 3:4, 4:5, 5:7, 11:14, ISO A) with these exact size groups: {sizes_csv}. "
            "Say files are high-resolution JPGs ready to print. "
            "P3 PDF via Google Drive link after purchase; no physical ship. "
            "P4 print tips + personal use only. "
            "If bundle: mention artwork count.\n\n"
            "TAGS: up to 13 strings, each ≤20 chars — style, subject, room, printable, digital download.\n"
            "MATERIALS: e.g. [\"Digital download\",\"PDF\",\"Printable wall art\",\"JPEG\"]."
        )
        user = (
            f"mode={mode}; orientation={orientation}; aspect={aspect}; "
            f"bundle_count={bundle_count or 1}; "
            f"title_hint={title_hint}; "
            f"concept={concept}; "
            f"sizes={sizes_csv}. "
            "Write a LONG Etsy title (120-140 chars) plus description and tags."
        )

    def _call(temp: float) -> dict:
        try:
            raw = groq_chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temp,
                max_tokens=4096,
            )
            return _salvage_json(raw)
        except RuntimeError as e:
            msg = str(e)
            if "__FAILED_GENERATION__" in msg:
                failed = msg.split("__FAILED_GENERATION__\n", 1)[-1]
                return _salvage_json(failed)
            raise

    try:
        data = _call(0.4)
    except Exception:
        # Shorter retry if first pass still blows up
        data = _call(0.2)

    pack = _normalize_pack(data)
    if not pack["title"]:
        pack["title"] = str(title_hint)[:140]
    if not pack["description"]:
        raise RuntimeError("SEO pack missing description")
    if not pack["tags"]:
        pack["tags"] = ["printable wall art", "digital download", "wall art print", "minimalist print"][:13]

    # If Groq returns a short title, expand once with a focused rewrite
    if len(pack["title"]) < 100:
        try:
            expand = groq_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite this Etsy listing title to 120-140 characters for search rank. "
                            "Return JSON {\"title\":\"...\"} only. Keep meaning, add searchable phrases "
                            "(style, subject, room, printable, digital download, wall art, colors). "
                            "No emoji. Do not exceed 140 chars."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Short title: {pack['title']}\n"
                            f"Concept: {concept}\n"
                            f"Mode: {mode}; aspect: {aspect}; sizes: {sizes_csv}"
                        ),
                    },
                ],
                temperature=0.35,
                max_tokens=256,
            )
            expanded = _salvage_json(expand)
            new_title = (expanded.get("title") or "").strip()[:140]
            if len(new_title) > len(pack["title"]):
                pack["title"] = new_title
        except Exception:
            pass

    # Soft guarantee: if multi-ratio pack wasn't mentioned, append sizes paragraph
    # (AI / theme prints only — never invent ratio packs for PD native deliveries)
    if not is_pd_native:
        desc_l = pack["description"].lower()
        needs_sizes = ("4x5" not in desc_l and "8x10" not in desc_l) or (
            "2:3" not in desc_l and "2x3" not in desc_l and "ratio" not in desc_l
        )
        if needs_sizes:
            pack["description"] = (
                pack["description"].rstrip()
                + "\n\nWhat's included: high-resolution JPG print files across multiple aspect ratios — "
                + sizes_csv
                + ". After purchase you'll get a PDF with a link to download your files from Google Drive. "
                "No physical item is shipped."
            )
    return pack


def apply_seo_pack_to_piece(piece_dir: str, pack: dict) -> dict:
    pack = _normalize_pack(pack)
    meta_path = os.path.join(piece_dir, "meta.json")
    listing_path = os.path.join(piece_dir, "listing.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["title"] = pack["title"]
    seo = meta.get("seo") or {}
    seo["title"] = pack["title"]
    seo["description"] = pack["description"]
    seo["tags"] = pack["tags"]
    seo["materials"] = pack["materials"]
    meta["seo"] = seo
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    with open(listing_path, "w", encoding="utf-8") as f:
        json.dump({
            "title": pack["title"],
            "tags": pack["tags"],
            "description": pack["description"],
            "materials": pack["materials"],
        }, f, indent=2)
    seo_md = os.path.join(piece_dir, "seo.md")
    with open(seo_md, "w", encoding="utf-8") as f:
        f.write(f"# {pack['title']}\n\n")
        f.write("**Tags**:\n")
        for t in pack["tags"]:
            f.write(f"- {t}\n")
        f.write("\n**Materials**:\n")
        for m in pack["materials"]:
            f.write(f"- {m}\n")
        f.write(f"\n**Description:**\n\n{pack['description']}\n")
    return pack


def suggest_bundle_options(artworks: list[dict]) -> list[dict]:
    """artworks: [{title, prompt, path}] → 2–3 bundle concepts."""
    if len(artworks) < 2:
        raise RuntimeError("Need at least 2 artworks")
    lines = []
    for i, a in enumerate(artworks[:24], 1):
        lines.append(f"{i}. {a.get('title') or 'Untitled'} — {(a.get('prompt') or '')[:180]}")
    system = (
        "You suggest themed digital wall-art bundles for Etsy. "
        "Return JSON: {\"options\":[{\"title\":\"...\",\"concept\":\"...\"}]} "
        "Give 2 or 3 options. Titles ≤100 chars. Concepts are 1–2 sentences."
    )
    user = "Selected artworks:\n" + "\n".join(lines)
    raw = groq_chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=0.7)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise RuntimeError("Groq returned non-JSON bundle options")
        data = json.loads(m.group(0))
    opts = data.get("options") or []
    clean = []
    for o in opts[:3]:
        title = (o.get("title") or "").strip()[:120]
        concept = (o.get("concept") or "").strip()
        if title:
            clean.append({"title": title, "concept": concept})
    if not clean:
        raise RuntimeError("No bundle options returned")
    return clean
