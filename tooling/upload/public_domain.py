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
import urllib.parse
from datetime import datetime
from io import BytesIO

import requests

from pd_prep import classify_aspect, prep_image_file

MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}"
WIKI_API = "https://commons.wikimedia.org/w/api.php"
LOC_SEARCH = "https://www.loc.gov/search/"
LOC_FREE_TO_USE = "https://www.loc.gov/free-to-use/{slug}/"
UA = {"User-Agent": "AethelgardArtCo/1.2 (local production tool; public-domain research)"}
LOC_HEADERS = {
    **UA,
    "Accept": "application/json, text/plain, */*",
}

PD_IMPORT_MAX = 200
_LOC_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "loc_sets")

_LOC_SET_HINTS = (
    (("halloween", "autumn", "fall", "pumpkin", "harvest", "october"), "autumn-and-halloween"),
    (("cat", "cats", "kitten", "kittens", "feline"), "cats"),
    (("children", "childrens", "denslow", "wonderland", "aesop", "huckleberry"), "classic-childrens-books"),
    (("architecture", "architectural"), "architecture-and-design"),
    (("christmas", "nativity", "xmas"), "christmas"),
    (("map", "maps", "cartograph"), "maps"),
    (("president", "presidential"), "presidential-portraits"),
)
# Keyword searches that should never fall through to Met oil-painting noise.
_LOC_EXCLUSIVE_HINTS = {
    "halloween", "autumn", "fall", "october",
    "cat", "cats", "kitten", "kittens", "feline",
    "children", "childrens", "denslow", "wonderland", "aesop",
    "architecture", "architectural",
}
_LOC_ART_INTENT = {"oil", "painting", "canvas", "still", "portrait", "met", "museum"}

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
    # Produce: search still-life variants, but do NOT synonym to generic "still life"
    # (that would keep flower/fruit paintings when the user asked for vegetables).
    "vegetable": ["vegetables", "produce", "cabbage", "pumpkin", "squash", "onion"],
    "vegetables": ["vegetable", "produce", "cabbage", "pumpkin", "squash", "onion"],
    "produce": ["vegetable", "vegetables", "fruit"],
    "fruit": ["fruits", "apple", "grape", "peach", "pear"],
    "fruits": ["fruit", "apple", "grape", "peach"],
}

_PRODUCE_WORDS = (
    "vegetable", "vegetables", "produce", "cabbage", "pumpkin", "squash",
    "onion", "garlic", "tomato", "pepper", "carrot", "eggplant", "gourd",
    "corn", "maize", "radish", "asparagus", "artichoke", "leek", "turnip",
    "fruit", "fruits", "apple", "grape", "grapes", "peach", "pear", "lemon",
    "orange", "melon", "berry", "berries", "potato", "beet", "celery",
)

_VEGETABLE_SCORE_TERMS = (
    "vegetable", "vegetables", "produce", "cabbage", "pumpkin", "squash",
    "onion", "garlic", "tomato", "pepper", "carrot", "eggplant", "radish",
    "asparagus", "artichoke", "leek", "turnip", "gourd", "corn", "maize",
    "potato", "beet", "celery", "cucumber", "lettuce", "spinach",
)

_FRUIT_SCORE_TERMS = (
    "fruit", "fruits", "apple", "grape", "peach", "pear", "lemon",
    "orange", "melon", "berry", "berries",
)

_PRODUCE_SCORE_TERMS = _VEGETABLE_SCORE_TERMS + _FRUIT_SCORE_TERMS

_PRODUCE_COMMONS_NOISE = (
    "lccn", "statick", "hairdress", "selling their", "seed catalog",
    "seed catalogue",
)

OIL_ON_CANVAS = "oil on canvas"

_GENERIC_MATCH_TERMS = {
    "the", "and", "for", "with", "from", "art", "old", "new", "set", "pack",
    "print", "prints", "vintage", "antique", "open", "access", "public",
    "domain", "still", "life",
}

_ARTIFACT_NOISE = (
    "mask", "rattle", "amygdaloid", "lentoid", "ennanga", "harp", "dagger",
    "sword", "helmet", "snuffbox", "snuff-box", "stela", "staurotheke",
    "nkishi", "seal", "intaglio",
)


def _normalize_query(query):
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _query_words(words_or_q):
    if isinstance(words_or_q, str):
        return [w for w in re.split(r"[^a-z0-9]+", words_or_q.lower()) if w]
    return [str(w).lower() for w in (words_or_q or []) if w]


def _is_fungi_query(words_or_q):
    words = _query_words(words_or_q)
    return any(w in words for w in ("mushroom", "mushrooms", "fungi", "fungus", "toadstool", "agaric", "mycology"))


def _is_produce_query(words_or_q):
    words = _query_words(words_or_q)
    return any(w in words for w in _PRODUCE_WORDS)


def _is_fruit_query(words_or_q):
    words = _query_words(words_or_q)
    return any(w in words for w in (
        "fruit", "fruits", "apple", "grape", "grapes", "peach", "pear",
        "lemon", "berry", "berries",
    ))


def _is_still_life_query(words_or_q):
    words = set(_query_words(words_or_q))
    return "still" in words and "life" in words


def _plural_stem_variants(term):
    t = (term or "").strip().lower()
    if len(t) < 3:
        return []
    out = [t]
    if t.endswith("ies") and len(t) > 4:
        out.append(t[:-3] + "y")
    elif t.endswith("es") and len(t) > 4:
        out.append(t[:-2])
    elif t.endswith("s") and len(t) > 4:
        out.append(t[:-1])
    else:
        out.append(t + "s")
    return out


def expand_search_queries(query, max_variants=14):
    """Build Met search variants when the exact phrase is too narrow."""
    q = _normalize_query(query)
    if not q:
        return []
    variants = [q]
    words = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) >= 3]

    preferred = [f"{q} oil painting"]
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
    elif _is_produce_query(words):
        fruit_only = any(w in words for w in (
            "fruit", "fruits", "apple", "grape", "grapes", "peach", "pear",
            "lemon", "berry", "berries",
        )) and not any(w in words for w in ("vegetable", "vegetables", "produce"))
        if fruit_only:
            preferred.extend([
                "fruit still life", "still life fruit", "fruit",
                "apple still life", "grapes", "peach",
            ])
        else:
            preferred.extend([
                "vegetable still life", "still life vegetables", "vegetables",
                "cabbage", "pumpkin", "squash", "onion", "corn still life",
            ])
    elif _is_still_life_query(words):
        preferred.extend(["still life", "still-life painting", "natura morta"])
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
    search_q = f'{q} "oil on canvas" painting filetype:bitmap'

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
            "tags": [],
            "credit": "Wikimedia Commons",
            "rights": f"{rights} (verify before commercial use)",
            "object_url": f"https://commons.wikimedia.org/wiki/File:{title.replace(' ', '_')}",
            "image": url,
            "image_small": thumb,
        })
        if len(out) >= limit:
            break
    return out


