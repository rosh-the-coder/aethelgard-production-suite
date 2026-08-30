import os
import sys
import json
import re
import asyncio
import datetime
import etsy_scrape_utils  # noqa: F401 — sets PLAYWRIGHT_BROWSERS_PATH
from playwright.async_api import async_playwright
from etsy_scrape_utils import (
    AUTH_STATE_PATH,
    CDP_PORT,
    launch_chrome_for_login,
    wait_for_cdp,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def print_alert(msg):
    print("\n" + "=" * 60)
    print(f"[!] [MANUAL ACTION REQUIRED]: {msg}")
    print("=" * 60 + "\n")
    if os.name == "nt":
        import winsound
        winsound.MessageBeep()


def write_status(piece_dir, status, message="", draft_url=None, extra=None):
    payload = {
        "status": status,
        "message": message,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "piece_dir": piece_dir.replace("\\", "/"),
    }
    if draft_url:
        payload["draft_url"] = draft_url
    if extra:
        payload.update(extra)
    path = os.path.join(piece_dir, "upload_status.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write upload_status.json: {e}")
    return payload


async def wait_for_user(page, msg):
    print_alert(msg)
    input("--> Press [ENTER] in this terminal when you have completed this step in the browser to resume...")


async def fill_field_with_fallback(page, selectors, value, label, timeout=5000):
    """Try multiple selectors; fall back to manual entry."""
    if isinstance(selectors, str):
        selectors = [selectors]
    last_err = None
    for selector in selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=timeout)
            await element.focus()
            await element.fill("")
            await element.type(str(value))
            print(f"[ok] Filled {label}: {value}")
            return True
        except Exception as e:
            last_err = e
            continue
    await wait_for_user(page, f"Could not automatically fill the {label} field.\nPlease enter: '{value}'\n({last_err})")
    return False


async def click_element_with_fallback(page, selectors, label, timeout=5000):
    if isinstance(selectors, str):
        selectors = [selectors]
    last_err = None
    for selector in selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=timeout)
            await element.click()
            print(f"[ok] Clicked {label}")
            return True
        except Exception as e:
            last_err = e
            continue
    await wait_for_user(page, f"Could not click the {label}.\nPlease click it manually.\n({last_err})")
    return False


