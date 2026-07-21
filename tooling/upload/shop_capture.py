"""Parse shop stats from a browser-side capture (EverBee-style workaround).

Public Etsy shop pages expose: sales count, reviews, rating, listing count,
featured listing titles/prices/urls. Monthly / listing sales are estimated —
same class of estimate as research plugins, not private Etsy backend data.
"""
import re
from etsy_scrape_utils import parse_etsy_number, normalize_listing_url

AVG_DIGITAL_PRICE = 4.99


def empty_result(shop_name, message, shop_url=None):
    return {
        "shop_name": shop_name,
        "shop_url": shop_url or f"https://www.etsy.com/shop/{shop_name}",
        "data_source": "unavailable",
        "message": message,
        "niche": "",
        "opened_on": "",
        "location": "",
        "sales": None,
        "revenue": "—",
        "active_listings": None,
        "reviews": None,
        "rating": None,
        "conversion_rate": "—",
        "monthly_sales": None,
        "monthly_revenue": "—",
        "listings": [],
        "reviews_list": [],
        "similar_shops": [],
        "show_history_chart": False,
    }


def parse_price_value(price_txt):
    """Parse sale price from strings like '€10.08€20.18', '$3.99', '10,08 €'."""
    if not price_txt:
        return 0.0, ""
    raw = str(price_txt).strip().replace("\u00a0", " ")
    amounts = re.findall(r"[\d]+[.,]\d{2}|\d+", raw)
    if not amounts:
        return 0.0, raw
    first = amounts[0].replace(",", ".")
    try:
        val = float(first)
    except ValueError:
        return 0.0, raw
    currency = "€" if "€" in raw else ("£" if "£" in raw else "$")
    return val, f"{currency}{val:.2f}"