def _extract_source_url(query):
    text = query or ""
    m = re.search(r"https?://[^\s<>\"']+", text, re.I)
    if m:
        return m.group(0).rstrip(".,);")
    m = re.search(r"(?:www\.)?loc\.gov/[^\s<>\"']+", text, re.I)
    if m:
        return "https://" + m.group(0).lstrip("/")
    return ""


def _loc_free_to_use_slug(url):
    m = re.search(r"/free-to-use/([^/?#]+)/?", url or "", re.I)
    slug = (m.group(1) or "").strip().lower() if m else ""
    return re.sub(r"[^a-z0-9-]", "", slug)


def _loc_set_slug_for_query(query):
    words = set(_query_words(query))
    for hints, slug in _LOC_SET_HINTS:
        if words & set(hints):
            return slug
    return ""


def _loc_query_is_exclusive_set(query):
    """Use a local LOC catalog when we have one — never Met junk for those queries."""
    words = set(_query_words(query))
    if words & _LOC_ART_INTENT:
        return False
    slug = _loc_set_slug_for_query(query)
    if slug and os.path.isfile(os.path.join(_LOC_DATA_DIR, f"{slug}.json")):
        return True
    return bool(words & _LOC_EXCLUSIVE_HINTS)


def _abs_loc_url(url):
    u = (url or "").strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return "https://www.loc.gov" + u
    return u


def _loc_best_image(item):
    urls = item.get("image_url") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [_abs_loc_url(u) for u in urls if u]
    if urls:
        return urls[-1], urls[0]
    resources = item.get("resources") or []
    if isinstance(resources, list):
        for res in reversed(resources):
            if not isinstance(res, dict):
                continue
            for key in ("url", "image", "full_image"):
                cand = _abs_loc_url(res.get(key) or "")
                if cand.startswith("http"):
                    return cand, cand
    inner = item.get("item") or {}
    if isinstance(inner, dict):
        for key in ("image_url", "url"):
            val = inner.get(key)
            if isinstance(val, list) and val:
                u = _abs_loc_url(val[-1])
                return u, _abs_loc_url(val[0])
            if isinstance(val, str) and val.startswith("http"):
                return val, val
    return "", ""


def _loc_rights_ok(item):
    if item.get("access_restricted") is True:
        return False
    inner = item.get("item") if isinstance(item.get("item"), dict) else {}
    if inner.get("access_restricted") is True:
        return False
    blob = " ".join([
        str(item.get("rights") or ""),
        str(inner.get("rights_advisory") or ""),
        str(inner.get("rights") or ""),
        str(inner.get("restriction") or ""),
    ]).lower()
    if any(x in blob for x in ("all rights reserved", "in copyright", "rights restricted")):
        return False
    return True


def _loc_card_from_item(item, source="loc"):
    if not isinstance(item, dict):
        return None
    if not _loc_rights_ok(item):
        return None
    image, thumb = _loc_best_image(item)
    if not image:
        return None
    inner = item.get("item") if isinstance(item.get("item"), dict) else {}
    title = (item.get("title") or inner.get("title") or "Library of Congress item")
    if isinstance(title, list):
        title = title[0] if title else "Library of Congress item"
    title = str(title).strip()
    creators = inner.get("creators") or item.get("contributor") or []
    if isinstance(creators, list) and creators:
        artist = str(creators[0].get("title") if isinstance(creators[0], dict) else creators[0])
    else:
        artist = str(creators or inner.get("created_published") or "Unknown")
    artist = re.sub(r"\s+", " ", artist).strip()[:120] or "Unknown"
    medium = inner.get("medium") or item.get("original_format") or ""
    if isinstance(medium, list):
        medium = ", ".join(str(m) for m in medium[:3])
    loc_id = item.get("id") or inner.get("id") or title
    slug = re.sub(r"[^a-z0-9]+", "-", str(loc_id).lower())[:48].strip("-") or "loc"
    object_url = item.get("url") or item.get("id") or ""
    object_url = _abs_loc_url(str(object_url))
    if object_url.startswith("http://"):
        object_url = "https://" + object_url[len("http://"):]
    return {
        "source": source,
        "object_id": f"loc-{slug}",
        "title": title,
        "artist": artist,
        "date": str((inner.get("date") or item.get("date") or "")),
        "department": "Library of Congress",
        "medium": str(medium or ""),
        "classification": "",
        "object_name": "",
        "tags": [],
        "credit": "Library of Congress",
        "rights": "Library of Congress — verify rights before commercial use",
        "object_url": object_url or image,
        "image": image,
        "image_small": thumb or image,
    }


def _loc_portal_file(image_url):
    m = re.search(r"/public-domain/([^/]+)/([^/?#]+)$", image_url or "", re.I)
    if not m:
        return "", ""
    return m.group(1).lower(), m.group(2)


def _loc_local_file(slug, filename):
    if not slug or not filename:
        return ""
    if not re.match(r"^[\w.-]+\.(jpe?g|png|webp)$", filename, re.I):
        return ""
    path = os.path.join(_LOC_DATA_DIR, slug, filename)
    return path if os.path.isfile(path) else ""


def _loc_preview_url(image_url):
    """Same-origin preview so loc.gov Cloudflare does not blank the grid."""
    slug, fname = _loc_portal_file(image_url)
    if slug and fname:
        local = _loc_local_file(slug, fname)
        ver = int(os.path.getmtime(local)) if local else 0
        return (
            f"/api/public_domain/image?set={urllib.parse.quote(slug)}"
            f"&file={urllib.parse.quote(fname)}&v={ver}"
        )
    if image_url and "loc.gov" in image_url.lower():
        return f"/api/public_domain/image?u={urllib.parse.quote(image_url, safe='')}"
    return image_url or ""


_COMMONS_STOP = {
    "this", "that", "with", "from", "photo", "poster", "print", "file",
    "near", "vicinity", "county", "united", "states", "color", "array",
    "ready", "scene", "rural", "between", "approximately",
}


