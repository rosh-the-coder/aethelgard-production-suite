"""Public-domain art search + download (Met Museum Open Access).

Only returns objects marked isPublicDomain=true by The Met.
Users remain responsible for verifying license for commercial Etsy use.
Imports are always treated as a pack (bundle listing), with native aspect preserved.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from io import BytesIO

import requests

from pd_prep import classify_aspect, prep_image_file

MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}"
WIKI_API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "AethelgardArtCo/1.2 (local production tool; public-domain research)"}

# Met often returns this near-identical junk cluster when isPublicDomain+hasImages are combined
_BOGUS_MET_IDS = {544320, 310453, 200668, 437261, 824771, 472562}

# Synonyms help when Met's keyword AND is too strict (e.g. "coastal lands" → 1 hit)
_QUERY_SYNONYMS = {
    "coastal": ["coast", "seascape", "shore", "beach", "maritime", "ocean", "wave", "ship", "boat"],
    "lands": ["landscape", "scenery"],
    "landscape": ["landscape", "scenery", "vista"],
    "flower": ["floral", "blossom", "botanical"],
    "flowers": ["floral", "blossom", "botanical"],
    # Keep fungi terms tight — do NOT expand into generic "botanical" (floods florals)
    "mushroom": ["fungi", "fungus", "toadstool", "agaric", "mycology", "mycological"],
    "fungi": ["mushroom", "fungus", "toadstool", "agaric", "mycological"],
    "fungus": ["mushroom", "fungi", "toadstool", "agaric"],
    "toadstool": ["mushroom", "fungi", "agaric"],
    "bird": ["avian", "ornithology"],
    "birds": ["avian", "ornithology"],
    "portrait": ["portrait", "bust"],
    "still": ["still life"],
    "life": [],
    "vintage": ["antique"],
    "botanical": ["botany", "herbarium"],
    "sea": ["seascape", "marine", "ocean", "maritime", "wave", "ship"],
    "ocean": ["seascape", "marine", "maritime", "wave"],
    "mountain": ["alpine", "peaks", "landscape"],
    "forest": ["woods", "trees", "landscape"],
    "japan": ["japanese", "ukiyo-e", "hokusai"],
    "japanese": ["japan", "ukiyo-e", "hokusai"],
    "wave": ["great wave", "ukiyo-e", "hokusai", "seascape"],
    "ship": ["boat", "vessel", "maritime", "harbor"],
    "boat": ["ship", "sailboat", "maritime"],
}


def _normalize_query(query):
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _is_fungi_query(words_or_q):
    if isinstance(words_or_q, str):
        words = [w for w in re.split(r"[^a-z0-9]+", words_or_q) if w]
    else:
        words = list(words_or_q or [])
    return any(w in words for w in ("mushroom", "mushrooms", "fungi", "fungus", "toadstool", "agaric", "mycology"))


def expand_search_queries(query, max_variants=14):
    """Build Met search variants when the exact phrase is too narrow."""
    q = _normalize_query(query)
    if not q:
        return []
    variants = [q]
    words = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) >= 3]

    preferred = []
    if any(w in words for w in ("coastal", "coast", "ocean", "sea", "marine", "beach", "shore")):
        preferred.extend([
            "seascape", "great wave", "hokusai", "ukiyo-e wave",
            "ship at sea", "sailing ship", "boat harbor", "fishing boat",
            "beach landscape", "rocky coast", "palm tree coast",
            "marine painting", "coast landscape", "shore",
        ])
    if "lands" in words or "landscape" in words:
        preferred.extend(["landscape painting", "landscape", "vista"])
    # Mushrooms first — never mix with floral still-life expansions
    if _is_fungi_query(words):
        preferred.extend([
            "mushroom", "mushrooms", "fungi", "fungus", "toadstool",
            "agaric", "mycological illustration", "mushroom botanical",
            "fungi botanical", "chanterelle", "amanita",
        ])
    elif any(w in words for w in ("flower", "flowers", "floral", "peony", "rose")):
        preferred.extend(["botanical", "floral still life", "herbarium", "flower study"])
    elif "botanical" in words:
        preferred.extend(["botanical", "herbarium", "plant study"])

    for p in preferred:
        variants.append(p)

    if len(words) >= 2:
        variants.append(words[0])
        variants.append(" ".join(words[:2]))
        for syn in _QUERY_SYNONYMS.get(words[1], [])[:3]:
            variants.append(f"{words[0]} {syn}")
        for syn in _QUERY_SYNONYMS.get(words[0], [])[:4]:
            variants.append(syn)

    for w in words:
        for syn in _QUERY_SYNONYMS.get(w, [])[:3]:
            variants.append(syn)

    seen = set()
    out = []
    for v in variants:
        v = _normalize_query(v)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
        if len(out) >= max_variants:
            break
    return out


def _met_search_ids(query):
    """Search Met. Avoid isPublicDomain+hasImages together — that combo often
    returns a bogus ~40-id highlight set unrelated to the query. PD + image
    checks happen in fetch_met_object instead.
    """
    q = (query or "").strip()
    if not q:
        return [], 0

    def _get(params):
        r = requests.get(MET_SEARCH, params=params, headers=UA, timeout=45)
        r.raise_for_status()
        data = r.json() or {}
        ids = list(data.get("objectIDs") or [])
        total = int(data.get("total") or 0)
        return ids, total

    # Prefer open keyword search; filter PD on object fetch
    ids, total = _get({"q": q})
    if _looks_like_bogus_met_ids(ids):
        ids2, total2 = _get({"q": q, "isPublicDomain": "true"})
        if ids2 and not _looks_like_bogus_met_ids(ids2):
            return ids2, total2
        # Last resort: hasImages alone
        ids3, total3 = _get({"q": q, "hasImages": "true"})
        if ids3 and not _looks_like_bogus_met_ids(ids3):
            return ids3, total3
    return ids, total


def _looks_like_bogus_met_ids(ids):
    if not ids or len(ids) < 5:
        return False
    head = set(int(x) for x in ids[:8] if str(x).isdigit())
    return len(head & _BOGUS_MET_IDS) >= 3


_PD_LICENSE_MARKERS = (
    "public domain", "pd-", "cc0", "cc-zero", "no restrictions",
    "copyright expired", "pd-art", "pd-old", "pd-us",
)


def _commons_license_ok(extmeta):
    if not isinstance(extmeta, dict):
        return False
    bits = []
    for key in ("LicenseShortName", "License", "UsageTerms", "Copyright"):
        node = extmeta.get(key) or {}
        val = (node.get("value") if isinstance(node, dict) else node) or ""
        bits.append(str(val).lower())
    blob = " ".join(bits)
    if any(b in blob for b in ("all rights reserved", "fair use", "non-commercial", "cc-by-nc")):
        return False
    return any(m in blob for m in _PD_LICENSE_MARKERS)


def search_wikimedia_commons(query, limit=48):
    """Search Wikimedia Commons for clearly public-domain / CC0 image files."""
    q = _normalize_query(query)
    if not q:
        return []
    limit = max(1, min(int(limit or 48), 96))
    # Bias toward illustrated plates for fungi / botanical wall art
    if _is_fungi_query(q):
        search_q = (
            f'{q} (mushroom OR fungi OR toadstool OR agaric OR mycological) '
            f'illustration OR botanical OR plate filetype:bitmap'
        )
    else:
        search_q = f"{q} illustration OR painting OR print filetype:bitmap"

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search_q,
        "gsrnamespace": 6,  # File:
        "gsrlimit": min(50, max(limit * 2, 24)),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 1200,
        "origin": "*",
    }
    try:
        r = requests.get(WIKI_API, params=params, headers=UA, timeout=45)
        r.raise_for_status()
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
    except Exception:
        return []

    out = []
    seen_titles = set()
    for page in pages.values():
        title = (page.get("title") or "").replace("File:", "").strip()
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = (info.get("mime") or "").lower()
        if not mime.startswith("image/"):
            continue
        if mime in ("image/svg+xml", "image/gif"):
            continue
        ext = info.get("extmetadata") or {}
        if not _commons_license_ok(ext):
            continue
        url = info.get("url") or info.get("thumburl") or ""
        thumb = info.get("thumburl") or url
        if not url:
            continue
        display = title.rsplit(".", 1)[0] if "." in title else title
        dedupe_key = re.sub(r"\s+", " ", display.lower()).strip()
        if dedupe_key in seen_titles:
            continue
        seen_titles.add(dedupe_key)
        artist_node = ext.get("Artist") or {}
        artist = re.sub(r"<[^>]+>", "", str(artist_node.get("value") if isinstance(artist_node, dict) else artist_node or "Unknown"))
        artist = re.sub(r"\s+", " ", artist).strip() or "Unknown"
        license_node = ext.get("LicenseShortName") or ext.get("License") or {}
        rights = str(license_node.get("value") if isinstance(license_node, dict) else license_node or "Public Domain / CC0")
        page_id = page.get("pageid") or title
        out.append({
            "source": "wikimedia_commons",
            "object_id": f"commons-{page_id}",
            "title": display,
            "artist": artist[:120],
            "date": "",
            "department": "Wikimedia Commons",
            "medium": mime,
            "credit": "Wikimedia Commons",
            "rights": f"{rights} (verify before commercial use)",
            "object_url": f"https://commons.wikimedia.org/wiki/File:{title.replace(' ', '_')}",
            "image": url,
            "image_small": thumb,
        })
        if len(out) >= limit:
            break
    return out


def _score_card(card, query_terms, source_query="", fungi_mode=False):
    hay = " ".join([
        card.get("title") or "",
        card.get("artist") or "",
        card.get("department") or "",
        card.get("medium") or "",
        card.get("date") or "",
    ]).lower()
    title = (card.get("title") or "").lower()
    score = 0
    for t in query_terms:
        if t in title:
            score += 5
        elif t in hay:
            score += 2
    # Scene keywords common in landscape / coastal wall art
    scene_hits = (
        "seascape", "coast", "shore", "beach", "harbor", "harbour", "ocean",
        "marine", "wave", "sea ", "landscape", "cliff", "dune", "bay ",
    )
    for kw in scene_hits:
        if len(kw.strip()) <= 3:
            if re.search(rf"(?<![a-z]){re.escape(kw.strip())}(?![a-z])", title):
                score += 4
            elif re.search(rf"(?<![a-z]){re.escape(kw.strip())}(?![a-z])", hay):
                score += 1
        elif kw in title:
            score += 4
        elif kw in hay:
            score += 1
    src = (source_query or "").lower()
    # Prefer hits that came from a strong art-query variant
    if fungi_mode:
        if any(k in src for k in ("mushroom", "fungi", "fungus", "toadstool", "agaric", "mycolog", "amanita")):
            score += 5
    elif any(k in src for k in ("seascape", "landscape", "marine", "shore", "botanical", "floral")):
        score += 3
    if src in ("coastal", "coast", "sea") and not any(k in title for k in scene_hits):
        score -= 2
    if fungi_mode:
        fungi_hits = (
            "mushroom", "fungi", "fungus", "toadstool", "agaric", "mycolog",
            "chanterelle", "amanita", "bolete", "morel", "puffball", "fungal",
        )
        floral_noise = (
            "flower", "floral", "rose", "peony", "bouquet", "blossom", "still life",
            "vase", "tulip", "daisy", "orchid", "lily", "chrysanthem", "carnation",
            "snuffbox", "snuff-box", "fruit",
        )
        for kw in fungi_hits:
            if kw in title:
                score += 12
            elif kw in hay:
                score += 6
        for kw in floral_noise:
            if kw in title:
                score -= 10
            elif kw in hay:
                score -= 5
    dept = (card.get("department") or "").lower()
    medium = (card.get("medium") or "").lower()
    if any(k in dept for k in (
        "paintings", "drawings", "prints", "photographs",
    )):
        score += 3
    elif "asian art" in dept:
        score += 1
    if any(k in medium for k in ("oil", "watercolor", "canvas", "etching", "lithograph")):
        score += 2
    if any(k in dept for k in ("arms", "armor", "musical", "costume", "egyptian art", "islamic art")):
        score -= 4
    vase_penalty = ("clock", "watch", "teapot", "sword", "dagger", "armor", "poems")
    if fungi_mode:
        # "vase" is floral noise already; keep other decorative penalties
        if any(k in title for k in vase_penalty):
            score -= 5
    elif any(k in title for k in ("clock", "watch", "vase", "teapot", "sword", "dagger", "armor", "poems")):
        score -= 5
    if card.get("image"):
        score += 1
    return score


def search_met(query, limit=48, offset=0, return_meta=False):
    """Search Met Open Access. Expands queries broadly and ranks by relevance.

    offset skips the first N ranked results (for Load more).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    q = _normalize_query(query)
    if not q:
        return ([], {"queries_tried": []}) if return_meta else []
    limit = max(1, min(int(limit or 48), 96))
    offset = max(0, int(offset or 0))
    query_terms = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) >= 3]
    score_terms = list(query_terms)
    for w in query_terms:
        for syn in _QUERY_SYNONYMS.get(w, [])[:6]:
            for part in re.split(r"\s+", syn):
                if len(part) >= 3 and part not in score_terms:
                    score_terms.append(part)
    for extra in ("wave", "ship", "boat", "harbor", "sail", "palm", "ukiyo"):
        if any(t in score_terms for t in ("coastal", "coast", "sea", "ocean", "marine", "beach")):
            if extra not in score_terms:
                score_terms.append(extra)
    fungi_mode = _is_fungi_query(q)
    if fungi_mode:
        for extra in ("mushroom", "fungi", "fungus", "toadstool", "agaric", "mycological", "amanita"):
            if extra not in score_terms:
                score_terms.append(extra)

    variants = expand_search_queries(q, max_variants=14)
    id_order = []
    seen_ids = set()
    id_source = {}
    queries_tried = []

    for i, variant in enumerate(variants):
        try:
            ids, total = _met_search_ids(variant)
        except Exception:
            continue
        queries_tried.append({"q": variant, "total": total})
        art_q = any(k in variant for k in (
            "seascape", "landscape", "marine", "shore", "botanical", "floral",
            "wave", "ship", "boat", "hokusai", "ukiyo", "harbor", "beach",
            "mushroom", "fungi", "fungus", "toadstool", "agaric", "mycolog",
        ))
        take = min(len(ids), 80 if art_q else 40)
        new_ids = []
        for oid in ids[:take]:
            if oid not in seen_ids:
                seen_ids.add(oid)
                new_ids.append(oid)
                id_source[oid] = variant
        if art_q and i > 0:
            id_order = new_ids + id_order
        else:
            id_order.extend(new_ids)
        # Keep expanding until we have a large pool (don't stop at first decent hit)
        if len(id_order) >= 220:
            break
        time.sleep(0.03)

    # Fetch enough to cover offset + limit with ranking headroom
    need = offset + limit
    fetch_cap = min(len(id_order), max(need * 2, min(160, need + 60)))
    to_fetch = id_order[:fetch_cap]
    out = []

    def _fetch(oid):
        try:
            return oid, fetch_met_object(oid)
        except Exception:
            return oid, None

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_fetch, oid) for oid in to_fetch]
        for fut in as_completed(futures):
            oid, card = fut.result()
            if not card or not card.get("image"):
                continue
            card["_score"] = _score_card(
                card, score_terms, id_source.get(oid, ""), fungi_mode=fungi_mode
            )
            out.append(card)

    source_note = None
    # Met Open Access barely indexes mushrooms — Commons has the mycological plates.
    if fungi_mode:
        try:
            commons = search_wikimedia_commons(q, limit=min(96, max(need + 24, 48)))
            queries_tried.insert(0, {"q": f"commons:{q}", "total": len(commons)})
            for card in commons:
                card["_score"] = _score_card(
                    card, score_terms, "wikimedia fungi", fungi_mode=True
                ) + 25
                out.append(card)
            if commons:
                source_note = (
                    "Met has almost no mushroom plates — results include Wikimedia Commons "
                    "(PD/CC0). Verify license before selling."
                )
        except Exception:
            pass

    out.sort(key=lambda c: (-c.get("_score", 0), c.get("title") or ""))
    scenic = (not fungi_mode) and any(t in score_terms for t in (
        "coastal", "coast", "seascape", "shore", "ocean", "sea", "landscape", "marine", "beach", "wave",
    ))
    if scenic:
        scene_kw = (
            "seashore", "seascape", "coast", "shore", "beach", "harbor", "harbour",
            "ocean", "marine", "wave", "sea", "landscape", "cliff", "dune", "bay",
            "tempest", "storm", "marina", "port", "boat", "ship", "sail", "hokusai",
            "ukiyo", "palm", "coconut", "island", "fisher", "yacht", "schooner",
        )
        def _is_scenic(card):
            blob = f"{card.get('title','')} {card.get('medium','')} {card.get('department','')}".lower()
            for k in scene_kw:
                k = k.strip()
                if len(k) <= 3:
                    if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", blob):
                        return True
                elif k in blob:
                    return True
            return False
        scenic_cards = [c for c in out if _is_scenic(c)]
        # Prefer scenic, but keep a long list — don't collapse to a tiny set
        if len(scenic_cards) >= 8:
            rest = [c for c in out if c not in scenic_cards]
            out = scenic_cards + rest

    if fungi_mode:
        fungi_kw = (
            "mushroom", "fungi", "fungus", "toadstool", "agaric", "mycolog",
            "chanterelle", "amanita", "bolete", "morel", "puffball", "fungal",
        )
        floral_noise = (
            "flower", "floral", "rose", "peony", "bouquet", "blossom", "still life",
            "vase of", "tulip", "daisy", "orchid", "lily", "chrysanthem", "carnation",
            "snuffbox", "fruit",
        )

        def _is_fungi(card):
            blob = f"{card.get('title','')} {card.get('medium','')} {card.get('department','')}".lower()
            return any(k in blob for k in fungi_kw) or card.get("source") == "wikimedia_commons"

        def _is_floral_noise(card):
            blob = f"{card.get('title','')} {card.get('medium','')}".lower()
            if _is_fungi(card):
                return False
            return any(k in blob for k in floral_noise)

        fungi_cards = [c for c in out if _is_fungi(c)]
        clean = [c for c in out if not _is_floral_noise(c)]
        # Prefer true fungi; demote obvious florals/still lifes / Met noise
        if len(fungi_cards) >= 4:
            rest = [c for c in clean if c not in fungi_cards]
            noise = [c for c in out if c not in fungi_cards and c not in rest]
            out = fungi_cards + rest + noise
        elif len(clean) >= 8:
            noise = [c for c in out if c not in clean]
            out = clean + noise
        # Drop Met junk that isn't fungi when Commons filled the list
        if len(fungi_cards) >= 8:
            out = [c for c in out if _is_fungi(c) or c.get("source") == "wikimedia_commons"]

    for c in out:
        c.pop("_score", None)
    total_ranked = len(out)
    results = out[offset: offset + limit]
    has_more = (offset + limit) < total_ranked
    if return_meta:
        return results, {
            "queries_tried": [x["q"] for x in queries_tried],
            "query_totals": queries_tried,
            "expanded": len(queries_tried) > 1,
            "offset": offset,
            "limit": limit,
            "total_ranked": total_ranked,
            "has_more": has_more,
            "pool_ids": len(id_order),
            "note": source_note,
        }
    return results


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
    try:
        from PIL import Image
        im = Image.open(BytesIO(data)).convert("RGB")
        im.save(dest_path, format="PNG", optimize=True)
    except Exception:
        with open(dest_path, "wb") as f:
            f.write(data)
    return dest_path


