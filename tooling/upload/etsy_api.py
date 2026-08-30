"""
Etsy Open API v3 client for Aethelgard draft listings.

This is the durable upload path: OAuth PKCE + createDraftListing + images/files.
It does NOT drive the Seller Manager UI (which trips bot walls).

Setup:
  1. https://www.etsy.com/developers/register — create an app
  2. Set callback URL to: http://localhost:8080/api/etsy/oauth/callback
  3. Put keystring in ~/.config/ai-images/env as ETSY_API_KEY=...
     (or tooling/upload/etsy_app.json → {"keystring": "..."})
  4. Dashboard → Connect Etsy API → approve scopes
  5. Upload Draft (API)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS_PATH = os.path.join(HERE, "etsy_tokens.json")
APP_CONFIG_PATH = os.path.join(HERE, "etsy_app.json")
OAUTH_PENDING_PATH = os.path.join(HERE, ".etsy_oauth_pending.json")
ENV_FILE = os.path.expanduser("~/.config/ai-images/env")

AUTH_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
API_BASE = "https://openapi.etsy.com/v3/application"

# Local suite callback (must match the app registration on Etsy)
# Etsy rejects IP callback URLs — use hostname "localhost", not 127.0.0.1
DEFAULT_REDIRECT_URI = "http://localhost:8080/api/etsy/oauth/callback"

SCOPES = " ".join(
    [
        "listings_r",
        "listings_w",
        "shops_r",
        "shops_w",
    ]
)

# Fallback if taxonomy lookup fails — Art & Collectibles › Prints › Digital Prints
# (verified via seller-taxonomy when online; override in etsy_app.json if needed)
DEFAULT_TAXONOMY_ID = 2078


def _read_env_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if os.path.isfile(ENV_FILE):
        try:
            raw = None
            for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    with open(ENV_FILE, "r", encoding=enc) as f:
                        raw = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            if raw is None:
                with open(ENV_FILE, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def load_app_config() -> dict:
    cfg = {
        "keystring": _read_env_key("ETSY_API_KEY") or _read_env_key("ETSY_KEYSTRING"),
        "shared_secret": _read_env_key("ETSY_SHARED_SECRET") or _read_env_key("ETSY_API_SECRET"),
        "redirect_uri": DEFAULT_REDIRECT_URI,
        "taxonomy_id": DEFAULT_TAXONOMY_ID,
        "shop_id": None,
    }
    if os.path.isfile(APP_CONFIG_PATH):
        try:
            with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                # Never pull secrets from disk logs into responses elsewhere; config may store shop_id/taxonomy only
                cfg.update({k: v for k, v in disk.items() if v not in (None, "")})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_app_config(updates: dict) -> dict:
    cfg = load_app_config()
    cfg.update(updates)
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def load_tokens() -> dict:
    if not os.path.isfile(TOKENS_PATH):
        return {}
    try:
        with open(TOKENS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_tokens(tokens: dict) -> None:
    tokens = dict(tokens)
    tokens["saved_at"] = int(time.time())
    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def api_status() -> dict:
    cfg = load_app_config()
    tokens = load_tokens()
    has_key = bool(cfg.get("keystring"))
    has_secret = bool(cfg.get("shared_secret"))
    has_token = bool(tokens.get("access_token"))
    expires_at = tokens.get("expires_at")
    expired = bool(expires_at and time.time() > float(expires_at) - 60)
    return {
        "keystring_configured": has_key,
        "shared_secret_configured": has_secret,
        "oauth_connected": has_token and not expired,
        "has_refresh_token": bool(tokens.get("refresh_token")),
        "shop_id": cfg.get("shop_id") or tokens.get("shop_id"),
        "taxonomy_id": cfg.get("taxonomy_id") or DEFAULT_TAXONOMY_ID,
        "redirect_uri": cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI,
        "tokens_path": TOKENS_PATH if has_token else None,
    }


def api_key_header_value() -> str:
    """Etsy requires x-api-key: keystring:shared_secret (enforced since Feb 2026)."""
    cfg = load_app_config()
    key = (cfg.get("keystring") or "").strip()
    secret = (cfg.get("shared_secret") or "").strip()
    if not key:
        raise RuntimeError("Missing ETSY_API_KEY (keystring) in ~/.config/ai-images/env")
    if not secret:
        raise RuntimeError(
            "Missing ETSY_SHARED_SECRET in ~/.config/ai-images/env. "
            "Copy the Shared secret from https://www.etsy.com/developers/your-apps"
        )
    if ":" in key:
        return key  # already combined
    return f"{key}:{secret}"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def begin_oauth() -> dict:
    cfg = load_app_config()
    key = cfg.get("keystring") or ""
    if not key:
        raise RuntimeError(
            "Missing ETSY_API_KEY / keystring. Register an app at "
            "https://www.etsy.com/developers/register and save the keystring."
        )
    if not (cfg.get("shared_secret") or "").strip():
        raise RuntimeError(
            "Missing ETSY_SHARED_SECRET. Add it next to ETSY_API_KEY in ~/.config/ai-images/env "
            "(from https://www.etsy.com/developers/your-apps)."
        )
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    redirect_uri = cfg.get("redirect_uri") or DEFAULT_REDIRECT_URI
    params = {
        "response_type": "code",
        "client_id": key,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    pending = {
        "verifier": verifier,
        "state": state,
        "redirect_uri": redirect_uri,
        "created_at": int(time.time()),
    }
    with open(OAUTH_PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(pending, f, indent=2)
    return {"authorize_url": url, "redirect_uri": redirect_uri}


def finish_oauth(code: str, state: str) -> dict:
    if not os.path.isfile(OAUTH_PENDING_PATH):
        raise RuntimeError("No pending OAuth — click Connect Etsy API again.")
    with open(OAUTH_PENDING_PATH, "r", encoding="utf-8") as f:
        pending = json.load(f)
    if state != pending.get("state"):
        raise RuntimeError("OAuth state mismatch — retry Connect Etsy API.")
    cfg = load_app_config()
    key = cfg["keystring"]
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": key,
            "redirect_uri": pending.get("redirect_uri") or DEFAULT_REDIRECT_URI,
            "code": code,
            "code_verifier": pending["verifier"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        tokens = json.loads(resp.read().decode("utf-8"))
    expires_in = int(tokens.get("expires_in") or 3600)
    tokens["expires_at"] = int(time.time()) + expires_in
    save_tokens(tokens)
    try:
        os.remove(OAUTH_PENDING_PATH)
    except OSError:
        pass
    # Resolve shop id for later uploads
    try:
        shop_id = None
        user_id = _user_id_from_token(tokens)
        try:
            me = api_get("/users/me", tokens=tokens)
            user_id = me.get("user_id") or user_id
        except Exception:
            pass
        if user_id:
            shops = api_get(f"/users/{user_id}/shops", tokens=tokens)
            shop_id = _extract_shop_id(shops)
        if not shop_id:
            for name in ("AethelgardArtCo", "Aethelgard Art Co"):
                found = api_get(f"/shops?shop_name={urllib.parse.quote(name)}", tokens=tokens)
                shop_id = _extract_shop_id(found)
                if shop_id:
                    break
        if shop_id:
            tokens["shop_id"] = shop_id
            save_tokens(tokens)
            save_app_config({"shop_id": shop_id})
    except Exception as e:
        tokens["shop_resolve_error"] = str(e)
        save_tokens(tokens)
    return {"success": True, "shop_id": tokens.get("shop_id")}


def refresh_access_token() -> dict:
    cfg = load_app_config()
    tokens = load_tokens()
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("No refresh token — Connect Etsy API again.")
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": cfg["keystring"],
            "refresh_token": refresh,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        fresh = json.loads(resp.read().decode("utf-8"))
    tokens.update(fresh)
    expires_in = int(fresh.get("expires_in") or 3600)
    tokens["expires_at"] = int(time.time()) + expires_in
    save_tokens(tokens)
    return tokens


def _ensure_tokens() -> dict:
    tokens = load_tokens()
    if not tokens.get("access_token"):
        raise RuntimeError("Etsy API not connected. Use Connect Etsy API in the dashboard.")
    exp = tokens.get("expires_at")
    if exp and time.time() > float(exp) - 120:
        tokens = refresh_access_token()
    return tokens


def _headers(tokens: Optional[dict] = None) -> dict:
    tokens = tokens or _ensure_tokens()
    return {
        "x-api-key": api_key_header_value(),
        "Authorization": f"Bearer {tokens['access_token']}",
    }


def api_request(
    method: str,
    path: str,
    data: Any = None,
    tokens: Optional[dict] = None,
    form: bool = False,
    json_body: Any = None,
) -> dict:
    """
    Call Etsy Open API.
    Prefer json_body for create/update listing — form-urlencoded array fields
    (tags=a&tags=b) are collapsed to the last value by Etsy's parser.
    """
    url = path if path.startswith("http") else API_BASE + path
    headers = _headers(tokens)
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif data is not None and not form:
        body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Etsy API {method} {path} → {e.code}: {err_body[:800]}") from e


def api_get(path: str, tokens: Optional[dict] = None) -> dict:
    return api_request("GET", path, tokens=tokens)


def api_post_form(path: str, fields: dict, tokens: Optional[dict] = None) -> dict:
    return api_request("POST", path, data=fields, tokens=tokens)


def api_json(method: str, path: str, payload: dict, tokens: Optional[dict] = None) -> dict:
    return api_request(method, path, json_body=payload, tokens=tokens)


def _multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----AethelgardBoundary" + secrets.token_hex(8)
    lines: list[bytes] = []
    for k, v in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        lines.append(str(v).encode("utf-8"))
        lines.append(b"\r\n")
    for field_name, filename, content, content_type in files:
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
        )
        lines.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        lines.append(content)
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    return b"".join(lines), f"multipart/form-data; boundary={boundary}"


def api_post_multipart(path: str, fields: dict, files: list, tokens: Optional[dict] = None) -> dict:
    tokens = tokens or _ensure_tokens()
    body, content_type = _multipart(fields, files)
    url = API_BASE + path
    headers = _headers(tokens)
    headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Etsy API multipart {path} → {e.code}: {err_body[:800]}") from e


def _user_id_from_token(tokens: Optional[dict] = None) -> Optional[int]:
    """Etsy access tokens are typically '{user_id}.{secret}'."""
    tokens = tokens or load_tokens()
    access = (tokens.get("access_token") or "").strip()
    if "." in access:
        head = access.split(".", 1)[0]
        if head.isdigit():
            return int(head)
    return None


def _extract_shop_id(payload: Any) -> Optional[int]:
    if not payload:
        return None
    if isinstance(payload, dict):
        if payload.get("shop_id"):
            try:
                return int(payload["shop_id"])
            except (TypeError, ValueError):
                pass
        for key in ("results", "shops"):
            items = payload.get(key)
            if isinstance(items, list) and items:
                sid = _extract_shop_id(items[0])
                if sid:
                    return sid
        # Nested shop object
        if isinstance(payload.get("shop"), dict):
            return _extract_shop_id(payload["shop"])
    if isinstance(payload, list) and payload:
        return _extract_shop_id(payload[0])
    return None


def resolve_shop_id() -> int:
    cfg = load_app_config()
    tokens = _ensure_tokens()

    env_shop = _read_env_key("ETSY_SHOP_ID")
    if env_shop and str(env_shop).isdigit():
        shop_id = int(env_shop)
        save_app_config({"shop_id": shop_id})
        tokens["shop_id"] = shop_id
        save_tokens(tokens)
        return shop_id

    if cfg.get("shop_id"):
        return int(cfg["shop_id"])
    if tokens.get("shop_id"):
        return int(tokens["shop_id"])

    errors = []
    user_id = _user_id_from_token(tokens)
    try:
        me = api_get("/users/me", tokens=tokens)
        user_id = me.get("user_id") or user_id
    except Exception as e:
        errors.append(f"/users/me: {e}")

    if user_id:
        try:
            # getShopByOwnerUserId — returns a Shop object (not always a results list)
            shops = api_get(f"/users/{user_id}/shops", tokens=tokens)
            shop_id = _extract_shop_id(shops)
            if shop_id:
                save_app_config({"shop_id": shop_id})
                tokens["shop_id"] = shop_id
                save_tokens(tokens)
                return shop_id
            errors.append(f"/users/{user_id}/shops returned no shop_id: {str(shops)[:200]}")
        except Exception as e:
            errors.append(f"/users/{user_id}/shops: {e}")

    # Fallback: public findShops by shop name
    for name in ("AethelgardArtCo", "Aethelgard Art Co", "aethelgardartco"):
        try:
            found = api_get(f"/shops?shop_name={urllib.parse.quote(name)}", tokens=tokens)
            shop_id = _extract_shop_id(found)
            if shop_id:
                save_app_config({"shop_id": shop_id})
                tokens["shop_id"] = shop_id
                save_tokens(tokens)
                return shop_id
        except Exception as e:
            errors.append(f"findShops({name}): {e}")

    hint = (
        "Could not resolve your Etsy shop_id. "
        "Open your shop in a browser (Shop Manager) and check the URL for a numeric id, "
        "or add ETSY_SHOP_ID=12345678 to ~/.config/ai-images/env. "
        f"Details: {' | '.join(errors)[:500]}"
    )
    raise RuntimeError(hint)


def find_digital_prints_taxonomy_id() -> int:
    cfg = load_app_config()
    if cfg.get("taxonomy_id"):
        return int(cfg["taxonomy_id"])
    try:
        tree = api_get("/seller-taxonomy/nodes")
        nodes = tree.get("results") or []

        def walk(items):
            for n in items:
                name = (n.get("name") or "").lower()
                if name == "digital prints":
                    return int(n["id"])
                kids = n.get("children") or []
                hit = walk(kids)
                if hit:
                    return hit
            return None

        found = walk(nodes)
        if found:
            save_app_config({"taxonomy_id": found})
            return found
    except Exception:
        pass
    return DEFAULT_TAXONOMY_ID


def _gather_piece_assets(piece_dir: str) -> tuple[list[str], list[str], dict]:
    meta_path = os.path.join(piece_dir, "meta.json")
    listing_path = os.path.join(piece_dir, "listing.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    listing = {}
    if os.path.isfile(listing_path):
        with open(listing_path, "r", encoding="utf-8") as f:
            listing = json.load(f)

    prefs = meta.get("mockup_prefs", {}) or {}
    disabled = set(prefs.get("disabled_mockups", []) or [])
    photo_order = [str(x) for x in (prefs.get("photo_order") or []) if x]

    mockup_files = []
    for f in os.listdir(piece_dir):
        low = f.lower()
        if low.startswith("mockup_") and low.endswith(".jpg") and f not in disabled:
            mockup_files.append(f)

    wm_name = None
    for candidate in ("master_wm.jpg", "master_wm.jpeg"):
        if os.path.isfile(os.path.join(piece_dir, candidate)) and candidate not in disabled:
            wm_name = candidate
            break

    # Build ordered list: respect photo_order, but never allow watermark as rank 1
    # unless it is the only photo. Prefer overview grids early (after cover lifestyle).
    by_name = {f: os.path.join(piece_dir, f) for f in mockup_files}
    if wm_name:
        by_name[wm_name] = os.path.join(piece_dir, wm_name)

    overview = sorted(f for f in mockup_files if f.lower().startswith("mockup_overview_"))
    room = sorted(f for f in mockup_files if not f.lower().startswith("mockup_overview_"))

    ordered_names = []
    for name in photo_order:
        if name in by_name and name not in ordered_names:
            ordered_names.append(name)
    # If no explicit order, cover = first room mockup, then overview sheets, then rest
    if not photo_order:
        if room:
            ordered_names.append(room[0])
        for f in overview:
            if f not in ordered_names:
                ordered_names.append(f)
        for f in room[1:]:
            if f not in ordered_names:
                ordered_names.append(f)
    else:
        for f in overview + room:
            if f not in ordered_names:
                ordered_names.append(f)
    if wm_name and wm_name not in ordered_names:
        ordered_names.append(wm_name)

    if len(ordered_names) > 1 and ordered_names[0] in ("master_wm.jpg", "master_wm.jpeg"):
        # Push watermark off cover
        ordered_names = ordered_names[1:] + [ordered_names[0]]

    photos = [by_name[n] for n in ordered_names if n in by_name]

    digital = []
    for name in ("Download_Links.pdf",):
        p = os.path.join(piece_dir, name)
        if os.path.isfile(p):
            digital.append(p)
            break
    if not digital:
        pdfs = [
            os.path.join(piece_dir, f)
            for f in os.listdir(piece_dir)
            if f.lower().endswith(".pdf") and f.lower().startswith("download_links")
        ]
        digital = pdfs[:1]
    return photos[:10], digital[:5], {**meta, "listing": listing}


def _sanitize_etsy_tag(tag: str) -> str:
    """Etsy tags: letters, numbers, spaces, -, ', ™, ©, ® — max 20 chars."""
    # Avoid \\w (allows _) — Etsy regex is letters/numbers/spaces/hyphen/apostrophe/marks only.
    t = re.sub(r"[^\w\s\-'\u2122\u00a9\u00ae]", " ", str(tag or ""), flags=re.UNICODE)
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip(" ,")
    return t[:20]