def _loc_resource_id(link):
    m = re.search(r"/resource/([^/?#]+)", link or "", re.I)
    if not m:
        return ""
    rid = (m.group(1) or "").strip().rstrip("/")
    # gottlieb.10861.0 / sm1874.15744.0 — trailing .0 is a page index
    if rid.count(".") >= 2 and re.search(r"\.\d+$", rid):
        rid = re.sub(r"\.\d+$", "", rid)
    return rid


def _loc_iiif_page(link):
    m = re.search(r"[?&]sp=(\d+)", link or "")
    return f"{int(m.group(1)):04d}" if m else "0001"


def _loc_padded_dirs(ident, cuts):
    width = len(ident or "")
    dirs = []
    for n in cuts:
        if 0 < n < width:
            dirs.append(ident[:n] + "0" * (width - n))
    return dirs


def _loc_iiif_jpeg(spec):
    return f"https://tile.loc.gov/image-services/iiif/{spec}/full/800,/0/default.jpg"


def _loc_tile_urls(resource_id, link=""):
    """Candidate JPEG URLs on tile.loc.gov (not Cloudflare-gated www.loc.gov)."""
    rid = (resource_id or _loc_resource_id(link) or "").strip().rstrip("/")
    if not rid or "." not in rid:
        return []
    coll, ident = rid.split(".", 1)
    coll, ident = coll.lower(), ident.strip()
    if not coll or not ident:
        return []
    urls = []
    page = _loc_iiif_page(link)
    is_book = coll.startswith("rbc") or coll in {"gdcmassbookdig", "dcmsiabooks"}

    if coll.startswith("rbc"):
        urls.append(_loc_iiif_jpeg(f"public:rbc:{ident}:{page}"))
        if page == "0001":
            urls.append(_loc_iiif_jpeg(f"public:rbc:{ident}:001"))
    if coll in {"gdcmassbookdig", "dcmsiabooks"}:
        urls.append(_loc_iiif_jpeg(f"public:{coll}:{ident}:{ident}_{page}"))
        if page != "0001":
            urls.append(_loc_iiif_jpeg(f"public:{coll}:{ident}:{ident}_0001"))
    if coll == "gottlieb":
        urls.append(_loc_iiif_jpeg(f"public:music:musgottlieb-{ident}:{page}"))
    if coll == "mcc":
        urls.append(_loc_iiif_jpeg(f"service:mss:mssmcc:{ident}:{page}"))

    if not is_book:
        pnp = []
        if ident.isdigit():
            for bucket in (100, 1000):
                group = str((int(ident) // bucket) * bucket).zfill(len(ident))
                pnp.append(f"{coll}/{group}/{ident}")
                pnp.append(f"{coll}/{group}/{ident}/{ident}")
        else:
            cut_order = ((3, 4, 5), (4, 5), (4, 5, 6)) if coll == "cph" else ((4, 5), (3, 4, 5), (4, 5, 6))
            for cuts in cut_order:
                dirs = _loc_padded_dirs(ident, cuts)
                if dirs:
                    pnp.append(f"{coll}/{'/'.join(dirs)}/{ident}")
        seen_pnp = set()
        for path in pnp:
            if path in seen_pnp:
                continue
            seen_pnp.add(path)
            urls.append(f"https://tile.loc.gov/storage-services/service/pnp/{path}r.jpg")
        for path in pnp:
            urls.append(f"https://tile.loc.gov/storage-services/service/pnp/{path}v.jpg")

    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:8]


def _http_image_bytes(url, timeout=8):
    try:
        r = requests.get(
            url,
            headers={**UA, "Accept": "image/jpeg,image/*,*/*;q=0.8"},
            timeout=timeout,
        )
    except Exception:
        return b""
    ctype = (r.headers.get("Content-Type") or "").lower()
    data = r.content or b""
    if r.status_code != 200 or "html" in ctype or len(data) < 800:
        return b""
    if data.lstrip()[:15].lower().startswith(b"<!doctype"):
        return b""
    return data


def _loc_fetch_tile_bytes(resource_id, link=""):
    for url in _loc_tile_urls(resource_id, link):
        data = _http_image_bytes(url, timeout=6)
        if data:
            return data
    return b""


def _significant_words(text):
    return {
        w for w in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(w) >= 4 and w not in _COMMONS_STOP
    }


def _commons_search_pages(query):
    q = (query or "").strip()
    if not q:
        return {}
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{q} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": 800,
        "origin": "*",
    }
    for attempt in range(2):
        try:
            r = requests.get(WIKI_API, params=params, headers=UA, timeout=8)
            if r.status_code == 429 or not (r.text or "").lstrip().startswith("{"):
                time.sleep(0.6 * (attempt + 1))
                continue
            r.raise_for_status()
            return ((r.json() or {}).get("query") or {}).get("pages") or {}
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return {}


def _loc_caption_head(title):
    text = re.sub(r"\s+", " ", title or "").strip()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    return re.split(
        r"\.\s+(?:Photo|Poster|Broadside|Lithograph|Woodcut|Color photo|Theatrical|Magazine|Composed)",
        text,
        maxsplit=1,
    )[0].strip()


def _loc_caption_artist(title):
    m = re.search(
        r"(?:Photo|Poster|Lithograph|Woodcut|Broadside)(?: by)?\s+([^.\[]+)",
        title or "",
        re.I,
    )
    if not m:
        return ""
    artist = re.sub(r"\s+", " ", m.group(1)).strip()
    artist = re.split(r",\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d)", artist)[0]
    return artist.strip(" ,")


def _loc_commons_queries(title, resource_id):
    queries = []
    rid = (resource_id or "").split("/")[0].strip()
    if rid and re.search(r"[a-z]", rid, re.I):
        queries.append(rid)
    head = _loc_caption_head(title)
    artist = _loc_caption_artist(title)
    skip = _COMMONS_STOP | {"autumn", "halloween"}
    words = [
        w for w in re.split(r"[^a-zA-Z0-9]+", head)
        if len(w) >= 4 and w.lower() not in skip
    ]
    if not rid and head:
        queries.append(f"{head} book")
    if artist and words:
        queries.append(f"{artist} {' '.join(words[:6])}")
    if words:
        queries.append(" ".join(words[:8]))
    if artist and len(words) >= 2:
        queries.append(f"{artist} {words[0]} {words[1]}")
    out, seen = [], set()
    for q in queries:
        key = q.lower()
        if key in seen or len(q) < 4:
            continue
        seen.add(key)
        out.append(q)
    return out[:3]