def dedupe_listings(listings):
    """Keep unique listings by Etsy listing id (or title fallback)."""
    seen = set()
    out = []
    for item in listings or []:
        url = item.get("url") or ""
        m = re.search(r"/listing/(\d+)", url)
        key = m.group(1) if m else (item.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def allocate_listing_sales(listings, monthly_shop_sales):
    """Spread shop monthly sales across visible listings (largest-remainder)."""
    if not listings:
        return listings
    monthly = int(monthly_shop_sales or 0)
    if monthly <= 0:
        for item in listings:
            price_val = item.pop("_price_val", None) or 0.0
            item["est_monthly_sales"] = 0
            item["est_monthly_revenue"] = f"{_currency_sym(item.get('price'))}0.00"
            if price_val and monthly == 0:
                item["est_monthly_revenue"] = f"{_currency_sym(item.get('price'))}0.00"
        return listings

    n = len(listings)
    weights = [1.0 / ((i + 1) ** 0.85) for i in range(n)]
    total_w = sum(weights) or 1.0
    raw_shares = [monthly * (w / total_w) for w in weights]
    shares = [int(x) for x in raw_shares]
    remainders = sorted(
        ((raw_shares[i] - shares[i], i) for i in range(n)),
        reverse=True,
    )
    leftover = monthly - sum(shares)
    for _, i in remainders:
        if leftover <= 0:
            break
        shares[i] += 1
        leftover -= 1

    for i, item in enumerate(listings):
        share = shares[i]
        price_val = item.pop("_price_val", None) or 0.0
        sym = _currency_sym(item.get("price"))
        item["est_monthly_sales"] = share
        item["est_monthly_revenue"] = f"{sym}{share * price_val:,.2f}" if price_val else "—"
    return listings


def _currency_sym(price_disp):
    if not price_disp:
        return "$"
    if "€" in str(price_disp):
        return "€"
    if "£" in str(price_disp):
        return "£"
    return "$"


def finalize_metrics(result):
    sales = result.get("sales")
    reviews = result.get("reviews")
    months = max(1, result.get("_shop_age_months") or 12)
    avg_price = result.pop("_avg_price", None) or AVG_DIGITAL_PRICE

    result["conversion_rate"] = "—"
    result["show_history_chart"] = False

    if sales is None:
        result.pop("_avg_price", None)
        result.pop("_shop_age_months", None)
        return result

    # Never invent sales: 0 sales => 0 monthly
    monthly = int(round(sales / months)) if sales > 0 else 0
    result["monthly_sales"] = monthly
    result["revenue"] = f"${round(sales * avg_price, 2):,.2f}"
    result["monthly_revenue"] = f"${round(monthly * avg_price, 2):,.2f}"

    # Conversion is not public. Only estimate when we have both sales and reviews.
    if sales > 0 and reviews is not None and reviews >= 0:
        review_rate = reviews / sales
        est_cvr = min(6.0, max(0.5, review_rate * 70))
        result["conversion_rate"] = f"~{est_cvr:.1f}%"
    elif sales == 0:
        result["conversion_rate"] = "—"

    result["listings"] = allocate_listing_sales(result.get("listings") or [], monthly)
    result.pop("_shop_age_months", None)
    return result


def shop_name_from_url(url):
    if not url:
        return ""
    m = re.search(r"etsy\.com/(?:[a-z]{2}/)?shop/([^/?#]+)", url, re.I)
    return m.group(1) if m else ""


def normalize_shop_url(shop_name, shop_url=""):
    name = shop_name or shop_name_from_url(shop_url)
    if shop_url and "/shop/" in shop_url.lower():
        return shop_url.split("?")[0]
    return f"https://www.etsy.com/shop/{name}" if name else shop_url or ""


def extract_shop_header_stats(text):
    """Pull sales / reviews / rating / items / age from noisy full-page text."""
    sales_m = re.search(r"([\d,.]+[kK]?)\s+sales\b", text, re.I)
    sales = parse_etsy_number(sales_m.group(1)) if sales_m else None

    # Search full page for reviews — not only near sales (layout varies by region)
    reviews = None
    rating = None
    combo = re.search(
        r"([1-5](?:[.,]\d)?)\s*[\(\[]?\s*([\d,.]+[kK]?)\s+reviews?[\)\]]?",
        text,
        re.I,
    )
    if combo:
        try:
            rating = float(combo.group(1).replace(",", "."))
        except ValueError:
            rating = None
        reviews = parse_etsy_number(combo.group(2))
    if reviews is None:
        for pat in (
            r"\(([\d,.]+[kK]?)\s+reviews?\)",
            r"([\d,.]+[kK]?)\s+shop reviews?\b",
            r"from\s+([\d,.]+[kK]?)\s+reviews?\b",
            r"([\d,.]+[kK]?)\s+reviews?\b",
        ):
            m = re.search(pat, text, re.I)
            if m:
                reviews = parse_etsy_number(m.group(1))
                break
    if rating is None:
        m = re.search(r"\b([1-5][.,]\d)\b(?:\s*out of 5)?", text)
        if m:
            rating = float(m.group(1).replace(",", "."))

    items = None
    for pat in (
        r"Search all\s+([\d,]+)\s+items",
        r"All\s*\(([\d,]+)\)",
        r"On sale\s*\(([\d,]+)\)",
        r"\b([\d,]+)\s+items\b",
    ):
        m = re.search(pat, text, re.I)
        if m:
            items = parse_etsy_number(m.group(1).replace(",", ""))
            if items is not None and items >= 0:
                break

    months = None
    opened_on = ""
    m = re.search(r"(\d+)\s+months?\s+on\s+Etsy", text, re.I)
    if m:
        months = max(1, int(m.group(1)))
        opened_on = f"{months} months on Etsy"
    else:
        m = re.search(r"On Etsy since\s+(\d{4})", text, re.I)
        if m:
            year = int(m.group(1))
            opened_on = f"On Etsy since {year}"
            months = max(1, (2026 - year) * 12)

    location = ""
    loc = re.search(
        r"\b(United States|United Kingdom|Ireland|Canada|Australia|Germany|France|Spain|Italy|Netherlands|India)\b",
        text[:3000],
        re.I,
    )
    if loc:
        location = loc.group(1).strip()

    return {
        "sales": sales,
        "reviews": reviews,
        "rating": rating,
        "active_listings": items,
        "months": months,
        "opened_on": opened_on,
        "location": location,
    }


def pick_niche(text, shop_name):
    for line in text.splitlines():
        line = line.strip()
        if not (8 < len(line) < 80):
            continue
        if shop_name and shop_name.lower() in line.lower():
            continue
        if re.match(r"^(All|On sale|Items|Reviews|About|Shop Policies)\b", line, re.I):
            continue
        if any(k in line.lower() for k in ("print", "art", "digital", "wall", "vintage", "modern", "gallery", "minimal")):
            return line
    return "Captured from Etsy shop page"


def parse_page_text(body_text, shop_url="", shop_name="", listings=None, stats=None):
    """Build analyzer payload from visible page text + optional listing cards."""
    shop_name = (shop_name or shop_name_from_url(shop_url) or "unknown").strip()
    shop_url = normalize_shop_url(shop_name, shop_url)
    text = body_text or ""
    stats = stats or {}

    if not text.strip() and not listings and not stats:
        return empty_result(
            shop_name,
            "Capture was empty. Open the shop page, wait for it to load, then run Capture again.",
            shop_url,
        )

    result = empty_result(shop_name, "", shop_url)
    result["data_source"] = "browser_capture"

    header = extract_shop_header_stats(text)

    result["sales"] = _num(stats.get("sales"), header["sales"])
    result["reviews"] = _num(stats.get("reviews"), header["reviews"])
    result["active_listings"] = _num(stats.get("active_listings"), header["active_listings"])
    result["rating"] = _float(stats.get("rating"), header["rating"])
    result["opened_on"] = stats.get("opened_on") or header["opened_on"]
    result["location"] = stats.get("location") or header["location"]
    if stats.get("shop_age_months"):
        result["_shop_age_months"] = max(1, int(stats["shop_age_months"]))
    elif header["months"]:
        result["_shop_age_months"] = header["months"]

    # If we captured unique listing cards but no All(N), use that count
    cleaned = []
    prices = []
    for item in listings or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        price_val, price_disp = parse_price_value(item.get("price"))
        if price_val > 0:
            prices.append(price_val)
        url = normalize_listing_url(item.get("url") or "")
        cleaned.append({
            "title": title,
            "price": price_disp if price_val else (item.get("price") or "—"),
            "_price_val": price_val,
            "est_monthly_sales": None,
            "est_monthly_revenue": "—",
            "image": item.get("image") or "",
            "url": url,
            "data_source": "browser_capture",
        })
    cleaned = dedupe_listings(cleaned)
    result["listings"] = cleaned[:24]
    if result["active_listings"] is None and cleaned:
        result["active_listings"] = len(cleaned)
    if prices:
        result["_avg_price"] = round(sum(prices) / len(prices), 2)

    result["niche"] = (stats.get("niche") or "").strip() or pick_niche(text, shop_name)

    if result["sales"] is None and result["reviews"] is None and not cleaned:
        return empty_result(
            shop_name,
            "Could not read sales/reviews from the captured page text. Make sure you are on the shop Items tab.",
            shop_url,
        )

    result = finalize_metrics(result)
    bits = [
        "Captured from your browser.",
        "Sales / reviews / rating / listing counts are public page values when found.",
    ]
    if result.get("conversion_rate") not in (None, "—"):
        bits.append("Conversion is estimated from reviews÷sales (not published by Etsy).")
    else:
        bits.append("Conversion left blank when sales are 0 or reviews are missing.")
    bits.append(
        "Per-listing monthly figures split shop monthly sales across unique listings — estimates only."
    )
    result["message"] = " ".join(bits)
    return result


def _num(preferred, fallback):
    if preferred is None or preferred == "":
        return fallback
    if isinstance(preferred, (int, float)):
        return int(preferred)
    parsed = parse_etsy_number(str(preferred))
    return parsed if parsed is not None else fallback


def _float(preferred, fallback):
    if preferred is None or preferred == "":
        return fallback
    try:
        val = float(str(preferred).replace(",", "."))
        return val if 1.0 <= val <= 5.0 else fallback
    except (TypeError, ValueError):
        return fallback


def parse_paste_text(raw_text, shop_name=""):
    """Fallback: user pastes visible shop-header text from Etsy."""
    name = shop_name.strip() or "pasted_shop"
    m = re.search(r"etsy\.com/(?:[a-z]{2}/)?shop/([A-Za-z0-9_-]+)", raw_text or "", re.I)
    if m:
        name = m.group(1)
    return parse_page_text(raw_text or "", shop_url=f"https://www.etsy.com/shop/{name}", shop_name=name)
