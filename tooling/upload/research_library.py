"""Curated research library — save listing/shop/keyword captures with categories."""
import json
import os
import re
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY_PATH = os.path.join(HERE, "research_library.json")

DEFAULT_CATEGORIES = [
    "Competitor watch",
    "Mega bundle",
    "Single print hero",
    "Niche idea",
    "Pricing ref",
    "Mockup / SEO ref",
    "Uncategorized",
]


def _empty():
    return {"version": 1, "categories": list(DEFAULT_CATEGORIES), "items": []}


def load_library():
    if not os.path.isfile(LIBRARY_PATH):
        return _empty()
    try:
        with open(LIBRARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("version", 1)
        data.setdefault("categories", list(DEFAULT_CATEGORIES))
        data.setdefault("items", [])
        return data
    except Exception:
        return _empty()


def save_library(data):
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _slug(text):
    s = re.sub(r"[^\w\s-]", "", (text or "").lower()).strip()
    return re.sub(r"[\s_-]+", "-", s)[:48] or "item"


def list_items(category=None, kind=None, q=None):
    lib = load_library()
    items = list(lib.get("items") or [])
    if category and category != "all":
        items = [i for i in items if (i.get("category") or "") == category]
    if kind and kind != "all":
        items = [i for i in items if (i.get("kind") or "") == kind]
    if q:
        needle = q.strip().lower()
        items = [
            i for i in items
            if needle in (i.get("title") or "").lower()
            or needle in (i.get("notes") or "").lower()
            or needle in (i.get("category") or "").lower()
            or needle in json.dumps(i.get("payload") or {}).lower()
        ]
    items.sort(key=lambda i: i.get("saved_at") or "", reverse=True)
    return {
        "categories": lib.get("categories") or list(DEFAULT_CATEGORIES),
        "items": items,
        "count": len(items),
    }


def add_item(kind, payload, category=None, notes="", title=None, tags=None):
    kind = (kind or "listing").strip().lower()
    if kind not in ("listing", "shop", "keyword"):
        kind = "listing"
    lib = load_library()
    cat = (category or "Uncategorized").strip() or "Uncategorized"
    if cat not in lib["categories"]:
        lib["categories"].append(cat)

    payload = payload if isinstance(payload, dict) else {}
    auto_title = title
    if not auto_title:
        if kind == "listing":
            auto_title = payload.get("title") or payload.get("listing_id") or "Listing"
        elif kind == "shop":
            auto_title = payload.get("shop_name") or "Shop"
        else:
            auto_title = payload.get("query") or payload.get("keyword") or "Keyword research"

    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "title": str(auto_title)[:200],
        "category": cat,
        "notes": (notes or "").strip()[:2000],
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()][:20],
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ref": {
            "listing_id": payload.get("listing_id") or "",
            "listing_url": payload.get("listing_url") or "",
            "shop_name": payload.get("shop_name") or "",
            "image": payload.get("image") or "",
            "price": payload.get("price") or "",
        },
        "payload": payload,
    }
    lib["items"].insert(0, item)
    # Cap library size
    lib["items"] = lib["items"][:500]
    save_library(lib)
    return item


def update_item(item_id, category=None, notes=None, title=None, tags=None):
    lib = load_library()
    for item in lib["items"]:
        if item.get("id") != item_id:
            continue
        if category is not None:
            cat = category.strip() or "Uncategorized"
            item["category"] = cat
            if cat not in lib["categories"]:
                lib["categories"].append(cat)
        if notes is not None:
            item["notes"] = str(notes).strip()[:2000]
        if title is not None:
            item["title"] = str(title).strip()[:200]
        if tags is not None:
            item["tags"] = [str(t).strip() for t in tags if str(t).strip()][:20]
        item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_library(lib)
        return item
    return None


def delete_item(item_id):
    lib = load_library()
    before = len(lib["items"])
    lib["items"] = [i for i in lib["items"] if i.get("id") != item_id]
    if len(lib["items"]) == before:
        return False
    save_library(lib)
    return True


def add_category(name):
    name = (name or "").strip()
    if not name:
        return None
    lib = load_library()
    if name not in lib["categories"]:
        lib["categories"].append(name)
        save_library(lib)
    return name