def _commons_thumb_for_loc_item(title, resource_id=""):
    loc_words = _significant_words(title)
    best = ("", 0)
    for query in _loc_commons_queries(title, resource_id):
        for page in _commons_search_pages(query).values():
            commons_title = page.get("title") or ""
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = (info.get("mime") or "").lower()
            if mime in ("image/svg+xml", "image/gif") or mime.endswith("pdf"):
                continue
            thumb = (info.get("thumburl") or info.get("url") or "").split("?")[0]
            if not thumb.startswith("http") or thumb.lower().endswith(".pdf"):
                continue
            score = len(loc_words & _significant_words(commons_title))
            rid = (resource_id or "").split("/")[0].lower()
            blob = commons_title.lower().replace(" ", "")
            if rid and rid in commons_title.lower():
                score += 8
            elif rid and rid.replace(".", "") and rid.replace(".", "") in blob.replace(".", ""):
                score += 5
            if mime.startswith("image/jpeg"):
                score += 1
            if score > best[1]:
                best = (thumb, score)
        time.sleep(0.08)
    need = 2 if len(loc_words) <= 5 else 3
    return best[0] if best[1] >= need else ""


def _write_placeholder_jpeg(title, dest_path):
    """Compact title card that stays readable in the 100px grid crop."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (480, 120), (92, 72, 42))
    draw = ImageDraw.Draw(im)
    text = re.sub(r"\s+", " ", title or "Library of Congress").strip()[:120]
    lines, line = [], ""
    for word in text.split(" "):
        trial = (line + " " + word).strip()
        if len(trial) > 38:
            if line:
                lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    y = 10
    for row in lines[:4]:
        draw.text((12, y), row, fill=(244, 228, 196))
        y += 26
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    im.save(dest_path, format="JPEG", quality=82)
    return dest_path


def _is_loc_placeholder(path):
    if not os.path.isfile(path) or os.path.getsize(path) < 800:
        return True
    try:
        from PIL import Image
        with Image.open(path) as im:
            size = im.size
        return size in {(640, 400), (480, 120)} and os.path.getsize(path) < 25000
    except Exception:
        return True


def hydrate_loc_set_thumbs(slug, write_placeholders=False):
    """Download reachable previews for a cached loc.gov free-to-use set."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from PIL import Image

    catalog = os.path.join(_LOC_DATA_DIR, f"{slug}.json")
    if not os.path.isfile(catalog):
        return 0
    try:
        with open(catalog, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return 0

    def _one(item):
        raw = _abs_loc_url(item.get("image") or "")
        set_slug, fname = _loc_portal_file(raw)
        set_slug = set_slug or slug
        link = item.get("link") or ""
        if "guides.loc.gov" in link.lower():
            return 0
        if not fname:
            rid = _loc_resource_id(link)
            if not rid:
                return 0
            fname = re.sub(r"[^a-z0-9.-]+", "-", rid.lower()).strip("-") + ".jpg"
        dest = os.path.join(_LOC_DATA_DIR, set_slug, fname)
        if not _is_loc_placeholder(dest):
            return 0
        data = _loc_fetch_tile_bytes(_loc_resource_id(link), link)
        if not data:
            url = _commons_thumb_for_loc_item(item.get("title") or "", _loc_resource_id(link))
            if url:
                data = _http_image_bytes(url, timeout=12)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if data:
            try:
                im = Image.open(BytesIO(data)).convert("RGB")
                im.thumbnail((900, 900))
                im.save(dest, format="JPEG", quality=85)
                print(f"loc {set_slug} +{fname}", flush=True)
                return 1
            except Exception:
                pass
        print(f"loc {set_slug} miss {fname}", flush=True)
        if write_placeholders:
            _write_placeholder_jpeg(item.get("title") or fname, dest)
            return 1
        return 0

    items = payload.get("items") or []
    wrote = 0
    workers = min(8, max(1, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, item) for item in items]
        for fut in as_completed(futs):
            try:
                wrote += int(fut.result() or 0)
            except Exception:
                pass
    return wrote


def resolve_pd_image_bytes(set_slug="", filename="", source_url=""):
    """Load a cached loc preview, or fetch a non-loc URL. Returns (bytes, mime)."""
    slug = re.sub(r"[^a-z0-9_-]", "", (set_slug or "").lower())
    fname = os.path.basename(filename or "")
    local = _loc_local_file(slug, fname)
    if not local and source_url:
        pslug, pfname = _loc_portal_file(source_url)
        local = _loc_local_file(pslug, pfname)
        slug, fname = pslug, pfname
    if local:
        with open(local, "rb") as f:
            data = f.read()
        mime = "image/jpeg"
        if fname.lower().endswith(".png"):
            mime = "image/png"
        elif fname.lower().endswith(".webp"):
            mime = "image/webp"
        return data, mime
    return b"", ""


def _loc_card_from_masonry(item, source="loc_free_to_use"):
    """Cards from loc.gov free-to-use masonry galleries (image/link/title)."""
    if not isinstance(item, dict):
        return None
    raw_image = _abs_loc_url(item.get("image") or item.get("image_fallback") or "")
    if not raw_image:
        return None
    title = str(item.get("title") or "Library of Congress item").strip()
    link = _abs_loc_url(item.get("link") or item.get("url") or "")
    if "guides.loc.gov" in link.lower():
        return None
    stem = (link or raw_image).rstrip("/").split("/")[-1] or title
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower())[:48].strip("-") or "loc"
    fallback = _abs_loc_url(item.get("image_fallback") or "")
    preview = _loc_preview_url(raw_image)
    set_slug, fname = _loc_portal_file(raw_image)
    local = _loc_local_file(set_slug, fname)
    has_preview = bool(local) and not _is_loc_placeholder(local)
    return {
        "source": source,
        "object_id": f"loc-{slug}",
        "title": title,
        "artist": "Library of Congress",
        "date": "",
        "department": "Library of Congress",
        "medium": "",
        "classification": "",
        "object_name": "",
        "tags": [],
        "credit": "Library of Congress free-to-use set",
        "rights": "Library of Congress free-to-use — verify before commercial use",
        "object_url": link or raw_image,
        "image": preview,
        "image_small": preview,
        "image_fallback": fallback,
        "loc_source_image": raw_image,
        "loc_resource": _loc_resource_id(link),
        "has_preview": has_preview,
    }


