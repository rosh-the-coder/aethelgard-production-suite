"""Listing-page capture + EverBee-style estimates (Phase 1).

Public Etsy listing fields (views, favorites, age, tags, etc.) come from the
browser page. Monthly/total sales, revenue, conversion, and visibility are
ESTIMATES — Etsy does not publish listing sales. EverBee's paid numbers are
also estimates from their private history DB; ours start from page signals.
"""
import json
import os
import re
import time
from etsy_scrape_utils import parse_etsy_number, normalize_listing_url

HERE = os.path.dirname(os.path.abspath(__file__))
LISTING_SNAPSHOTS_PATH = os.path.join(HERE, "listing_snapshots.json")


def empty_listing(message="", listing_url=""):
    return {
        "data_source": "unavailable",
        "message": message,
        "listing_url": listing_url,
        "listing_id": "",
        "title": "",
        "price": "—",
        "price_val": None,
        "currency": "$",
        "shop_name": "",
        "shop_url": "",
        "image": "",
        "views": None,
        "favorites": None,
        "listing_reviews": None,
        "listing_age_months": None,
        "listing_age_label": "—",
        "category": "",
        "tags": [],
        "details": {},
        # Estimates (EverBee paid equivalents)
        "est_total_sales": None,
        "est_monthly_sales": None,
        "est_monthly_revenue": "—",
        "est_conversion_rate": "—",
        "est_visibility_score": None,
        "estimate_notes": [],
        "captured_at": None,
    }


def listing_id_from_url(url):
    m = re.search(r"/listing/(\d+)", url or "")
    return m.group(1) if m else ""


def parse_price(raw):
    if not raw:
        return None, "—", "$"
    text = str(raw).replace("\u00a0", " ")
    # Prefer full money amounts; skip bare "." crumbs from broken scrapes
    amounts = re.findall(r"\d+[.,]\d{2}|\d+", text)
    currency = "€" if "€" in text else ("£" if "£" in text else "$")
    for amount in amounts:
        cleaned = amount.replace(",", ".")
        if cleaned in (".", "") or not any(ch.isdigit() for ch in cleaned):
            continue
        try:
            val = float(cleaned)
        except ValueError:
            continue
        if val <= 0:
            continue
        return val, f"{currency}{val:.2f}", currency
    return None, text.strip() or "—", currency


def extract_tags_from_text(text):
    tags = []
    # Common patterns near "Tags" section on listing
    block = re.search(r"Tags?\s*\n((?:.+\n){1,20})", text, re.I)
    if block:
        for line in block.group(1).splitlines():
            line = line.strip().strip(",").strip()
            if not line or len(line) > 60:
                continue
            if re.match(r"^(Highlights|Description|Shipping|Meet|About|Reviews)\b", line, re.I):
                break
            if line.lower() in ("tags", "tag"):
                continue
            tags.append(line)
    return tags[:20]


def estimate_listing_metrics(result):
    """Heuristic stand-ins for EverBee paid fields — clearly labeled as estimates."""
    notes = []
    views = result.get("views")
    favs = result.get("favorites") or 0
    age = max(1, result.get("listing_age_months") or 1)
    reviews = result.get("listing_reviews") or 0
    price = result.get("price_val") or 0.0
    currency = result.get("currency") or "$"

    # Total sales estimate: favorites + reviews are weak public demand signals.
    # Calibrated as a transparent heuristic, not EverBee-equivalent accuracy.
    base = (favs * 0.55) + (reviews * 8.0)
    if views and views > 0:
        # Slight bump when engagement rate is high
        eng = favs / max(views, 1)
        base *= 1.0 + min(1.5, eng * 20)
        notes.append("Total sales estimated from favorites, listing reviews, and views engagement.")
    else:
        notes.append("Total sales estimated from favorites and listing reviews (views missing).")

    est_total = int(round(base))
    if favs == 0 and reviews == 0 and (not views or views < 20):
        est_total = 0
        notes.append("Low public signals — sales estimate set to 0.")

    est_monthly = int(round(est_total / age)) if est_total > 0 else 0
    est_rev = round(est_monthly * price, 2) if price else 0.0

    if views and views > 0 and est_total > 0:
        cvr = min(25.0, max(0.1, (est_total / views) * 100))
        cvr_label = f"~{cvr:.1f}%"
        notes.append("Conversion ≈ estimated total sales ÷ views.")
    else:
        cvr_label = "—"

    # Visibility 0–100 from public signals
    vis = 20
    if views:
        vis += min(40, views / 25)
    if favs:
        vis += min(25, favs * 1.2)
    if reviews:
        vis += min(15, reviews * 5)
    vis = int(min(99, max(1, round(vis))))

    result["est_total_sales"] = est_total
    result["est_monthly_sales"] = est_monthly
    result["est_monthly_revenue"] = f"{currency}{est_rev:,.2f}"
    result["est_conversion_rate"] = cvr_label
    result["est_visibility_score"] = vis
    result["estimate_notes"] = notes
    return result


