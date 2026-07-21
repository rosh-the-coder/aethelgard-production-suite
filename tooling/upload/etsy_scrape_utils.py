"""Shared helpers for Etsy Playwright scrapers."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PLAYWRIGHT_BROWSERS = os.path.abspath(
    os.path.join(HERE, "..", "ad-creatives", ".playwright-browsers")
)
AUTH_STATE_PATH = os.path.join(HERE, "auth_state.json")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", PLAYWRIGHT_BROWSERS)


def parse_etsy_number(text):
    """Parse Etsy counts like '2.7k', '2,700', '14,110'."""
    if text is None or text == "":
        return None
    t = str(text).strip().lower().replace(",", "").replace(" ", "")
    if not t or t in (".", "-") or not any(ch.isdigit() for ch in t):
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)(k)?$", t)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    if m.group(2) == "k":
        val *= 1000
    return int(val)


def find_first(patterns, text, flags=re.IGNORECASE):
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m.group(1)
    return None


def normalize_listing_url(href):
    if not href:
        return ""
    if href.startswith("/"):
        href = "https://www.etsy.com" + href
    # Regional paths like /ie/listing/123 still count
    if "/listing/" not in href:
        return ""
    return href.split("?")[0]


def etsy_search_url(query):
    from urllib.parse import quote_plus
    return f"https://www.etsy.com/search?q={quote_plus(query)}"


def is_blocked_page(title, body_text, url, expected_fragment, html=""):
    combined = (body_text or "") + (html or "")
    if not body_text and not html:
        return True
    if "Access Denied" in (title or ""):
        return True
    if "datadome" in combined.lower() or "captcha-delivery.com" in combined.lower():
        return True
    if expected_fragment and expected_fragment.lower() not in (url or "").lower():
        return True
    return False


def blocked_message():
    if os.path.isfile(AUTH_STATE_PATH):
        return (
            "Etsy blocked this request. Your saved login may have expired, or your IP was "
            "temporarily restricted after bot checks. Re-authenticate in real Chrome, wait "
            "30–60 minutes, or try a different network, then retry."
        )
    return (
        "Etsy blocked automated access. Click Etsy Authentication — it opens real Chrome "
        "(not a bot browser). Sign in there, press ENTER in the console, then retry. "
        "If you see 'Access temporarily restricted', wait or switch network."
    )


LOGIN_PROFILE_DIR = os.path.join(HERE, ".etsy-login-profile")
CHROME_PROFILE_DIR = os.path.join(HERE, ".etsy-chrome-profile")
CDP_PORT = 9222


def find_chrome_exe():
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def launch_chrome_for_login():
    """Start real Chrome with remote debugging — no Playwright automation flags."""
    import subprocess

    chrome = find_chrome_exe()
    if not chrome:
        return None, "Google Chrome is not installed. Install Chrome, then retry Etsy Authentication."

    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    proc = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={CDP_PORT}",
            f'--user-data-dir={CHROME_PROFILE_DIR}',
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.etsy.com/",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc, None


def wait_for_cdp(timeout_sec=20):
    import time
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{CDP_PORT}/json/version"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.4)
    return False


async def launch_browser(playwright, headless=True):
    """Prefer installed Chrome; fall back to bundled Chromium."""
    launch_kwargs = {"headless": headless}
    try:
        return await playwright.chromium.launch(channel="chrome", **launch_kwargs)
    except Exception:
        return await playwright.chromium.launch(**launch_kwargs)


async def new_etsy_context(browser):
    kwargs = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "locale": "en-US",
    }
    if os.path.isfile(AUTH_STATE_PATH):
        return await browser.new_context(storage_state=AUTH_STATE_PATH, **kwargs)
    return await browser.new_context(**kwargs)