def _loc_masonry_items_from_payload(data):
    """Gallery rows from a loc.gov free-to-use ?fo=json payload.

    Current portal JSON uses content.set.items. Older pages used masonry_gallery.
    Do not walk next/previous sibling sets — those are other galleries.
    """
    if not isinstance(data, dict):
        return []

    def items_from_set_block(block):
        if not isinstance(block, dict):
            return []
        st = block.get("set")
        if isinstance(st, dict) and isinstance(st.get("items"), list):
            return [x for x in st["items"] if isinstance(x, dict) and (x.get("image") or x.get("link"))]
        return []

    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    found = items_from_set_block(content)
    if found:
        return found

    masonry = []

    def walk_masonry(node, depth=0):
        if depth > 10 or masonry:
            return
        if isinstance(node, dict):
            galleries = node.get("masonry_gallery")
            if isinstance(galleries, list):
                for gallery in galleries:
                    if isinstance(gallery, dict) and isinstance(gallery.get("items"), list):
                        masonry.extend(
                            x for x in gallery["items"]
                            if isinstance(x, dict) and (x.get("image") or x.get("link"))
                        )
                        if masonry:
                            return
            for key, val in node.items():
                if key in {"next", "previous", "next_sibling", "previous_sibling"}:
                    continue
                walk_masonry(val, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk_masonry(item, depth + 1)

    walk_masonry(content or data)
    return masonry


def _loc_cards_from_cached_set(slug):
    if not slug:
        return []
    path = os.path.join(_LOC_DATA_DIR, f"{slug}.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    out = []
    seen = set()
    for item in payload.get("items") or []:
        card = _loc_card_from_masonry(item, source="loc_free_to_use")
        if not card:
            continue
        if not card.get("has_preview"):
            continue
        key = card.get("object_id")
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def ingest_loc_free_to_use_set(slug):
    """Download a loc.gov free-to-use gallery catalog and cache it locally."""
    slug = re.sub(r"[^a-z0-9-]", "", (slug or "").lower())
    if not slug:
        return 0
    url = LOC_FREE_TO_USE.format(slug=slug)
    try:
        data = _loc_get_json(url)
    except Exception:
        return 0
    raw_items = _loc_masonry_items_from_payload(data)
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    title = str(content.get("title") or data.get("title") or slug.replace("-", " ")).strip()
    items = []
    seen = set()
    for it in raw_items:
        image = _abs_loc_url(it.get("image") or it.get("image_fallback") or "")
        link = _abs_loc_url(it.get("link") or it.get("url") or "")
        if not image and not link:
            continue
        key = link or image
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": str(it.get("title") or "Library of Congress item").strip(),
            "image": image,
            "link": link,
        })
    if not items:
        return 0
    os.makedirs(_LOC_DATA_DIR, exist_ok=True)
    path = os.path.join(_LOC_DATA_DIR, f"{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"slug": slug, "url": url, "title": title, "items": items}, f, indent=2)
        f.write("\n")
    return len(items)


def ensure_loc_free_to_use_set(slug):
    """Return downloadable cards for any free-to-use slug, ingesting on first use."""
    slug = re.sub(r"[^a-z0-9-]", "", (slug or "").lower())
    if not slug:
        return []
    catalog = os.path.join(_LOC_DATA_DIR, f"{slug}.json")
    if not os.path.isfile(catalog):
        ingest_loc_free_to_use_set(slug)
    cards = _loc_cards_from_cached_set(slug)
    catalog_n = 0
    try:
        with open(os.path.join(_LOC_DATA_DIR, f"{slug}.json"), encoding="utf-8") as f:
            catalog_n = len((json.load(f) or {}).get("items") or [])
    except Exception:
        catalog_n = 0
    if not cards or (catalog_n and len(cards) < min(8, catalog_n)):
        hydrate_loc_set_thumbs(slug, False)
        cards = _loc_cards_from_cached_set(slug)
    return cards


def _finish_direct_cards(cards, offset, limit, note, query_label):
    total_ranked = len(cards)
    results = cards[offset: offset + limit]
    meta = {
        "queries_tried": [query_label],
        "query_totals": [{"q": query_label, "total": total_ranked}],
        "expanded": False,
        "offset": offset,
        "limit": limit,
        "total_ranked": total_ranked,
        "has_more": (offset + limit) < total_ranked,
        "pool_ids": total_ranked,
        "note": note,
    }
    return results, meta


def _loc_json_url(url, count=80):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    qs["fo"] = ["json"]
    path = (parsed.path or "").lower()
    if "/free-to-use/" not in path:
        qs["c"] = [str(count)]
    new_q = urllib.parse.urlencode(qs, doseq=True)
    return urllib.parse.urlunparse(parsed._replace(query=new_q, fragment=""))


def _loc_wayback_json_url(url):
    target = _loc_json_url(url)
    if target.startswith("http://"):
        target = "https://" + target[len("http://"):]
    return "https://web.archive.org/web/2id_/" + target


def _loc_parse_json_response(resp):
    if resp is None:
        return {}
    text = (resp.text or "").lstrip()
    if resp.status_code != 200 or not (text.startswith("{") or text.startswith("[")):
        return {}
    try:
        return resp.json() or {}
    except Exception:
        return {}


def _loc_get_json(url):
    """Load loc.gov JSON. Direct requests are often Cloudflare-blocked; Wayback is the fallback."""
    target = _loc_json_url(url)
    try:
        r = requests.get(target, headers=LOC_HEADERS, timeout=20)
        data = _loc_parse_json_response(r)
        if data:
            return data
    except Exception:
        pass
    r = requests.get(_loc_wayback_json_url(url), headers=LOC_HEADERS, timeout=45)
    data = _loc_parse_json_response(r)
    if not data:
        raise RuntimeError("Library of Congress returned HTML instead of JSON (blocked or not an API page).")
    return data


def _loc_items_from_payload(data):
    found = []

    def walk(node, depth=0):
        if depth > 8 or len(found) > 120:
            return
        if isinstance(node, dict):
            has_img = bool(node.get("image_url"))
            link = str(node.get("link") or node.get("id") or node.get("url") or "")
            if has_img or "/item/" in link:
                found.append(node)
                return
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for x in node:
                walk(x, depth + 1)

    if isinstance(data, dict):
        walk(data)
    return found


def _loc_item_ids_from_html(html):
    ids = []
    seen = set()
    for m in re.finditer(r"/item/([a-zA-Z0-9_./-]+)/", html or ""):
        iid = m.group(1).strip("/")
        if not iid or iid in seen or "/" in iid:
            continue
        seen.add(iid)
        ids.append(iid)
    return ids[:80]


def _loc_cards_from_html(url, limit, source):
    page = url.split("?")[0]
    try:
        r = requests.get(page, headers={**LOC_HEADERS, "Accept": "text/html,application/xhtml+xml"}, timeout=45)
        r.raise_for_status()
        html = r.text or ""
    except Exception:
        return []
    ids = _loc_item_ids_from_html(html)
    out = []
    seen = set()

    def _one(iid):
        try:
            data = _loc_get_json(f"https://www.loc.gov/item/{iid}/")
        except Exception:
            return None
        item = data.get("item") if isinstance(data.get("item"), dict) else data
        return _loc_card_from_item(item if isinstance(item, dict) else data, source=source)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_one, iid) for iid in ids[:limit]]
        for fut in as_completed(futs):
            card = fut.result()
            if not card:
                continue
            key = card.get("object_id")
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= limit:
                break
    return out