def _sanitize_etsy_material(mat: str) -> str:
    """Etsy materials: letters, numbers, whitespace only — max 45 chars."""
    m = re.sub(r"[^\w\s]", " ", str(mat or ""), flags=re.UNICODE)
    m = m.replace("_", " ")
    m = re.sub(r"\s+", " ", m).strip()
    return m[:45]


def _sanitize_etsy_title(title: str) -> str:
    """Etsy listing titles: max 140 chars; colon may appear only once."""
    t = re.sub(r"\s+", " ", str(title or "").strip()) or "Digital Print"
    if t.count(":") > 1:
        first, rest = t.split(":", 1)
        rest = rest.replace(":", " -")
        t = f"{first}:{rest}"
        t = re.sub(r"\s+", " ", t).replace(" - -", " -").strip()
    return t[:140]


def _normalize_tags_materials(raw_tags: Any, raw_materials: Any) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    seen: set[str] = set()
    for t in raw_tags or []:
        clean = _sanitize_etsy_tag(t)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            tags.append(clean)
        if len(tags) >= 13:
            break
    materials: list[str] = []
    seen_m: set[str] = set()
    for m in raw_materials or []:
        clean = _sanitize_etsy_material(m)
        key = clean.lower()
        if clean and key not in seen_m:
            seen_m.add(key)
            materials.append(clean)
        if len(materials) >= 13:
            break
    return tags, materials