def parse_listing_capture(page_text="", listing_url="", stats=None, tags=None, details=None):
    stats = stats or {}
    details = details or {}
    listing_url = (listing_url or "").split("?")[0]
    lid = stats.get("listing_id") or listing_id_from_url(listing_url)
    text = page_text or ""

    if not text.strip() and not stats:
        return empty_listing("Empty capture. Open an Etsy listing and run the bookmarklet.", listing_url)

    result = empty_listing("", listing_url)
    result["data_source"] = "browser_capture"
    result["listing_id"] = str(lid or "")
    result["listing_url"] = listing_url or f"https://www.etsy.com/listing/{lid}"
    result["title"] = (stats.get("title") or "").strip()
    if not result["title"]:
        m = re.search(r"^(.+?)\s+-\s+Etsy", text[:300], re.M)
        if m:
            result["title"] = m.group(1).strip()

    price_val, price_disp, currency = parse_price(stats.get("price") or "")
    if price_val is None:
        # Fallback from page text
        m = re.search(r"(?:Price:|€|\$|£)\s*([\d,.]+)", text)
        if m:
            price_val, price_disp, currency = parse_price(m.group(0))
    if price_val is None and (not price_disp or price_disp.strip() in (".", "-", "—")):
        price_disp = "—"
    result["price_val"] = price_val
    result["price"] = price_disp
    result["currency"] = currency
    result["shop_name"] = (stats.get("shop_name") or "").strip()
    result["shop_url"] = stats.get("shop_url") or (
        f"https://www.etsy.com/shop/{result['shop_name']}" if result["shop_name"] else ""
    )
    result["image"] = stats.get("image") or ""

    result["views"] = _num(stats.get("views"), _find_num(text, [
        r"([\d,.]+[kK]?)\s+views?\b",
        r"Views?\s*[:\-]?\s*([\d,.]+[kK]?)",
    ]))
    result["favorites"] = _num(stats.get("favorites"), _find_num(text, [
        r"([\d,.]+[kK]?)\s+favorites?\b",
        r"Favorites?\s*[:\-]?\s*([\d,.]+[kK]?)",
    ]))
    result["listing_reviews"] = _num(stats.get("listing_reviews"), _find_num(text, [
        r"\(([\d,.]+[kK]?)\s+reviews?\)",
        r"([\d,.]+[kK]?)\s+reviews?\b",
    ]))

    age_months = stats.get("listing_age_months")
    if age_months is None:
        m = re.search(r"Listed on\s+(\w+\s+\d{1,2},\s+\d{4})", text, re.I)
        if m:
            age_months = _months_since_date_label(m.group(1))
        else:
            m = re.search(r"(\d+)\s+months?\s+(?:ago|old|on Etsy)", text, re.I)
            if m:
                age_months = int(m.group(1))
    result["listing_age_months"] = int(age_months) if age_months is not None else None
    if result["listing_age_months"] is not None:
        result["listing_age_label"] = f"{result['listing_age_months']} mo."
    elif stats.get("listing_age_label"):
        result["listing_age_label"] = stats["listing_age_label"]

    result["category"] = (stats.get("category") or "").strip()
    tag_list = tags if tags is not None else stats.get("tags")
    if not tag_list:
        tag_list = extract_tags_from_text(text)
    # Normalize tags
    cleaned_tags = []
    seen = set()
    for t in tag_list or []:
        t = str(t).strip()
        key = t.lower()
        if not t or key in seen or len(t) > 70:
            continue
        seen.add(key)
        cleaned_tags.append(t)
    result["tags"] = cleaned_tags[:20]

    # Listing attribute details (More Details)
    merged_details = {}
    defaults = {
        "when_made": stats.get("when_made"),
        "listing_type": stats.get("listing_type"),
        "customizable": stats.get("customizable"),
        "craft_supply": stats.get("craft_supply"),
        "personalized": stats.get("personalized"),
        "auto_renew": stats.get("auto_renew"),
        "has_variations": stats.get("has_variations"),
        "who_made": stats.get("who_made"),
        "title_char_count": len(result["title"]) if result["title"] else None,
        "tag_count": len(result["tags"]),
    }
    for k, v in defaults.items():
        if v is not None and v != "":
            merged_details[k] = v
    merged_details.update({k: v for k, v in details.items() if v is not None and v != ""})
    # Text fallbacks for attributes
    for key, patterns in (
        ("when_made", [r"When made\s*[:\-]?\s*([^\n]+)"]),
        ("who_made", [r"Who made(?: this)?\s*[:\-]?\s*([^\n]+)", r"Made by\s*[:\-]?\s*([^\n]+)"]),
        ("listing_type", [r"(Digital download|Physical item|download)"]),
    ):
        if key not in merged_details:
            for pat in patterns:
                m = re.search(pat, text, re.I)
                if m:
                    merged_details[key] = m.group(1).strip()
                    break
    result["details"] = merged_details

    result = estimate_listing_metrics(result)
    result["message"] = (
        "Listing capture from your browser. Views, favorites, age, tags, and details are public "
        "page values when found. Monthly/total sales, revenue, conversion, and visibility are "
        "heuristic estimates (not EverBee’s paid DB, and not private Etsy sales)."
    )
    result["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return result


def _months_since_date_label(label):
    """Best-effort months since 'Mar 12, 2026' style dates."""
    try:
        from datetime import datetime
        dt = datetime.strptime(label.strip(), "%b %d, %Y")
        now = datetime(2026, 7, 16)
        months = (now.year - dt.year) * 12 + (now.month - dt.month)
        return max(1, months) if months >= 0 else 1
    except Exception:
        return None


def _find_num(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return parse_etsy_number(m.group(1))
    return None


def _num(preferred, fallback):
    if preferred is None or preferred == "":
        return fallback
    if isinstance(preferred, (int, float)):
        return int(preferred)
    parsed = parse_etsy_number(str(preferred))
    return parsed if parsed is not None else fallback


def append_listing_snapshot(listing):
    """Store capture for future trends (Phase: historical graphs)."""
    lid = listing.get("listing_id")
    if not lid:
        return
    data = {}
    if os.path.isfile(LISTING_SNAPSHOTS_PATH):
        try:
            with open(LISTING_SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    bucket = data.setdefault(str(lid), [])
    bucket.append({
        "captured_at": listing.get("captured_at"),
        "views": listing.get("views"),
        "favorites": listing.get("favorites"),
        "est_total_sales": listing.get("est_total_sales"),
        "est_monthly_sales": listing.get("est_monthly_sales"),
        "price_val": listing.get("price_val"),
    })
    # Keep last 90 snapshots per listing
    data[str(lid)] = bucket[-90:]
    try:
        with open(LISTING_SNAPSHOTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_listing_snapshots(listing_id):
    if not listing_id or not os.path.isfile(LISTING_SNAPSHOTS_PATH):
        return []
    try:
        with open(LISTING_SNAPSHOTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(listing_id), [])
    except Exception:
        return []