def _loc_cards_from_page(url, limit, source):
    slug = _loc_free_to_use_slug(url)
    if slug:
        return ensure_loc_free_to_use_set(slug)[:limit]
    out = []
    seen = set()
    try:
        data = _loc_get_json(url)
        for item in _loc_masonry_items_from_payload(data):
            card = _loc_card_from_masonry(item, source=source)
            if not card:
                continue
            key = card.get("object_id")
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= limit:
                return out
        for item in _loc_items_from_payload(data):
            card = _loc_card_from_item(item, source=source)
            if not card:
                # JSON may only have /item/ links — resolve those
                link = str(item.get("link") or item.get("id") or item.get("url") or "")
                m = re.search(r"/item/([a-zA-Z0-9_.-]+)/?", link)
                if m:
                    try:
                        nested = _loc_get_json(f"https://www.loc.gov/item/{m.group(1)}/")
                        inner = nested.get("item") if isinstance(nested.get("item"), dict) else nested
                        card = _loc_card_from_item(inner, source=source)
                    except Exception:
                        card = None
            if not card:
                continue
            key = card.get("object_id")
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= limit:
                return out
    except Exception:
        pass
    if len(out) < max(4, limit // 4):
        html_cards = _loc_cards_from_html(url, limit, source)
        for card in html_cards:
            key = card.get("object_id")
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= limit:
                break
    return out


def search_loc(query, limit=48):
    """Search Library of Congress digital collections / free-to-use sets."""
    q = _normalize_query(query)
    if not q:
        return []
    limit = max(1, min(int(limit or 48), 96))
    urls = []
    source_url = _extract_source_url(query)
    if source_url and "loc.gov" in source_url.lower():
        urls.append(source_url)
    else:
        words = set(_query_words(q))
        for hints, slug in _LOC_SET_HINTS:
            if words & set(hints):
                urls.append(LOC_FREE_TO_USE.format(slug=slug))
                break
        urls.append(
            f"{LOC_SEARCH}?q={urllib.parse.quote(q)}&fa=online-format:image&fo=json&c={max(limit, 40)}"
        )
    seen = set()
    out = []
    for url in urls:
        source = "loc_free_to_use" if "/free-to-use/" in url else "loc"
        for card in _loc_cards_from_page(url, limit=limit, source=source):
            key = card.get("object_id")
            if key in seen:
                continue
            seen.add(key)
            out.append(card)
            if len(out) >= limit:
                return out
        time.sleep(0.05)
    return out


def search_from_url(url, limit=48):
    """Turn a pasted loc.gov / Met / Commons / image URL into result cards."""
    url = (url or "").strip()
    if not url:
        return []
    low = url.lower()
    if "loc.gov" in low:
        return search_loc(url, limit=limit)
    if "metmuseum.org" in low:
        m = re.search(r"/search/(\d+)", url)
        if m:
            card = fetch_met_object(m.group(1))
            return [card] if card else []
    if "commons.wikimedia.org" in low and "File:" in url:
        name = url.split("File:", 1)[-1]
        name = urllib.parse.unquote(name).replace("_", " ")
        return search_wikimedia_commons(name.rsplit(".", 1)[0], limit=min(limit, 8))
    if re.search(r"\.(jpe?g|png|webp)(\?|$)", low):
        stem = url.rsplit("/", 1)[-1].split("?", 1)[0]
        return [{
            "source": "url",
            "object_id": f"url-{re.sub(r'[^a-z0-9]+', '-', stem.lower())[:40]}",
            "title": stem.rsplit(".", 1)[0] or "Pasted image",
            "artist": "Unknown",
            "date": "",
            "department": "Pasted URL",
            "medium": "",
            "tags": [],
            "credit": url,
            "rights": "Verify license before commercial use",
            "object_url": url,
            "image": url,
            "image_small": url,
        }]
    return []


def _tag_text(card):
    tags = card.get("tags") or []
    if isinstance(tags, list):
        return " ".join(str(t) for t in tags if t)
    return str(tags)


def _card_blob(card):
    return " ".join([
        card.get("title") or "",
        card.get("artist") or "",
        card.get("department") or "",
        card.get("medium") or "",
        card.get("date") or "",
        card.get("object_name") or "",
        card.get("classification") or "",
        _tag_text(card),
    ]).lower()


def _specific_match_terms(query_terms, score_terms):
    terms = []
    seen = set()
    for t in list(query_terms or []) + list(score_terms or []):
        for part in _plural_stem_variants(t):
            if part not in seen:
                seen.add(part)
                terms.append(part)
    return [t for t in terms if t not in _GENERIC_MATCH_TERMS and len(t) >= 4]


def _term_in_blob(term, blob):
    t = (term or "").strip().lower()
    if len(t) < 3:
        return False
    if len(t) <= 4:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", blob))
    return t in blob


def _normalized_medium_text(text):
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    return s.rstrip(".")


def _is_oil_on_canvas(card, query_terms=None):
    """Keep Met/Commons works whose medium is exactly 'Oil on canvas'.

    Library of Congress and pasted loc.gov links are exempt — those sets are
    mixed media (prints, posters, photos) by design.
    """
    src = (card.get("source") or "")
    if src.startswith("loc") or src == "url":
        return True
    medium = _normalized_medium_text(card.get("medium") or "")
    if medium == OIL_ON_CANVAS:
        return True
    if src == "wikimedia_commons":
        blob = f"{card.get('title') or ''} {card.get('medium') or ''}".lower()
        return OIL_ON_CANVAS in blob
    return False


def _is_flat_artwork(card, query_terms=None):
    return _is_oil_on_canvas(card, query_terms)


def _is_relevant_card(card, query_terms, score_terms, min_score=8, require_term=False, produce_mode=False):
    """Drop Met keyword-noise and anything that is not oil on canvas."""
    if not _is_oil_on_canvas(card, query_terms):
        return False
    if (card.get("source") or "").startswith("loc") or (card.get("source") or "") == "url":
        return True
    if produce_mode:
        title = (card.get("title") or "").lower()
        q_blob = " ".join(query_terms or [])
        if (card.get("source") or "") == "wikimedia_commons":
            if any(k in title for k in _PRODUCE_COMMONS_NOISE):
                return False
        for kw in ("teapot", "clock", "watch", "snuffbox"):
            if kw in title and kw not in q_blob:
                return False
    specific = _specific_match_terms(query_terms, score_terms)
    if not specific:
        return True
    blob = _card_blob(card)
    if any(_term_in_blob(t, blob) for t in specific):
        return True
    if require_term:
        return False
    return int(card.get("_score") or 0) >= min_score


def _score_card(card, query_terms, source_query="", fungi_mode=False, produce_mode=False):
    hay = _card_blob(card)
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
    elif produce_mode:
        if any(k in src for k in ("vegetable", "still life", "produce", "cabbage", "pumpkin", "fruit")):
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
    if produce_mode:
        qset = set(query_terms or [])
        veg_asked = bool(qset & set(_VEGETABLE_SCORE_TERMS))
        fruit_asked = _is_fruit_query(query_terms)
        if veg_asked and fruit_asked:
            hit_terms = _PRODUCE_SCORE_TERMS
        elif fruit_asked and not veg_asked:
            hit_terms = _FRUIT_SCORE_TERMS
        else:
            hit_terms = _VEGETABLE_SCORE_TERMS
        for kw in hit_terms:
            if kw in title:
                score += 12
            elif kw in hay:
                score += 6
        if "still life" in title or "still-life" in title:
            score += 4
        if (card.get("source") or "") == "met":
            score += 4
        if any(k in title for k in _PRODUCE_COMMONS_NOISE):
            score -= 10
    q_blob = " ".join(query_terms or []).lower()
    for kw in _ARTIFACT_NOISE:
        if kw in q_blob:
            continue
        if kw in title:
            score -= 12
        elif kw in hay:
            score -= 4
    dept = (card.get("department") or "").lower()
    medium = _normalized_medium_text(card.get("medium") or "")
    classif = (card.get("classification") or "").lower()
    if medium == OIL_ON_CANVAS:
        score += 10
    if "paintings" in dept or "paintings" in classif:
        score += 3
    if any(k in dept for k in ("arms", "armor", "musical", "costume", "egyptian art", "islamic art")):
        score -= 4
    if "rockefeller" in dept:
        score -= 5
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

    source_url = _extract_source_url(query)
    if source_url:
        slug = _loc_free_to_use_slug(source_url)
        cards = ensure_loc_free_to_use_set(slug) if slug else []
        if not cards:
            cards = search_from_url(source_url, limit=min(96, offset + limit + 12))
        if not cards:
            note = (
                f"No images from that link ({source_url}). "
                "This was not a Met keyword search. loc.gov blocks this app; "
                "free-to-use galleries are loaded from a snapshot and cached locally on first use."
            )
            empty = _finish_direct_cards([], offset, limit, note, source_url)
            return empty if return_meta else []
        note = "Sourced from your pasted link — verify license before commercial use."
        if any((c.get("source") or "").startswith("loc") for c in cards):
            note = (
                f"Library of Congress free-to-use set — {len(cards)} images ready to import as one bundle. "
                "Not a Met oil-painting search."
            )
        results, meta = _finish_direct_cards(cards, offset, limit, note, source_url)
        return (results, meta) if return_meta else results

    loc_slug = _loc_set_slug_for_query(q)
    if loc_slug and _loc_query_is_exclusive_set(q):
        loc_url = LOC_FREE_TO_USE.format(slug=loc_slug)
        cards = ensure_loc_free_to_use_set(loc_slug)
        if cards:
            note = (
                f"Library of Congress free-to-use set ({loc_slug.replace('-', ' ')}) — "
                f"{len(cards)} images ready to import as one bundle. "
                "This is not a Met oil-on-canvas search."
            )
            results, meta = _finish_direct_cards(cards, offset, limit, note, loc_url)
            return (results, meta) if return_meta else results
        note = (
            f"Could not load the Library of Congress {loc_slug.replace('-', ' ')} set, "
            "and Met was not searched (those results would be unrelated oil paintings)."
        )
        empty = _finish_direct_cards([], offset, limit, note, loc_url)
        return empty if return_meta else []

    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", q):
        loc_url = LOC_FREE_TO_USE.format(slug=q)
        cards = ensure_loc_free_to_use_set(q)
        if cards:
            note = (
                f"Library of Congress free-to-use set ({q.replace('-', ' ')}) — "
                f"{len(cards)} images ready to import as one bundle. "
                "This is not a Met oil-on-canvas search."
            )
            results, meta = _finish_direct_cards(cards, offset, limit, note, loc_url)
            return (results, meta) if return_meta else results

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
    produce_mode = (not fungi_mode) and _is_produce_query(q)
    if fungi_mode:
        for extra in ("mushroom", "fungi", "fungus", "toadstool", "agaric", "mycological", "amanita"):
            if extra not in score_terms:
                score_terms.append(extra)
    if produce_mode:
        veg_asked = any(t in query_terms for t in _VEGETABLE_SCORE_TERMS)
        fruit_asked = _is_fruit_query(q)
        if veg_asked and fruit_asked:
            extras = list(_PRODUCE_SCORE_TERMS)
        elif fruit_asked:
            extras = list(_FRUIT_SCORE_TERMS)
        else:
            extras = list(_VEGETABLE_SCORE_TERMS)
        for extra in extras:
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
            "vegetable", "still life", "produce", "cabbage", "pumpkin", "fruit",
            "oil painting",
        ))
        take = min(len(ids), 100 if art_q else 70)
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

    # Fetch in batches until we have enough *relevant* hits (skip Met keyword noise)
    need = offset + limit
    target = min(need + 36, 120)
    out = []
    idx = 0
    batch_size = 40
    max_fetch = min(len(id_order), 200)

    def _fetch(oid):
        try:
            return oid, fetch_met_object(oid)
        except Exception:
            return oid, None

    while len(out) < target and idx < max_fetch:
        chunk = id_order[idx: idx + batch_size]
        if not chunk:
            break
        idx += len(chunk)
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_fetch, oid) for oid in chunk]
            for fut in as_completed(futures):
                oid, card = fut.result()
                if not card or not card.get("image"):
                    continue
                card["_score"] = _score_card(
                    card, score_terms, id_source.get(oid, ""),
                    fungi_mode=fungi_mode, produce_mode=produce_mode,
                )
                if _is_relevant_card(
                    card, query_terms, score_terms,
                    require_term=produce_mode, produce_mode=produce_mode,
                ):
                    out.append(card)
        if idx < max_fetch and len(out) < target:
            time.sleep(0.03)

    source_note = None
    want_commons = fungi_mode or produce_mode or len(out) < min(8, need)
    # Met Open Access barely indexes mushrooms — Commons has the mycological plates.
    # Produce / thin Met matches also get Commons still-life plates.
    if want_commons:
        try:
            commons = search_wikimedia_commons(q, limit=min(96, max(need + 24, 48)))
            queries_tried.insert(0, {"q": f"commons:{q}", "total": len(commons)})
            commons_kept = 0
            src_label = (
                "wikimedia fungi" if fungi_mode
                else "wikimedia produce" if produce_mode
                else "wikimedia"
            )
            boost = 25 if fungi_mode else 3 if produce_mode else 8
            for card in commons:
                card["_score"] = _score_card(
                    card, score_terms, src_label,
                    fungi_mode=fungi_mode, produce_mode=produce_mode,
                ) + boost
                if _is_relevant_card(
                    card, query_terms, score_terms,
                    require_term=produce_mode, produce_mode=produce_mode,
                ):
                    out.append(card)
                    commons_kept += 1
            if commons_kept and fungi_mode:
                source_note = (
                    "Met has almost no mushroom plates — results include Wikimedia Commons "
                    "(PD/CC0). Verify license before selling."
                )
            elif commons_kept and produce_mode:
                source_note = (
                    "Results include Wikimedia Commons still-life / botanical plates (PD/CC0). "
                    "Verify license before selling."
                )
            elif commons_kept:
                source_note = (
                    "Few close Met matches — added Wikimedia Commons (PD/CC0). "
                    "Verify license before selling."
                )
        except Exception:
            pass

    try:
        loc_cards = search_loc(q, limit=min(96, max(need + 24, 48)))
        queries_tried.append({"q": f"loc:{q}", "total": len(loc_cards)})
        loc_kept = 0
        for card in loc_cards:
            card["_score"] = _score_card(
                card, score_terms, "library of congress",
                fungi_mode=fungi_mode, produce_mode=produce_mode,
            ) + 12
            if _is_relevant_card(card, query_terms, score_terms):
                out.append(card)
                loc_kept += 1
        if loc_kept:
            loc_note = (
                "Results include Library of Congress (free-to-use / digital collections). "
                "Verify rights before selling."
            )
            source_note = (source_note + " " + loc_note) if source_note else loc_note
    except Exception:
        pass

    if not out:
        source_note = source_note or (
            "No Oil on canvas Open Access matches for this query. "
            "Try a different subject (still life, landscape, portrait)."
        )

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