async def confirm_draft_saved(page, piece_dir):
    """Prefer automated signals; otherwise ask the operator explicitly."""
    # URL / text hints that a draft listing exists
    for _ in range(8):
        url = page.url or ""
        if "/listings/" in url and ("edit" in url or "draft" in url.lower()):
            write_status(piece_dir, "succeeded", "Draft listing URL detected.", draft_url=url)
            return True, url
        try:
            body = await page.inner_text("body")
            lowered = (body or "").lower()
            if "saved as draft" in lowered or "listing saved" in lowered or "draft saved" in lowered:
                write_status(piece_dir, "succeeded", "Draft save confirmation text detected.", draft_url=url or None)
                return True, url or None
        except Exception:
            pass
        await page.wait_for_timeout(500)

    write_status(
        piece_dir,
        "waiting_manual",
        "Could not auto-confirm draft save. Confirm in the console.",
    )
    print_alert(
        "Did the listing save as a DRAFT on Etsy?\n"
        "Type y and press ENTER if yes, or n if no / cancelled."
    )
    answer = input("--> Draft saved? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        url = page.url or ""
        write_status(piece_dir, "succeeded", "Operator confirmed draft saved.", draft_url=url or None)
        return True, url or None
    write_status(piece_dir, "failed", "Operator reported draft was not saved.")
    return False, None


async def run_login():
    """
    Open real Google Chrome (no automation flags), let user sign in, export cookies via CDP.
    """
    print("Starting real Google Chrome for Etsy login...")
    print("(This is NOT Playwright's automated browser — Etsy should not show bot warnings.)\n")

    proc, err = launch_chrome_for_login()
    if err:
        print(f"[ERROR] {err}")
        return

    if not wait_for_cdp():
        print("[ERROR] Chrome did not start remote debugging. Close other Chrome windows and retry.")
        if proc:
            proc.terminate()
        return

    print("\n" + "=" * 60)
    print("Chrome should be open on https://www.etsy.com")
    print("  1. Sign in with 'Sign in' (top-right) if needed")
    print("  2. If you see 'Access temporarily restricted':")
    print("       - Wait 30–60 minutes, OR try phone hotspot / different Wi‑Fi")
    print("       - Do NOT keep retrying — that extends the block")
    print("  3. When your account shows as signed in, return HERE and press ENTER")
    print("=" * 60 + "\n")

    input("--> Press [ENTER] when you are logged in on Etsy...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            if not browser.contexts:
                print("[ERROR] No Chrome session found. Sign in in the Chrome window and retry.")
                return
            context = browser.contexts[0]
            await context.storage_state(path=AUTH_STATE_PATH)
    except Exception as e:
        print(f"[ERROR] Could not save session: {type(e).__name__}: {e}")
        print("Make sure you are signed in and Chrome is still open, then run --login again.")
        return

    print(f"\n[OK] Session saved to:\n  {AUTH_STATE_PATH}")
    print("You can close the Chrome window, click Reload in the dashboard, then retry Market Research.")
    if proc and proc.poll() is None:
        print("(Chrome left running — close it manually when done.)")


async def upload_listing(piece_dir):
    """
    Upload a piece folder to Etsy as a draft. Status is written to upload_status.json.
    meta.uploaded_at is set only after a confirmed draft save.
    """
    meta_path = os.path.join(piece_dir, "meta.json")
    listing_path = os.path.join(piece_dir, "listing.json")

    if not os.path.exists(meta_path) or not os.path.exists(listing_path):
        write_status(piece_dir, "failed", "Missing meta.json or listing.json")
        print(f"Error: Missing meta.json or listing.json in {piece_dir}")
        return False

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(listing_path, "r", encoding="utf-8") as f:
        listing = json.load(f)

    title = listing.get("title", meta.get("title"))
    description = listing.get("description", meta.get("seo", {}).get("description", ""))
    tags = listing.get("tags", meta.get("seo", {}).get("tags", []))
    price = meta.get("price", "4.99")
    quantity = meta.get("quantity", "999")

    prefs = meta.get("mockup_prefs", {})
    disabled = set(prefs.get("disabled_mockups", []))
    photo_order = [str(x) for x in (prefs.get("photo_order") or []) if x]
    mockup_names = [
        f
        for f in os.listdir(piece_dir)
        if f.lower().startswith("mockup_") and f.lower().endswith(".jpg") and f not in disabled
    ]
    # Watermarked flat art — keep on listing but never as cover when other photos exist
    wm = os.path.join(piece_dir, "master_wm.jpg")
    if not os.path.isfile(wm):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from shop_watermark import ensure_master_watermarked
            ensure_master_watermarked(piece_dir, text="Aethelgard Art Co.", opacity=0.18)
        except Exception as e:
            print(f"Watermark preview for upload skipped: {e}")
    wm_name = "master_wm.jpg" if os.path.isfile(wm) and "master_wm.jpg" not in disabled else None

    by_name = {f: os.path.join(piece_dir, f) for f in mockup_names}
    if wm_name:
        by_name[wm_name] = os.path.join(piece_dir, wm_name)
    ordered_names = []
    for name in photo_order:
        if name in by_name and name not in ordered_names:
            ordered_names.append(name)
    for f in sorted(mockup_names):
        if f not in ordered_names:
            ordered_names.append(f)
    if wm_name and wm_name not in ordered_names:
        ordered_names.append(wm_name)
    if len(ordered_names) > 1 and ordered_names[0] in ("master_wm.jpg", "master_wm.jpeg"):
        ordered_names = ordered_names[1:] + [ordered_names[0]]
    mockups = [by_name[n] for n in ordered_names if n in by_name]

    digital_files = []
    pdf_files = [os.path.join(piece_dir, f) for f in os.listdir(piece_dir) if f.lower().endswith(".pdf")]
    if pdf_files:
        digital_files = [pdf_files[0]]
    else:
        prints_dir = None
        for name in os.listdir(piece_dir):
            sub = os.path.join(piece_dir, name)
            if os.path.isdir(sub) and ("print" in name.lower() or name == "prints"):
                prints_dir = sub
                break
        if prints_dir:
            digital_files = [
                os.path.join(prints_dir, f)
                for f in os.listdir(prints_dir)
                if f.lower().endswith(".jpg")
            ][:5]

    if not os.path.exists(AUTH_STATE_PATH):
        write_status(piece_dir, "failed", f"Auth missing at {AUTH_STATE_PATH}. Run Etsy Authentication first.")
        print(f"Error: Authentication state file not found at {AUTH_STATE_PATH}. Please run with --login first.")
        return False

    write_status(piece_dir, "running", f"Uploading draft for: {title}")
    print(f"Uploading listing for: {title}...")
    chrome_proc = None
    try:
        # Use real Chrome over CDP (same as --login). Bundled Chromium trips Etsy bot walls.
        print("Starting real Google Chrome for upload (not Playwright Chromium)...")
        chrome_proc, err = launch_chrome_for_login()
        if err:
            write_status(piece_dir, "failed", err)
            print(f"[ERROR] {err}")
            return False
        if not wait_for_cdp():
            write_status(piece_dir, "failed", "Chrome CDP did not start. Close other Chrome windows and retry.")
            print("[ERROR] Chrome did not start remote debugging. Close other Chrome windows and retry.")
            return False

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            # Chrome profile from Etsy Authentication already carries the session.
            print_alert(
                "Real Chrome is open.\n"
                "If you are not signed into Etsy in THAT window, sign in now.\n"
                "Then press ENTER here to continue the draft upload."
            )
            input("--> Press [ENTER] when Etsy is signed in in the Chrome window...")
            try:
                await context.storage_state(path=AUTH_STATE_PATH)
            except Exception:
                pass

            async def page_looks_blocked(pg):
                try:
                    text = (await pg.inner_text("body")).lower()
                except Exception:
                    return False
                return (
                    "access is temporarily restricted" in text
                    or "unusual activity" in text
                    or "automated (bot) activity" in text
                )

            # Etsy moved create under /tools/… — old /listings/create is a permanent 404.
            create_urls = [
                "https://www.etsy.com/your/shops/me/tools/listings/create",
                "https://www.etsy.com/your/shops/me/listings/create",
            ]
            listings_hub = "https://www.etsy.com/your/shops/me/tools/listings"
            landed = False
            for url in create_urls:
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                if await page_looks_blocked(page):
                    write_status(
                        piece_dir,
                        "failed",
                        "Etsy temporarily restricted this network (bot wall). Stop retries; use manual draft for now.",
                    )
                    print_alert(
                        "Etsy blocked this IP for automated activity.\n"
                        "STOP clicking Upload Draft.\n"
                        "Wait 1–2 hours (or try phone hotspot), then create the first draft MANUALLY in normal Chrome:\n"
                        "  Shop Manager → Listings → Add a listing\n"
                        "Do not keep retrying — that extends the ban."
                    )
                    input("--> Press [ENTER] to close this upload attempt...")
                    return False
                body = ""
                try:
                    body = (await page.inner_text("body")).lower()
                except Exception:
                    pass
                if "page you were looking for was not found" in body or ("uh oh" in body and "not found" in body):
                    print(f"[warn] 404 at {url}")
                    continue
                if "signin" in page.url or "join" in page.url:
                    break
                landed = True
                print(f"[ok] Opened listing creator via {url}")
                break

            if "signin" in page.url or "join" in page.url:
                write_status(piece_dir, "waiting_manual", "Session expired — log in in the browser.")
                await wait_for_user(page, "Session expired or invalid. Please log in manually in the browser window.")
                await context.storage_state(path=AUTH_STATE_PATH)
                write_status(piece_dir, "running", "Session refreshed; continuing form fill.")
                await page.goto(create_urls[0], wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                if await page_looks_blocked(page):
                    write_status(piece_dir, "failed", "Etsy bot wall after login. Stop and wait.")
                    print_alert("Still blocked after login. Stop retries; create draft manually later.")
                    return False
                landed = True

            if not landed:
                write_status(
                    piece_dir,
                    "waiting_manual",
                    "Could not open create-listing URL — click Add a listing in Shop Manager.",
                )
                await page.goto(listings_hub, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                try:
                    add_btn = page.get_by_role("link", name=re.compile(r"add a listing", re.I))
                    if await add_btn.count() == 0:
                        add_btn = page.get_by_role("button", name=re.compile(r"add a listing", re.I))
                    if await add_btn.count():
                        await add_btn.first.click()
                        await page.wait_for_timeout(2500)
                        landed = True
                        print("[ok] Clicked Add a listing from listings hub")
                except Exception as e:
                    print(f"[warn] Could not click Add a listing: {e}")
                if not landed:
                    await wait_for_user(
                        page,
                        "Open Shop Manager → Listings → Add a listing, then press ENTER here.",
                    )
                    write_status(piece_dir, "running", "Continuing after manual create-listing open.")

            print("Navigated to listing creator. Starting form automation...")

            await fill_field_with_fallback(
                page,
                [
                    'input[name="title"]',
                    'textarea[id="title-input"]',
                    'input[id*="title"]',
                    'textarea[name="title"]',
                ],
                title,
                "Title",
            )

            try:
                await page.select_option('select[data-field="who_made"]', label="I did")
                await page.select_option('select[data-field="is_seller"]', label="A finished product")
                await page.select_option('select[data-field="when_made"]', label="Made to order")
                print("[ok] Selected Who, What, When selects")
            except Exception:
                write_status(piece_dir, "waiting_manual", "Set Who / What / When manually.")
                await wait_for_user(
                    page,
                    "Please set 'Who made it' to 'I did', 'What is it' to 'A finished product', "
                    "and 'When was it made' to 'Made to order' (or similar).",
                )
                write_status(piece_dir, "running", "Continuing after Who/What/When.")

            try:
                digital_radio = await page.wait_for_selector(
                    'input[value="digital"], label:has-text("Digital")', timeout=3000
                )
                await digital_radio.click()
                print("[ok] Selected listing type: Digital")
            except Exception:
                write_status(piece_dir, "waiting_manual", "Select Digital listing type.")
                await wait_for_user(page, "Please select 'Digital' under Listing Type.")
                write_status(piece_dir, "running", "Continuing after listing type.")

            try:
                cat_input = await page.wait_for_selector(
                    'input[data-field="category"], input[placeholder*="category"], input[placeholder*="Category"]',
                    timeout=3000,
                )
                await cat_input.fill("Digital Prints")
                await page.wait_for_timeout(1000)
                await page.keyboard.press("Enter")
                print("[ok] Set category search to 'Digital Prints'")
                await page.wait_for_timeout(2000)
                first_sug = await page.wait_for_selector(
                    'ul.suggestions-list li, button.suggestion-item, [role="option"]', timeout=3000
                )
                await first_sug.click()
                print("[ok] Selected category suggestion")
            except Exception:
                write_status(piece_dir, "waiting_manual", "Select category Digital Prints.")
                await wait_for_user(page, "Please search for and select the category 'Digital Prints' manually.")
                write_status(piece_dir, "running", "Continuing after category.")

            await fill_field_with_fallback(
                page,
                [
                    'textarea[name="description"]',
                    'textarea[id="description-input"]',
                    'textarea[id*="description"]',
                ],
                description,
                "Description",
            )

            await fill_field_with_fallback(
                page,
                ['input[name="price"]', 'input[id="price-input"]', 'input[id*="price"]'],
                price,
                "Price",
            )
            await fill_field_with_fallback(
                page,
                ['input[name="quantity"]', 'input[id="quantity-input"]', 'input[id*="quantity"]'],
                quantity,
                "Quantity",
            )

            if mockups:
                print(f"Uploading {len(mockups)} mockup photos...")
                try:
                    file_input = await page.wait_for_selector('input[type="file"]', timeout=5000)
                    await file_input.set_input_files(mockups)
                    print("[ok] Mockup photos uploaded.")
                    await page.wait_for_timeout(5000)
                except Exception:
                    write_status(piece_dir, "waiting_manual", "Upload mockup photos manually.")
                    await wait_for_user(page, f"Please upload the mockup images manually.\nPaths: {', '.join(mockups)}")
                    write_status(piece_dir, "running", "Continuing after photos.")
            else:
                print("No mockup photos found to upload.")

            if digital_files:
                print(f"Uploading {len(digital_files)} digital print/PDF files...")
                try:
                    file_inputs = await page.query_selector_all('input[type="file"]')
                    digital_input = None
                    for inp in file_inputs:
                        inp_id = (await inp.get_attribute("id") or "").lower()
                        inp_name = (await inp.get_attribute("name") or "").lower()
                        if "digital" in inp_id or "digital" in inp_name or "file" in inp_id:
                            digital_input = inp
                    if digital_input is None and len(file_inputs) > 1:
                        digital_input = file_inputs[-1]
                    if digital_input is not None:
                        await digital_input.set_input_files(digital_files)
                        print("[ok] Digital files uploaded.")
                        await page.wait_for_timeout(5000)
                    else:
                        write_status(piece_dir, "waiting_manual", "Upload digital files manually.")
                        await wait_for_user(
                            page,
                            f"Please upload your digital print files manually.\nPaths: {', '.join(digital_files)}",
                        )
                        write_status(piece_dir, "running", "Continuing after digital files.")
                except Exception:
                    write_status(piece_dir, "waiting_manual", "Upload digital files manually.")
                    await wait_for_user(
                        page,
                        f"Please upload your digital print files manually.\nPaths: {', '.join(digital_files)}",
                    )
                    write_status(piece_dir, "running", "Continuing after digital files.")
            else:
                print("No digital print files found to upload.")

            if tags:
                print(f"Adding {len(tags)} tags...")
                try:
                    tag_input = await page.wait_for_selector(
                        'input[id*="tag-input"], input[data-field="tags"], input[placeholder*="tag"]',
                        timeout=3000,
                    )
                    for tag in tags:
                        await tag_input.focus()
                        await tag_input.fill("")
                        await tag_input.type(tag)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(500)
                    print("[ok] Tags added.")
                except Exception:
                    write_status(piece_dir, "waiting_manual", "Add tags manually.")
                    await wait_for_user(page, f"Please add tags manually.\nTags: {', '.join(tags)}")
                    write_status(piece_dir, "running", "Continuing after tags.")

            print("\nListing details filled out!")
            print("Please check the browser window to verify everything is correct.")

            draft_clicked = False
            for selector in [
                'button:has-text("Save as draft")',
                'button:has-text("Save as Draft")',
                '[data-clg-id*="save-draft"]',
                'button.save-draft-button',
            ]:
                try:
                    save_btn = await page.wait_for_selector(selector, timeout=2500)
                    await save_btn.click()
                    print("[ok] Clicked 'Save as draft'")
                    draft_clicked = True
                    await page.wait_for_timeout(2500)
                    break
                except Exception:
                    continue

            if not draft_clicked:
                write_status(piece_dir, "waiting_manual", "Click Save as draft in the browser.")
                await wait_for_user(page, "Click the 'Save as draft' button in the browser window to finalize the listing.")

            ok, draft_url = await confirm_draft_saved(page, piece_dir)
            if ok:
                meta["uploaded_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if draft_url:
                    meta["etsy_draft_url"] = draft_url
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                print(f"Successfully uploaded {title} as draft on Etsy!")
            else:
                print("Upload did not confirm a saved draft — uploaded_at was NOT written.")

            # Leave real Chrome open (CDP). Closing it mid-session is confusing for operators.
            return ok
    except Exception as e:
        write_status(piece_dir, "failed", f"Upload crashed: {type(e).__name__}: {e}")
        print(f"[ERROR] Upload failed: {type(e).__name__}: {e}")
        return False


async def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python upload_to_etsy.py --login")
        print("  python upload_to_etsy.py --upload <piece_directory>")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "--login":
        await run_login()
    elif cmd == "--upload":
        if len(sys.argv) < 3:
            print("Please specify a piece directory path.")
            sys.exit(1)
        piece_dir = sys.argv[2]
        if not os.path.isabs(piece_dir):
            piece_dir = os.path.abspath(piece_dir)
        ok = await upload_listing(piece_dir)
        sys.exit(0 if ok else 1)
    else:
        print("Unknown command.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