def update_listing_tags_materials(
    listing_id: int | str,
    tags: list[str],
    materials: list[str] | None = None,
    shop_id: int | str | None = None,
) -> dict:
    """PATCH an existing listing with tags/materials as a JSON array (not form fields)."""
    shop_id = shop_id or resolve_shop_id()
    payload: dict[str, Any] = {"tags": tags}
    if materials is not None:
        payload["materials"] = materials
    resp = api_json("PATCH", f"/shops/{shop_id}/listings/{listing_id}", payload)
    got = resp.get("tags") or []
    if tags and len(got) < len(tags):
        raise RuntimeError(
            f"Etsy kept only {len(got)}/{len(tags)} tags after PATCH: {got!r}. "
            "Expected JSON array encoding."
        )
    return resp


def sync_piece_tags_to_etsy(piece_dir: str) -> dict:
    """Push on-disk SEO tags/materials onto an existing Etsy draft (meta.etsy_listing_id)."""
    meta_path = os.path.join(piece_dir, "meta.json")
    listing_path = os.path.join(piece_dir, "listing.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    listing = {}
    if os.path.isfile(listing_path):
        with open(listing_path, "r", encoding="utf-8") as f:
            listing = json.load(f)
    listing_id = meta.get("etsy_listing_id")
    if not listing_id:
        raise RuntimeError("No etsy_listing_id on this piece — upload a draft first.")
    raw_tags = listing.get("tags") or meta.get("seo", {}).get("tags") or []
    raw_materials = listing.get("materials") or meta.get("seo", {}).get("materials") or []
    tags, materials = _normalize_tags_materials(raw_tags, raw_materials)
    if not tags:
        raise RuntimeError("No tags found in listing.json / meta.seo")
    resp = update_listing_tags_materials(listing_id, tags, materials)
    return {
        "success": True,
        "listing_id": listing_id,
        "tags": resp.get("tags") or tags,
        "materials": resp.get("materials") or materials,
        "draft_url": meta.get("etsy_draft_url")
        or f"https://www.etsy.com/your/shops/me/tools/listings/{listing_id}",
    }


def create_draft_from_piece(piece_dir: str, who_made: str = "i_did") -> dict:
    """
    Create an Etsy draft listing from a suite piece folder.
    who_made: i_did | collective | someone_else  (use someone_else for PD packs when honest)
    """
    if not os.path.isdir(piece_dir):
        raise RuntimeError("Invalid piece_dir")
    photos, digital_files, meta = _gather_piece_assets(piece_dir)
    pdf_on_disk = any(
        f.lower().endswith(".pdf") and f.lower().startswith("download_links")
        for f in os.listdir(piece_dir)
    )
    if pdf_on_disk and not digital_files:
        raise RuntimeError(
            "Download_Links PDF exists on disk but was not selected for upload. "
            "Re-run Compile PDF or check the piece folder."
        )
    listing = meta.get("listing") or {}
    title = _sanitize_etsy_title(listing.get("title") or meta.get("title") or "Digital Print")
    description = listing.get("description") or meta.get("seo", {}).get("description") or title
    raw_tags = listing.get("tags") or meta.get("seo", {}).get("tags") or []
    raw_materials = listing.get("materials") or meta.get("seo", {}).get("materials") or []
    tags, materials = _normalize_tags_materials(raw_tags, raw_materials)
    price = float(meta.get("price") or 2.99)
    quantity = int(meta.get("quantity") or 999)
    shop_id = resolve_shop_id()
    taxonomy_id = find_digital_prints_taxonomy_id()

    # Etsy rejects someone_else + made_to_order + finished product unless you attach
    # production_partner_ids ("invalid_marketplace"). Only force someone_else for true
    # public-domain packs when a partner id is configured — never for AI "bundle" sets.
    mode = (meta.get("mode") or meta.get("product_type") or "").lower()
    cfg = load_app_config()
    partner_ids = cfg.get("production_partner_ids") or meta.get("production_partner_ids") or []
    if isinstance(partner_ids, (str, int)):
        partner_ids = [partner_ids]
    partner_ids = [str(p) for p in partner_ids if p]

    is_pd = (
        "public_domain" in mode
        or meta.get("productType") == "pd_bundle"
        or meta.get("product_type") == "pd_bundle"
        or (meta.get("product_type") or "").lower() in ("public_domain_pack", "pd_pack")
    )
    if is_pd and partner_ids:
        who_made = "someone_else"
    else:
        # AI / designed digital downloads (including set-of-N bundles): you made the listing assets
        who_made = who_made if who_made in ("i_did", "collective") else "i_did"

    # Create draft with form fields (Etsy createDraftListing is form-urlencoded).
    # Tags/materials MUST be applied in a follow-up JSON PATCH — form arrays
    # collapse to the last value only (Modern / JPEG). Never skip that PATCH.
    form_fields = {
        "quantity": quantity,
        "title": title,
        "description": description,
        "price": f"{price:.2f}",
        "who_made": who_made,
        "when_made": "made_to_order",
        "taxonomy_id": taxonomy_id,
        "type": "download",
        "is_supply": "false",
        "should_auto_renew": "true",
    }
    if who_made == "someone_else" and partner_ids:
        # Repeated keys via doseq
        form_fields["production_partner_ids"] = partner_ids

    try:
        listing_resp = api_request("POST", f"/shops/{shop_id}/listings", data=form_fields)
    except RuntimeError as e:
        msg = str(e)
        if "invalid_marketplace" in msg:
            raise RuntimeError(
                "Etsy rejected this draft (invalid_marketplace). "
                "Usually who_made=someone_else without a production partner, "
                "or an illegal Who/When/Supply combo. "
                "Sets and AI prints now default to who_made=i_did. "
                f"Original: {msg[:400]}"
            ) from e
        raise
    listing_id = listing_resp.get("listing_id")
    if not listing_id:
        raise RuntimeError(f"Draft create returned no listing_id: {listing_resp}")

    if tags or materials:
        listing_resp = update_listing_tags_materials(
            listing_id, tags, materials or [], shop_id=shop_id
        )
        # Re-read to confirm (Shop Manager caches; API is source of truth)
        verify = api_get(f"/listings/{listing_id}")
        got_tags = verify.get("tags") or []
        if tags and len(got_tags) < len(tags):
            raise RuntimeError(
                f"Draft {listing_id} created but tags did not stick "
                f"({len(got_tags)}/{len(tags)}): {got_tags!r}"
            )
    uploaded_images = []
    for i, path in enumerate(photos):
        with open(path, "rb") as f:
            content = f.read()
        name = os.path.basename(path)
        ctype = "image/jpeg"
        resp = api_post_multipart(
            f"/shops/{shop_id}/listings/{listing_id}/images",
            fields={"rank": str(i + 1)},
            files=[("image", name, content, ctype)],
        )
        uploaded_images.append(resp.get("listing_image_id") or name)

    uploaded_files = []
    for path in digital_files:
        with open(path, "rb") as f:
            content = f.read()
        name = os.path.basename(path)
        ctype = "application/pdf" if name.lower().endswith(".pdf") else "application/octet-stream"
        resp = api_post_multipart(
            f"/shops/{shop_id}/listings/{listing_id}/files",
            fields={"name": name},
            files=[("file", name, content, ctype)],
        )
        uploaded_files.append(resp.get("listing_file_id") or name)

    if pdf_on_disk and len(uploaded_files) == 0:
        raise RuntimeError(
            "Listing draft was created but PDF digital-file upload failed (0 files attached). "
            f"Check Shop Manager → Pricing & Delivery for listing {listing_id}."
        )

    draft_url = f"https://www.etsy.com/your/shops/me/tools/listings/{listing_id}"
    meta_path = os.path.join(piece_dir, "meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            disk_meta = json.load(f)
        disk_meta["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        disk_meta["etsy_listing_id"] = listing_id
        disk_meta["etsy_draft_url"] = draft_url
        disk_meta["etsy_upload_via"] = "open_api"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(disk_meta, f, indent=2)
    except OSError:
        pass

    return {
        "success": True,
        "listing_id": listing_id,
        "draft_url": draft_url,
        "images_uploaded": len(uploaded_images),
        "files_uploaded": len(uploaded_files),
        "photo_order": [os.path.basename(p) for p in photos],
        "digital_files": [os.path.basename(p) for p in digital_files],
        "title": title,
        "shop_id": shop_id,
        "tags": tags,
        "materials": materials,
        "tip": (
            "Confirm the PDF under Shop Manager → Pricing & Delivery (keep listing type Digital). "
            "Preview → About this item should show Digital file type(s): PDF."
        ),
    }