def _object_tag_terms(o):
    out = []
    for t in (o.get("tags") or []):
        if isinstance(t, dict):
            term = str(t.get("term") or "").strip()
        else:
            term = str(t or "").strip()
        if term:
            out.append(term)
        if len(out) >= 24:
            break
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
        "classification": o.get("classification") or "",
        "object_name": o.get("objectName") or "",
        "tags": _object_tag_terms(o),
        "credit": o.get("creditLine") or "",
        "rights": "Public Domain (Met Open Access)",
        "object_url": o.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{oid}",
        "image": image,
        "image_small": o.get("primaryImageSmall") or image,
    }


def download_image(url, dest_path, alt_urls=None):
    tried = []
    for candidate in [url, *(alt_urls or [])]:
        candidate = (candidate or "").strip()
        if not candidate or candidate in tried:
            continue
        tried.append(candidate)
        try:
            data = b""
            if candidate.startswith("/api/public_domain/image"):
                parsed = urllib.parse.urlparse(candidate)
                qs = urllib.parse.parse_qs(parsed.query)
                data, _mime = resolve_pd_image_bytes(
                    (qs.get("set") or [""])[0],
                    (qs.get("file") or [""])[0],
                    (qs.get("u") or [""])[0],
                )
            else:
                headers = dict(UA)
                if "loc.gov" in candidate.lower():
                    headers = {
                        **LOC_HEADERS,
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": "https://www.loc.gov/",
                    }
                r = requests.get(candidate, headers=headers, timeout=120)
                ctype = (r.headers.get("Content-Type") or "").lower()
                data = r.content or b""
                if r.status_code != 200 or "html" in ctype or data.lstrip()[:15].lower().startswith(b"<!doctype"):
                    continue
            if not data or len(data) < 200:
                continue
            from PIL import Image
            im = Image.open(BytesIO(data)).convert("RGB")
            if im.size in {(640, 400), (480, 120)} and len(data) < 25000:
                continue
            im.save(dest_path, format="PNG", optimize=True)
            return dest_path
        except Exception:
            continue
    raise RuntimeError("Downloaded image is empty/tiny or blocked (loc.gov Cloudflare).")


def _safe_filename(text, fallback="art"):
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    slug = re.sub(r"[\s_-]+", "-", slug)[:48].strip("-")
    return slug or fallback


def import_objects_to_run(objects, runs_dir, concept="public domain vintage", trim_borders=True, max_objects=PD_IMPORT_MAX):
    """Download + prep selected PD objects as a pack into _candidates.

    Large packs are parallelized (a few at a time) so the HTTP request finishes
    before browsers / proxies give up. Soft-caps selection size.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    objects = list(objects or [])
    if len(objects) > max_objects:
        objects = objects[:max_objects]

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
            alt = [obj.get("image_fallback"), obj.get("loc_source_image"), obj.get("image_small")]
            download_image(img_url, raw_path, alt_urls=alt)
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

    workers = min(6, max(1, len(objects)))
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
