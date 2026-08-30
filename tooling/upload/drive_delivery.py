"""
Google Drive delivery for Aethelgard listings.

Layout under the configured root folder (default: Etsy 2026):

  Etsy 2026/
    00_Mockups_Private/          # owner-only — never shared
      {listing-slug}/
        mockup_*.jpg
    01_Customer_Delivery/        # shareable parent
      {listing-slug}/            # anyone-with-link (reader)
        print / pack files
        (PDF is generated locally with this folder's share link)

Setup:
  1. Google Cloud Console → create OAuth client (Desktop app)
  2. Download JSON → tooling/upload/gdrive_client.json
     OR set GOOGLE_DRIVE_CLIENT_ID + GOOGLE_DRIVE_CLIENT_SECRET in ~/.config/ai-images/env
  3. Enable Google Drive API on the project
  4. Dashboard → Connect Google Drive → approve
  5. Catalog → Package to Drive & Compile PDF
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_PATH = os.path.join(HERE, "gdrive_client.json")
TOKENS_PATH = os.path.join(HERE, "gdrive_tokens.json")
OAUTH_PENDING_PATH = os.path.join(HERE, ".gdrive_oauth_pending.json")
ENV_FILE = os.path.expanduser("~/.config/ai-images/env")

DEFAULT_ROOT_FOLDER_ID = "1owjKwkil2H-7jli52jbkIhexxXclhkQk"
DEFAULT_REDIRECT_URI = "http://localhost:8080/api/drive/oauth/callback"
MOCKUPS_FOLDER_NAME = "00_Mockups_Private"
CUSTOMER_FOLDER_NAME = "01_Customer_Delivery"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]


def _read_env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if not os.path.isfile(ENV_FILE):
        return ""
    try:
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(ENV_FILE, "r", encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            return ""
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip("\"'")
    except OSError:
        pass
    return ""


def _slug(text: str, fallback: str = "listing") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:80] or fallback)


def load_client_config() -> Dict[str, Any]:
    """Return OAuth client config for an installed/desktop app."""
    cfg: Dict[str, Any] = {
        "client_id": _read_env("GOOGLE_DRIVE_CLIENT_ID"),
        "client_secret": _read_env("GOOGLE_DRIVE_CLIENT_SECRET"),
        "redirect_uri": _read_env("GOOGLE_DRIVE_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        "root_folder_id": _read_env("GOOGLE_DRIVE_ROOT_FOLDER_ID") or DEFAULT_ROOT_FOLDER_ID,
    }
    if os.path.isfile(CLIENT_SECRETS_PATH):
        try:
            with open(CLIENT_SECRETS_PATH, "r", encoding="utf-8") as f:
                disk = json.load(f)
            installed = disk.get("installed") or disk.get("web") or disk
            if isinstance(installed, dict):
                cfg["client_id"] = installed.get("client_id") or cfg["client_id"]
                cfg["client_secret"] = installed.get("client_secret") or cfg["client_secret"]
                redirects = installed.get("redirect_uris") or []
                if redirects and not _read_env("GOOGLE_DRIVE_REDIRECT_URI"):
                    # Prefer localhost callback that matches our server
                    for r in redirects:
                        if "localhost:8080" in r or "127.0.0.1:8080" in r:
                            cfg["redirect_uri"] = r.replace("127.0.0.1", "localhost")
                            break
        except Exception as e:
            print(f"drive_delivery: could not read gdrive_client.json: {e}")
    return cfg


def status() -> Dict[str, Any]:
    cfg = load_client_config()
    connected = False
    email = None
    if os.path.isfile(TOKENS_PATH):
        try:
            with open(TOKENS_PATH, "r", encoding="utf-8") as f:
                tok = json.load(f)
            connected = bool(tok.get("refresh_token") or tok.get("token"))
            email = tok.get("account_email")
        except Exception:
            connected = False
    return {
        "connected": connected,
        "client_configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "root_folder_id": cfg.get("root_folder_id") or DEFAULT_ROOT_FOLDER_ID,
        "redirect_uri": cfg.get("redirect_uri"),
        "account_email": email,
        "mockups_folder_name": MOCKUPS_FOLDER_NAME,
        "customer_folder_name": CUSTOMER_FOLDER_NAME,
        "setup_hint": (
            None
            if (cfg.get("client_id") and cfg.get("client_secret"))
            else "Add tooling/upload/gdrive_client.json (Desktop OAuth client) or GOOGLE_DRIVE_CLIENT_ID/SECRET in ~/.config/ai-images/env"
        ),
    }


def begin_oauth() -> Dict[str, Any]:
    from google_auth_oauthlib.flow import Flow

    cfg = load_client_config()
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        raise RuntimeError(
            "Google Drive OAuth client not configured. "
            "Save Desktop client JSON as tooling/upload/gdrive_client.json "
            "or set GOOGLE_DRIVE_CLIENT_ID + GOOGLE_DRIVE_CLIENT_SECRET."
        )

    client_config = {
        "web": {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [cfg["redirect_uri"]],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = cfg["redirect_uri"]
    state = secrets.token_urlsafe(24)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    with open(OAUTH_PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "state": state,
                "redirect_uri": cfg["redirect_uri"],
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                # PKCE verifier must survive the browser redirect round-trip
                "code_verifier": getattr(flow, "code_verifier", None),
                "created_at": time.time(),
            },
            f,
            indent=2,
        )
    return {"auth_url": auth_url, "state": state}


def finish_oauth(code: str, state: str) -> Dict[str, Any]:
    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials

    if not os.path.isfile(OAUTH_PENDING_PATH):
        raise RuntimeError("No pending Google Drive OAuth — start Connect Google Drive again.")
    with open(OAUTH_PENDING_PATH, "r", encoding="utf-8") as f:
        pending = json.load(f)
    if state and pending.get("state") and state != pending["state"]:
        raise RuntimeError("OAuth state mismatch — try Connect Google Drive again.")

    client_config = {
        "web": {
            "client_id": pending["client_id"],
            "client_secret": pending["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [pending["redirect_uri"]],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, state=pending["state"])
    flow.redirect_uri = pending["redirect_uri"]
    if pending.get("code_verifier"):
        flow.code_verifier = pending["code_verifier"]
    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "saved_at": time.time(),
    }
    # Best-effort account email
    try:
        service = _service_from_creds(creds)
        about = service.about().get(fields="user(emailAddress,displayName)").execute()
        user = about.get("user") or {}
        payload["account_email"] = user.get("emailAddress")
        payload["account_name"] = user.get("displayName")
    except Exception as e:
        print(f"drive_delivery: could not read account email: {e}")

    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    try:
        os.remove(OAUTH_PENDING_PATH)
    except OSError:
        pass
    return {"success": True, "account_email": payload.get("account_email")}


def _service_from_creds(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not os.path.isfile(TOKENS_PATH):
        raise RuntimeError("Google Drive not connected. Use Connect Google Drive in the suite.")
    with open(TOKENS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        data["token"] = creds.token
        data["expiry"] = creds.expiry.isoformat() if creds.expiry else None
        with open(TOKENS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    if not creds.valid:
        raise RuntimeError("Google Drive credentials invalid — reconnect.")
    return _service_from_creds(creds)


def _escape_query(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace("'", "\\'")


def find_child_folder(service, parent_id: str, name: str) -> Optional[str]:
    q = (
        f"name = '{_escape_query(name)}' and '{parent_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id, name)", pageSize=10)
        .execute()
    )
    files = res.get("files") or []
    return files[0]["id"] if files else None


def ensure_folder(service, parent_id: str, name: str) -> str:
    existing = find_child_folder(service, parent_id, name)
    if existing:
        return existing
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id").execute()
    return created["id"]


def ensure_layout(service, root_folder_id: str) -> Dict[str, str]:
    mockups_id = ensure_folder(service, root_folder_id, MOCKUPS_FOLDER_NAME)
    customer_id = ensure_folder(service, root_folder_id, CUSTOMER_FOLDER_NAME)
    return {"mockups_id": mockups_id, "customer_id": customer_id, "root_id": root_folder_id}


def upload_file(service, local_path: str, parent_id: str, name: Optional[str] = None) -> str:
    from googleapiclient.http import MediaFileUpload

    fname = name or os.path.basename(local_path)
    mime, _ = mimetypes.guess_type(fname)
    mime = mime or "application/octet-stream"

    # Replace existing same-name file in folder (idempotent re-package)
    q = (
        f"name = '{_escape_query(fname)}' and '{parent_id}' in parents "
        "and trashed = false"
    )
    existing = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id)", pageSize=5)
        .execute()
        .get("files")
        or []
    )
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    if existing:
        updated = (
            service.files()
            .update(fileId=existing[0]["id"], media_body=media, fields="id")
            .execute()
        )
        return updated["id"]
    created = (
        service.files()
        .create(
            body={"name": fname, "parents": [parent_id]},
            media_body=media,
            fields="id",
        )
        .execute()
    )
    return created["id"]


def share_anyone_with_link(service, file_id: str) -> str:
    """Make folder readable by anyone with the link; return webViewLink."""
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
    except Exception as e:
        # Permission may already exist
        msg = str(e).lower()
        if "already" not in msg and "exists" not in msg:
            print(f"drive_delivery: share warning: {e}")
    meta = service.files().get(fileId=file_id, fields="webViewLink,id").execute()
    link = meta.get("webViewLink") or f"https://drive.google.com/drive/folders/{file_id}"
    return link


def _read_meta(piece_dir: str) -> Dict[str, Any]:
    path = os.path.join(piece_dir, "meta.json")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_meta(piece_dir: str, meta: Dict[str, Any]) -> None:
    path = os.path.join(piece_dir, "meta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def list_folder_files(service, parent_id: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{parent_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        out.extend(resp.get("files") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def trash_files_not_in_set(service, parent_id: str, keep_names: set[str]) -> int:
    """Remove stale delivery files (e.g. old 4:5-only stubs) after a re-package."""
    trashed = 0
    keep = {n.lower() for n in keep_names}
    for f in list_folder_files(service, parent_id):
        name = f.get("name") or ""
        if name.lower() in keep:
            continue
        try:
            service.files().update(fileId=f["id"], body={"trashed": True}).execute()
            trashed += 1
        except Exception as e:
            print(f"drive_delivery: trash warning for {name}: {e}")
    return trashed


def collect_customer_files(piece_dir: str) -> List[Tuple[str, str]]:
    """
    Return list of (local_path, upload_name) for the customer delivery folder.
    Single: multi-ratio prints/* (+ master.png bonus)
    Bundle: multi-ratio prints from each bundle_sources member (+ optional masters)
    """
    meta = _read_meta(piece_dir)
    product_type = (meta.get("product_type") or "").lower()
    out: List[Tuple[str, str]] = []
    seen = set()

    def add(path: str, name: Optional[str] = None) -> None:
        if not path or not os.path.isfile(path):
            return
        fname = name or os.path.basename(path)
        key = fname.lower()
        if key in seen:
            return
        seen.add(key)
        out.append((path, fname))

    if product_type == "pd_bundle":
        # Public-domain packs: native high-res files from bundle/ only
        bundle_dir = meta.get("bundle_dir") or os.path.join(piece_dir, "bundle")
        if os.path.isdir(bundle_dir):
            for name in sorted(os.listdir(bundle_dir)):
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff")):
                    add(os.path.join(bundle_dir, name))
    elif product_type == "bundle":
        sources = meta.get("bundle_sources") or []
        for i, src in enumerate(sources, 1):
            src = (src or "").replace("/", os.sep)
            if not os.path.isdir(src):
                continue
            prints = os.path.join(src, "prints")
            try:
                from print_exports import iter_print_files

                for full, upload_name in iter_print_files(prints):
                    add(full, f"{i:02d}_{upload_name}")
            except Exception:
                if os.path.isdir(prints):
                    for name in sorted(os.listdir(prints)):
                        if name.lower().endswith((".jpg", ".jpeg", ".png")):
                            add(os.path.join(prints, name), f"{i:02d}_{name}")
            for cand in ("master.png", "master.jpg", "master.jpeg"):
                add(os.path.join(src, cand), f"{i:02d}_{os.path.basename(src)}_{cand}")
        if not any(n.lower().endswith((".jpg", ".jpeg")) for _, n in out):
            bundle_dir = meta.get("bundle_dir") or os.path.join(piece_dir, "bundle")
            if os.path.isdir(bundle_dir):
                for name in sorted(os.listdir(bundle_dir)):
                    if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        add(os.path.join(bundle_dir, name))
    else:
        prints = os.path.join(piece_dir, "prints")
        try:
            from print_exports import iter_print_files

            for full, upload_name in iter_print_files(prints):
                add(full, upload_name)
        except Exception:
            if os.path.isdir(prints):
                for name in sorted(os.listdir(prints)):
                    if name.lower().endswith((".jpg", ".jpeg", ".png")):
                        add(os.path.join(prints, name))
        for cand in ("master.png", "master.jpg", "master.jpeg"):
            add(os.path.join(piece_dir, cand))

    return out


def collect_mockup_files(piece_dir: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(piece_dir)):
        low = name.lower()
        if low.startswith("mockup_") and low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            out.append((os.path.join(piece_dir, name), name))
    return out


def package_piece_to_drive(
    piece_dir: str,
    *,
    root_folder_id: Optional[str] = None,
    compile_pdf: bool = True,
    pdf_script: Optional[str] = None,
    python_exe: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload customer files + private mockups, share customer folder, optionally compile PDF.
    """
    piece_dir = os.path.abspath(piece_dir)
    if not os.path.isdir(piece_dir):
        raise ValueError("Invalid piece_dir")

    # Rebuild incomplete / single-ratio packs (including each member of a set)
    try:
        from print_exports import ensure_customer_prints

        ensure_customer_prints(piece_dir, force=False)
    except Exception as e:
        print(f"drive_delivery: print export warning: {e}")

    meta = _read_meta(piece_dir)
    title = meta.get("title") or meta.get("slug") or os.path.basename(piece_dir)
    listing_slug = _slug(meta.get("slug") or title)

    cfg = load_client_config()
    root_id = root_folder_id or meta.get("drive_root_folder_id") or cfg.get("root_folder_id") or DEFAULT_ROOT_FOLDER_ID

    service = get_service()
    layout = ensure_layout(service, root_id)

    customer_listing_id = ensure_folder(service, layout["customer_id"], listing_slug)
    mockups_listing_id = ensure_folder(service, layout["mockups_id"], listing_slug)

    customer_files = collect_customer_files(piece_dir)
    if not customer_files:
        raise RuntimeError(
            "No customer delivery files found. Need prints/*.jpg (single) or "
            "multi-ratio prints under each bundle_sources piece (set)."
        )

    uploaded_customer = []
    for local_path, name in customer_files:
        fid = upload_file(service, local_path, customer_listing_id, name)
        uploaded_customer.append({"name": name, "id": fid})

    # Drop leftover stub names (old 8x10/16x20-only packs) so Drive matches the new pack
    keep = {u["name"] for u in uploaded_customer}
    if compile_pdf:
        keep.add("Download_Links.pdf")
    trashed = trash_files_not_in_set(service, customer_listing_id, keep)

    uploaded_mockups = []
    for local_path, name in collect_mockup_files(piece_dir):
        fid = upload_file(service, local_path, mockups_listing_id, name)
        uploaded_mockups.append({"name": name, "id": fid})

    drive_link = share_anyone_with_link(service, customer_listing_id)

    meta["drive_link"] = drive_link
    meta["drive_customer_folder_id"] = customer_listing_id
    meta["drive_mockups_folder_id"] = mockups_listing_id
    meta["drive_root_folder_id"] = root_id
    meta["drive_packaged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta["drive_customer_files"] = [u["name"] for u in uploaded_customer]
    meta["drive_mockup_files"] = [u["name"] for u in uploaded_mockups]
    _write_meta(piece_dir, meta)

    pdf_path = None
    pdf_error = None
    if compile_pdf:
        script = pdf_script or os.path.join(
            os.path.dirname(HERE), "mockups", "generate_pdf_links.py"
        )
        exe = python_exe or os.environ.get("PYTHON_EXE") or "python"
        if os.path.isfile(script):
            import subprocess

            proc = subprocess.run(
                [exe, script, piece_dir, drive_link],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == 0:
                for f in os.listdir(piece_dir):
                    if f.lower().startswith("download_links") and f.lower().endswith(".pdf"):
                        pdf_path = os.path.join(piece_dir, f)
                        break
                if pdf_path:
                    meta = _read_meta(piece_dir)
                    meta["pdf_path"] = pdf_path.replace("\\", "/")
                    meta["drive_link"] = drive_link
                    meta["pdf_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _write_meta(piece_dir, meta)
                    try:
                        pdf_id = upload_file(
                            service, pdf_path, customer_listing_id, "Download_Links.pdf"
                        )
                        uploaded_customer.append({"name": "Download_Links.pdf", "id": pdf_id})
                        meta = _read_meta(piece_dir)
                        meta["drive_customer_files"] = [u["name"] for u in uploaded_customer]
                        _write_meta(piece_dir, meta)
                    except Exception as e:
                        print(f"drive_delivery: PDF upload warning: {e}")
            else:
                pdf_error = (proc.stderr or proc.stdout or "PDF failed")[-500:]
        else:
            pdf_error = f"PDF script missing: {script}"

    return {
        "success": True,
        "drive_link": drive_link,
        "customer_folder_id": customer_listing_id,
        "mockups_folder_id": mockups_listing_id,
        "customer_files": uploaded_customer,
        "mockup_files": uploaded_mockups,
        "pdf_path": (pdf_path or "").replace("\\", "/") if pdf_path else None,
        "pdf_error": pdf_error,
        "listing_slug": listing_slug,
        "title": title,
        "sizes": (_read_meta(piece_dir) or {}).get("sizes"),
        "trashed_stale_files": trashed,
    }
