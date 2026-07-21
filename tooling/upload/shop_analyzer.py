import os
import sys
import json
import re
import asyncio
import etsy_scrape_utils  # noqa: F401 — sets PLAYWRIGHT_BROWSERS_PATH
from playwright.async_api import async_playwright

from etsy_scrape_utils import (
    parse_etsy_number,
    find_first,
    normalize_listing_url,
    is_blocked_page,
    blocked_message,
    launch_browser,
    new_etsy_context,
)

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
    }


def finalize_metrics(result):
    sales = result.get("sales")
    if sales is not None:
        total_rev = round(sales * AVG_DIGITAL_PRICE, 2)
        result["revenue"] = f"${total_rev:,.2f}"
        months = max(1, result.get("_shop_age_months") or 12)
        monthly = max(1, int(sales / months))
        result["monthly_sales"] = monthly
        result["monthly_revenue"] = f"${round(monthly * AVG_DIGITAL_PRICE, 2):,.2f}"
    result.pop("_shop_age_months", None)
    return result


async def scrape_shop_listings(page, limit=12):
    listings = []
    cards = await page.query_selector_all("[data-listing-card-v2], .v2-listing-card")
    for card in cards[:limit]:
        try:
            title_el = await card.query_selector("h3, h2")
            price_el = await card.query_selector(".currency-value, .n-listing-card__price")
            img_el = await card.query_selector("img")
            link_el = await card.query_selector("a[href*='/listing/']")
            if not title_el:
                continue
            title = (await title_el.inner_text()).strip()
            if not title:
                continue
            price_txt = (await price_el.inner_text()).strip() if price_el else "0"
            price_val = float(re.sub(r"[^\d.]", "", price_txt) or "0")
            img = ""
            if img_el:
                img = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""
            href = await link_el.get_attribute("href") if link_el else ""
            url = normalize_listing_url(href)
            listings.append({
                "title": title,
                "price": f"${price_val:.2f}",
                "est_monthly_sales": None,
                "est_monthly_revenue": "—",
                "image": img,
                "url": url,
                "data_source": "live",
            })
        except Exception:
            continue
    return listings


async def scrape_shop_data(shop_name):
    shop_name = shop_name.strip().strip("/")
    url = f"https://www.etsy.com/shop/{shop_name}"
    result = empty_result(shop_name, "", url)
    result["data_source"] = "live"

    try:
        async with async_playwright() as p:
            browser = await launch_browser(p)
            context = await new_etsy_context(browser)
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            await page.goto(url, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)

            title = await page.title()
            body_text = await page.evaluate("document.body.innerText") or ""
            html = await page.content()

            if is_blocked_page(title, body_text, page.url, f"/shop/{shop_name.lower()}", html):
                await browser.close()
                return empty_result(shop_name, blocked_message(), url)

            # Shop tagline / niche
            for sel in (".shop-name-and-title-container p", ".shop-home-wider-sections p", "p.wt-text-caption"):
                el = await page.query_selector(sel)
                if el:
                    txt = (await el.inner_text()).strip()
                    if txt and len(txt) < 120:
                        result["niche"] = txt
                        break
            if not result["niche"]:
                result["niche"] = "Etsy shop"

            sales_raw = find_first([
                r"([\d,.]+[kK]?)\s+sales",
                r"([\d,]+)\s+Sales",
            ], body_text)
            reviews_raw = find_first([
                r"\(([ \d,.]+[kK]?)\s+reviews\)",
                r"([\d,.]+[kK]?)\s+reviews",
            ], body_text)
            rating_raw = find_first([r"([\d.]+)\s+out of 5", r"([\d.]+)\s+★"], body_text)
            since_raw = find_first([r"On Etsy since\s+(\d{4})", r"(\d+)\s+months on Etsy"], body_text)
            items_raw = find_first([r"All\s*\(([\d,]+)\)", r"Search all\s+([\d,]+)\s+items"], body_text)

            result["sales"] = parse_etsy_number(sales_raw) if sales_raw else None
            result["reviews"] = parse_etsy_number(reviews_raw) if reviews_raw else None
            result["rating"] = float(rating_raw) if rating_raw else None
            result["active_listings"] = parse_etsy_number(items_raw.replace(",", "")) if items_raw else None

            if since_raw:
                if since_raw.isdigit() and len(since_raw) == 4:
                    result["opened_on"] = f"On Etsy since {since_raw}"
                    result["_shop_age_months"] = max(1, (2026 - int(since_raw)) * 12)
                else:
                    result["opened_on"] = f"{since_raw} months on Etsy"
                    result["_shop_age_months"] = max(1, int(since_raw))

            loc_match = re.search(r"([A-Za-z .]+)\s*\|\s*On Etsy since", body_text)
            if loc_match:
                result["location"] = loc_match.group(1).strip()

            result["listings"] = await scrape_shop_listings(page)
            await browser.close()

    except Exception as e:
        print(f"Shop scrape error: {type(e).__name__}: {e}", file=sys.stderr)
        return empty_result(
            shop_name,
            "Could not scrape Etsy (Playwright browser missing or shop unreachable). "
            "Run: python -m playwright install chromium",
            url,
        )

    if result["sales"] is None and result["reviews"] is None and not result["listings"]:
        return empty_result(
            shop_name,
            "Could not read shop stats from Etsy page layout. Use the shop link for accurate numbers.",
            url,
        )

    result = finalize_metrics(result)
    if result["listings"]:
        result["message"] = (
            "Live shop stats from Etsy. Monthly sales/revenue are rough averages (total ÷ shop age). "
            "Per-listing monthly figures are not public on Etsy."
        )
    else:
        result["message"] = (
            "Live shop stats from Etsy. Monthly figures are estimates. "
            "Listing rows could not be scraped from this page."
        )
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shop_analyzer.py <shop_name>")
        sys.exit(1)

    shop = sys.argv[1]
    res = asyncio.run(scrape_shop_data(shop))
    print("\nSHOP_ANALYSIS_JSON:")
    print(json.dumps(res, indent=2))