def _safe_filename(text, fallback="art"):
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    slug = re.sub(r"[\s_-]+", "-", slug)[:48].strip("-")
    return slug or fallback


def import_objects_to_run(objects, runs_dir, concept="public domain vintage", trim_borders=True, max_objects=36):
    """Download + prep selected PD objects as a pack into _candidates.

    Large packs are parallelized (a few at a time) so the HTTP request finishes
    before browsers / proxies give up. Soft-caps selection size.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    objects = list(objects or [])
    if len(objects) > max_objects:
        raise ValueError(
            f"Too many selected ({len(objects)}). Import up to {max_objects} at a time, "
            "then add more in a second pack if needed."
        )

    slug = re.sub(r"[^a-z0-9]+", "_", (concept or "public_domain").strip().lower()).strip("_") or "public_domain"
    run_dir = os.path.join(runs_dir, slug)
    counter = 1
    while os.path.exists(run_dir):
        run_dir = os.path.join(runs_dir, f"{slug}_{counter}")
        counter += 1
    candidates_dir = os.path.join(run_dir, "_candidates")
    os.makedirs(candidates_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidates = []
    errors = []
    lock = __import__("threading").Lock()

    def _one(i, obj):
        oid = obj.get("object_id") or obj.get("objectID") or f"item{i}"
        try:
            img_url = obj.get("image") or obj.get("primaryImage")
            if not img_url:
                if obj.get("object_id") or obj.get("objectID"):
                    refreshed = fetch_met_object(obj.get("object_id") or obj.get("objectID"))
                    if refreshed:
                        obj = refreshed
                        img_url = obj.get("image")
            if not img_url:
                return None, {"object_id": oid, "error": "No image URL"}
            label = f"pd-{oid}"
            raw_path = os.path.join(candidates_dir, f"{ts}_{label}-{i}_raw.png")
            dest = os.path.join(candidates_dir, f"{ts}_{label}-{i}.png")
            download_image(img_url, raw_path)
            prep = prep_image_file(raw_path, dest, trim_borders=trim_borders)
            try:
                os.remove(raw_path)
            except OSError:
                pass

            art_title = (obj.get("title") or label).strip()
            file_stem = _safe_filename(art_title, label)
            with open(dest + ".json", "w", encoding="utf-8") as f:
                json.dump({**obj, "prep": prep, "file_stem": file_stem}, f, indent=2, ensure_ascii=False)

            return ({
                "label": label,
                "path": dest.replace("\\", "/"),
                "rel_path": None,
                "prompt": f"Public domain pack member: {art_title} — {obj.get('artist')} ({obj.get('rights')})",
                "model": "public-domain-met",
                "aspect": prep.get("aspect") or "4:5",
                "orientation": prep.get("orientation") or "portrait",
                "aspect_ratio": prep.get("aspect_ratio"),
                "attribution": obj,
                "art_title": art_title,
                "file_stem": file_stem,
                "product_type": "pd_bundle",
                "prep": prep,
            }, None)
        except Exception as e:
            return None, {"object_id": oid, "error": str(e)}

    workers = min(4, max(1, len(objects)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, i, obj): i for i, obj in enumerate(objects)}
        for fut in as_completed(futures):
            cand, err = fut.result()
            with lock:
                if cand:
                    candidates.append(cand)
                if err:
                    errors.append(err)

    # Stable order by original selection index (via label suffix) when possible
    candidates.sort(key=lambda c: c.get("label") or "")

    manifest = {
        "source": "met_open_access",
        "product_type": "pd_bundle",
        "concept": concept,
        "pack_title": concept,
        "imported_at": datetime.now().isoformat(),
        "count": len(candidates),
        "note": "Pack import — native aspects preserved. Verify Open Access before commercial use.",
        "orientations": {
            "portrait": sum(1 for c in candidates if c.get("orientation") == "portrait"),
            "landscape": sum(1 for c in candidates if c.get("orientation") == "landscape"),
            "square": sum(1 for c in candidates if c.get("orientation") == "square"),
        },
    }
    with open(os.path.join(run_dir, "public_domain_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return run_dir, candidates, errors, manifest
