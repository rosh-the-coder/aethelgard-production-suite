import os
import sys
import json
import subprocess
import urllib.parse
import re
import requests
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Root of artwork orchestrator
ROOT_DIR = os.path.abspath(os.path.join(HERE, "..", ".."))
RUNS_DIR = os.path.join(ROOT_DIR, "tooling", "digital-product-research", "artwork-runs")
MOCKUPS_SCRIPT = os.path.join(ROOT_DIR, "tooling", "mockups", "generate_mockups.py")
DETECT_FRAMES_SCRIPT = os.path.join(ROOT_DIR, "tooling", "mockups", "detect_frames.py")
MOCKUPS_DIR = os.path.join(ROOT_DIR, "tooling", "mockups")
PDF_SCRIPT = os.path.join(ROOT_DIR, "tooling", "mockups", "generate_pdf_links.py")
UPLOAD_SCRIPT = os.path.join(HERE, "upload_to_etsy.py")
PYTHON_EXE = os.path.join(ROOT_DIR, "tooling", "ad-creatives", ".venv", "Scripts", "python.exe")
AUTH_STATE_PATH = os.path.join(HERE, "auth_state.json")
ENV_FILE_PATH = os.path.expanduser("~/.config/ai-images/env")
JOBS_DIR = os.path.join(HERE, ".jobs")
SUITE_SETTINGS_PATH = os.path.join(HERE, "suite_settings.json")
MOCKUP_JOBS = {}
MOCKUP_JOBS_LOCK = threading.Lock()
LATEST_SHOP_CAPTURE = None
LATEST_SHOP_CAPTURE_LOCK = threading.Lock()
LATEST_LISTING_CAPTURE = None
LATEST_LISTING_CAPTURE_LOCK = threading.Lock()
SHOP_WATERMARK_TEXT = "Aethelgard Art Co."

DEFAULT_SUITE_SETTINGS = {
    "prices": {
        "single": 2.99,
        "graphic_poster": 2.99,
        "pd_bundle": 7.99,
        "bundle": 12.99,
    },
    "default_quantity": 999,
    "thank_you_note": "",
    "batch": {
        "concurrency": 1,
        "dry_run_default": True,
    },
    "email": {
        "enabled": False,
        "host": "",
        "port": 587,
        "username": "",
        "sender": "",
        "recipient": "",
        "tls_mode": "starttls",
    },
    "drive": {
        "root_folder_id": "1owjKwkil2H-7jli52jbkIhexxXclhkQk",
        "auto_package_on_batch": False,
    },
}


def load_suite_settings():
    settings = json.loads(json.dumps(DEFAULT_SUITE_SETTINGS))
    if os.path.isfile(SUITE_SETTINGS_PATH):
        try:
            with open(SUITE_SETTINGS_PATH, "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk.get("prices"), dict):
                settings["prices"].update({k: float(v) for k, v in disk["prices"].items() if v is not None})
            if disk.get("default_quantity") is not None:
                settings["default_quantity"] = int(disk["default_quantity"])
            if disk.get("thank_you_note") is not None:
                settings["thank_you_note"] = str(disk["thank_you_note"])
            if isinstance(disk.get("batch"), dict):
                settings["batch"].update(disk["batch"])
            if isinstance(disk.get("email"), dict):
                # never persist password fields from disk even if present
                email = {k: v for k, v in disk["email"].items() if "password" not in str(k).lower()}
                settings["email"].update(email)
            if isinstance(disk.get("drive"), dict):
                settings["drive"].update({k: v for k, v in disk["drive"].items() if v is not None})
        except Exception as e:
            print(f"Warning: could not read suite_settings.json: {e}")
    return settings


def save_suite_settings(data):
    current = load_suite_settings()
    prices = data.get("prices") or {}
    for key in ("single", "graphic_poster", "pd_bundle", "bundle"):
        if key in prices and prices[key] is not None:
            current["prices"][key] = float(prices[key])
    if data.get("default_quantity") is not None:
        current["default_quantity"] = int(data["default_quantity"])
    if "thank_you_note" in data:
        current["thank_you_note"] = str(data.get("thank_you_note") or "")
    if isinstance(data.get("batch"), dict):
        batch = data["batch"]
        if batch.get("concurrency") is not None:
            current["batch"]["concurrency"] = max(1, min(4, int(batch["concurrency"])))
        if "dry_run_default" in batch:
            current["batch"]["dry_run_default"] = bool(batch["dry_run_default"])
    if isinstance(data.get("email"), dict):
        email = data["email"]
        for key in ("enabled", "host", "username", "sender", "recipient", "tls_mode"):
            if key in email:
                current["email"][key] = email[key] if key != "enabled" else bool(email[key])
        if email.get("port") is not None:
            current["email"]["port"] = int(email["port"])
    if isinstance(data.get("drive"), dict):
        drive = data["drive"]
        if drive.get("root_folder_id") is not None:
            current["drive"]["root_folder_id"] = str(drive["root_folder_id"]).strip()
        if "auto_package_on_batch" in drive:
            current["drive"]["auto_package_on_batch"] = bool(drive["auto_package_on_batch"])
    with open(SUITE_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return current


def price_for_product_type(product_type=None, product_kind=None):
    settings = load_suite_settings()
    prices = settings.get("prices") or {}
    kind = (product_kind or product_type or "single") or "single"
    kind = str(kind).lower()
    if kind in ("pd_bundle",):
        key = "pd_bundle"
    elif kind in ("bundle",):
        key = "bundle"
    elif kind in ("graphic_poster",):
        key = "graphic_poster"
    else:
        key = "single"
    try:
        return f"{float(prices.get(key, prices.get('single', 2.99))):.2f}"
    except (TypeError, ValueError):
        return "2.99"


def ensure_piece_master_watermark(piece_dir, force=False):
    """Build master_wm.jpg for catalog / listing preview. Returns rel path from ROOT_DIR or None."""
    try:
        from shop_watermark import ensure_master_watermarked
        abs_path = ensure_master_watermarked(
            piece_dir, text=SHOP_WATERMARK_TEXT, opacity=0.18, force=force,
        )
        if not abs_path or not os.path.isfile(abs_path):
            return None
        return os.path.relpath(abs_path, ROOT_DIR).replace("\\", "/")
    except Exception as e:
        print(f"ensure_piece_master_watermark: {e}")
        return None


def playwright_env():
    env = os.environ.copy()
    browsers = os.path.join(ROOT_DIR, "tooling", "ad-creatives", ".playwright-browsers")
    # Always force suite browsers — do not inherit a broken/empty system cache.
    env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def clean_win_text(value):
    """Remove chars that break Windows cp1252 consoles / legacy file writes."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace("\ufffd", "").replace("\x00", "")


def safe_console_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        print(text.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def load_env_keys_into_os():
    """Load ~/.config/ai-images/env into os.environ (values never returned)."""
    if not os.path.isfile(ENV_FILE_PATH):
        return
    try:
        raw = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with open(ENV_FILE_PATH, "r", encoding=enc) as f:
                    raw = f.read()
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            with open(ENV_FILE_PATH, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k:
                os.environ[k] = v
        # google-genai prefers GOOGLE_API_KEY; keep GEMINI Studio key authoritative.
        google = (os.environ.get("GOOGLE_API_KEY") or "").strip()
        gemini = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not google:
            os.environ.pop("GOOGLE_API_KEY", None)
        if gemini:
            os.environ["GEMINI_API_KEY"] = gemini
            if not google or google != gemini:
                os.environ["GOOGLE_API_KEY"] = gemini
    except Exception as e:
        print(f"Warning: could not read env file: {e}")


def env_key_present(name):
    load_env_keys_into_os()
    val = (os.environ.get(name) or "").strip()
    return bool(val)


def stderr_tail(text, max_chars=600):
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return "…" + text[-max_chars:]


def upload_status_path(piece_dir):
    return os.path.join(piece_dir, "upload_status.json")


def write_upload_status(piece_dir, status, message="", draft_url=None, extra=None):
    payload = {
        "status": status,
        "message": message,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "piece_dir": piece_dir.replace("\\", "/"),
    }
    if draft_url:
        payload["draft_url"] = draft_url
    if extra:
        payload.update(extra)
    try:
        with open(upload_status_path(piece_dir), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write upload_status.json: {e}")
    return payload


def read_upload_status(piece_dir):
    path = upload_status_path(piece_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def persist_mockup_job(job_id, data):
    try:
        os.makedirs(JOBS_DIR, exist_ok=True)
        path = os.path.join(JOBS_DIR, f"{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: could not persist mockup job: {e}")


def load_mockup_job(job_id):
    path = os.path.join(JOBS_DIR, f"{job_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def resolve_upscaler_path():
    env_path = os.environ.get("ARTWORK_UPSCALER")
    if env_path and os.path.isfile(env_path):
        return env_path
    candidates = [
        os.path.join(ROOT_DIR, "tooling", "upscale", "realesrgan-ncnn-vulkan.exe"),
        os.path.join(ROOT_DIR, "tooling", "upscale", "realesrgan-ncnn-vulkan"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def build_preflight():
    load_env_keys_into_os()
    browsers = os.path.join(ROOT_DIR, "tooling", "ad-creatives", ".playwright-browsers")
    upscaler = resolve_upscaler_path()
    gemini_ok = env_key_present("GEMINI_API_KEY")
    cf_key = env_key_present("CLOUDFLARE_WORKER_KEY")
    cf_url = bool((os.environ.get("CLOUDFLARE_WORKER_URL") or "").strip())
    cloudflare_ok = cf_key and cf_url
    return {
        "env_file_present": os.path.isfile(ENV_FILE_PATH),
        "env_file_path": ENV_FILE_PATH,
        "gemini_key_set": gemini_ok,
        "openrouter_key_set": env_key_present("OPENROUTER_API_KEY"),
        "openai_key_set": env_key_present("OPENAI_API_KEY"),
        "groq_key_set": env_key_present("GROQ_API_KEY"),
        "cloudflare_worker_key_set": cf_key,
        "cloudflare_worker_url_set": cf_url,
        "cloudflare_ready": cloudflare_ok,
        "upscaler_present": bool(upscaler),
        "upscaler_path": upscaler,
        "playwright_browsers_present": os.path.isdir(browsers),
        "playwright_browsers_path": browsers,
        "auth_state_present": os.path.isfile(AUTH_STATE_PATH),
        "python_exe_present": os.path.isfile(PYTHON_EXE),
        "can_generate": (gemini_ok or cloudflare_ok) and os.path.isfile(PYTHON_EXE),
    }


def run_python_subprocess(cmd):
    try:
        safe_console_print(f"Running command: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=playwright_env())
        if res.stdout:
            safe_console_print(res.stdout)
        if res.stderr:
            safe_console_print(res.stderr)
        return res.returncode == 0, res.stdout or "", res.stderr or ""
    except Exception as e:
        safe_console_print(f"Error running subprocess: {e}")
        return False, "", str(e)


def parse_mockup_stdout(stdout, piece_dir, success):
    generated = 0
    warnings = []
    if "__MOCKUP_RESULT__" in stdout:
        try:
            payload = json.loads(stdout.split("__MOCKUP_RESULT__", 1)[1].strip().splitlines()[0])
            generated = payload.get("generated", 0)
            warnings = payload.get("warnings", [])
            success = payload.get("success", success)
        except Exception:
            pass
    if generated == 0 and success and os.path.isdir(piece_dir):
        generated = len([
            f for f in os.listdir(piece_dir)
            if f.lower().startswith("mockup_") and f.lower().endswith(".jpg")
        ])
    return generated, warnings, success


def start_mockup_job(piece_dir, only_templates=None, overview_only=False):
    job_id = uuid.uuid4().hex[:10]
    initial = {
        "status": "running",
        "piece_dir": piece_dir,
        "started_at": time.time(),
        "only_templates": list(only_templates or []),
        "overview_only": bool(overview_only),
    }
    with MOCKUP_JOBS_LOCK:
        MOCKUP_JOBS[job_id] = initial
        if len(MOCKUP_JOBS) > 30:
            oldest = sorted(MOCKUP_JOBS.items(), key=lambda kv: kv[1].get("started_at", 0))[:10]
            for old_id, _ in oldest:
                MOCKUP_JOBS.pop(old_id, None)
    persist_mockup_job(job_id, initial)

    def worker():
        cmd = [PYTHON_EXE, MOCKUPS_SCRIPT, piece_dir]
        if overview_only:
            cmd += ["--overview-only"]
        elif only_templates:
            cmd += ["--only", ",".join(only_templates)]
        stdout_lines = []
        try:
            print(f"Running command: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=playwright_env(),
            )
            for line in proc.stdout:
                print(line, end="" if line.endswith("\n") else "\n")
                stdout_lines.append(line)
                if "__MOCKUP_PROGRESS__" in line:
                    try:
                        payload = json.loads(line.split("__MOCKUP_PROGRESS__", 1)[1].strip())
                        with MOCKUP_JOBS_LOCK:
                            if job_id in MOCKUP_JOBS:
                                MOCKUP_JOBS[job_id]["progress"] = payload
                                persist_mockup_job(job_id, MOCKUP_JOBS[job_id])
                    except Exception:
                        pass
            proc.wait()
            success = proc.returncode == 0
        except Exception as e:
            print(f"Error running subprocess: {e}")
            success = False
        stdout = "".join(stdout_lines)
        generated, warnings, success = parse_mockup_stdout(stdout, piece_dir, success)
        done = {
            "status": "done" if success else "error",
            "success": success,
            "generated": generated,
            "warnings": warnings,
            "piece_dir": piece_dir,
            "finished_at": time.time(),
            "overview_only": bool(overview_only),
        }
        with MOCKUP_JOBS_LOCK:
            MOCKUP_JOBS[job_id] = done
        persist_mockup_job(job_id, done)

    threading.Thread(target=worker, daemon=True).start()
    return job_id

class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve files from root directory so we can access images in runs/templates
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def api_path(self):
        return urllib.parse.urlparse(self.path).path

    def end_headers(self):
        # CORS + Chrome Private Network Access (HTTPS Etsy → localhost)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        path = self.api_path()

        # Factory OS APIs (dashboard aggregate, SSE, batches, templates, quota)
        if path.startswith("/api/") or path.startswith("/api"):
            try:
                from factory import factory_routes
                research_count = None
                try:
                    from research_library import list_items
                    research_count = len(list_items() or [])
                except Exception:
                    research_count = None
                if factory_routes.handle_get(
                    self,
                    path,
                    scan_runs=self.scan_runs,
                    build_preflight=build_preflight,
                    load_suite_settings=load_suite_settings,
                    research_count=research_count,
                ):
                    return
            except Exception as e:
                if path in ("/api/dashboard", "/api/events", "/api/quota", "/api/batches") or path.startswith(
                    "/api/templates/"
                ) or path.startswith("/api/batches/"):
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                    return

            if path.startswith("/api/archive"):
                try:
                    from archive import routes as archive_routes
                    if archive_routes.handle_get(self, path):
                        return
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                    return

        if path == "/factory_ui.js":
            asset = os.path.join(HERE, "factory_ui.js")
            if os.path.isfile(asset):
                self.send_response(200)
                self.send_header("Content-type", "application/javascript; charset=utf-8")
                self.end_headers()
                with open(asset, "rb") as f:
                    self.wfile.write(f.read())
                return

        if path == "/archive_studio.css":
            asset = os.path.join(HERE, "archive_studio.css")
            if os.path.isfile(asset):
                self.send_response(200)
                self.send_header("Content-type", "text/css; charset=utf-8")
                self.end_headers()
                with open(asset, "rb") as f:
                    self.wfile.write(f.read())
                return
        if path == "/archive_studio.js":
            asset = os.path.join(HERE, "archive_studio.js")
            if os.path.isfile(asset):
                self.send_response(200)
                self.send_header("Content-type", "application/javascript; charset=utf-8")
                self.end_headers()
                with open(asset, "rb") as f:
                    self.wfile.write(f.read())
                return

        # Route dashboard home
        if path == "/" or path == "/index.html":
            dashboard_path = os.path.join(HERE, "dashboard.html")
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            with open(dashboard_path, "rb") as f:
                self.wfile.write(f.read())
            return

        # Factory dashboard static assets
        if path == "/factory_dashboard.css":
            asset = os.path.join(HERE, "factory_dashboard.css")
            if os.path.isfile(asset):
                self.send_response(200)
                self.send_header("Content-type", "text/css; charset=utf-8")
                self.end_headers()
                with open(asset, "rb") as f:
                    self.wfile.write(f.read())
                return
        if path == "/factory_dashboard.js":
            asset = os.path.join(HERE, "factory_dashboard.js")
            if os.path.isfile(asset):
                self.send_response(200)
                self.send_header("Content-type", "application/javascript; charset=utf-8")
                self.end_headers()
                with open(asset, "rb") as f:
                    self.wfile.write(f.read())
                return
            
        # Mockup helper tool route
        if path == "/mockup_helper" or path == "/mockup_helper.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            helper_path = os.path.join(ROOT_DIR, "tooling", "mockups", "mockup_helper.html")
            with open(helper_path, "rb") as f:
                self.wfile.write(f.read())
            return

        # API: Etsy auth session status
        if path == "/api/auth_status":
            auth_path = AUTH_STATE_PATH
            exists = os.path.isfile(auth_path)
            api_info = {}
            try:
                from etsy_api import api_status
                api_info = api_status()
            except Exception as e:
                api_info = {"error": str(e)}
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "authenticated": exists,
                "auth_file": auth_path if exists else None,
                "etsy_api": api_info,
            }).encode('utf-8'))
            return

        # API: Etsy Open API connection status
        if path == "/api/etsy/api_status":
            try:
                from etsy_api import api_status
                payload = api_status()
                self.send_response(200)
            except Exception as e:
                payload = {"error": str(e)}
                self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # API: OAuth callback from Etsy (browser redirect)
        if path == "/api/etsy/oauth/callback":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            err = (qs.get("error") or [None])[0]
            html_ok = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;background:#111;color:#eee">
            <h1>Etsy API connected</h1><p>You can close this tab and return to the Production Suite.</p>
            <script>setTimeout(()=>window.close(), 1500)</script></body></html>"""
            html_bad = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;background:#111;color:#f88">
            <h1>Etsy API connect failed</h1><p>{}</p></body></html>"""
            if err or not code or not state:
                self.send_response(400)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bad.format(err or "Missing code/state").encode("utf-8"))
                return
            try:
                from etsy_api import finish_oauth
                finish_oauth(code, state)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_ok.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bad.format(str(e)).encode("utf-8"))
            return

        # API: Google Drive OAuth callback
        if path == "/api/drive/oauth/callback":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            err = (qs.get("error") or [None])[0]
            html_ok = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;background:#111;color:#eee">
            <h1>Google Drive connected</h1><p>You can close this tab and return to the Production Suite.</p>
            <script>setTimeout(()=>window.close(), 1500)</script></body></html>"""
            html_bad = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;background:#111;color:#f88">
            <h1>Google Drive connect failed</h1><p>{}</p></body></html>"""
            if err or not code:
                self.send_response(400)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bad.format(err or "Missing code").encode("utf-8"))
                return
            try:
                import drive_delivery
                drive_delivery.finish_oauth(code, state or "")
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_ok.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_bad.format(str(e)).encode("utf-8"))
            return

        if path == "/api/drive/status":
            try:
                import drive_delivery
                payload = {"success": True, **drive_delivery.status()}
                settings = load_suite_settings()
                payload["root_folder_id"] = (settings.get("drive") or {}).get(
                    "root_folder_id"
                ) or payload.get("root_folder_id")
                self.send_response(200)
            except Exception as e:
                payload = {"success": False, "error": str(e)}
                self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        # API: Operator preflight (booleans only — never returns key material)
        if path == "/api/preflight":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(build_preflight()).encode("utf-8"))
            return

        # API: Poll upload status for a piece
        if path.startswith("/api/upload_status"):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            piece_dir = params.get("piece_dir", [""])[0]
            if not piece_dir or not os.path.isdir(piece_dir):
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid piece_dir"}).encode("utf-8"))
                return
            status = read_upload_status(piece_dir) or {
                "status": "idle",
                "message": "No upload started for this piece.",
                "piece_dir": piece_dir.replace("\\", "/"),
            }
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode("utf-8"))
            return

        # API: Get all runs
        if path == "/api/runs":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            runs = self.scan_runs()
            self.wfile.write(json.dumps(runs).encode('utf-8'))
            return

        # API: Poll async mockup regeneration job
        if path.startswith("/api/mockup_job"):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            job_id = params.get("job_id", [""])[0]
            with MOCKUP_JOBS_LOCK:
                job = MOCKUP_JOBS.get(job_id)
            if not job:
                job = load_mockup_job(job_id)
                if job:
                    with MOCKUP_JOBS_LOCK:
                        MOCKUP_JOBS[job_id] = job
            if not job:
                self.send_response(404)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Job not found"}).encode("utf-8"))
                return
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(job).encode("utf-8"))
            return

        # API: Images available for gallery-wall assignment
        if path.startswith("/api/bundle_images"):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            piece_dir = params.get("piece_dir", [""])[0]
            if not piece_dir or not os.path.isdir(piece_dir):
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid piece_dir"}).encode("utf-8"))
                return
            sys.path.insert(0, MOCKUPS_DIR)
            import generate_mockups as gm
            images = gm.list_bundle_images(piece_dir)
            out = []
            for img in images:
                rel = os.path.relpath(img["path"], ROOT_DIR).replace("\\", "/")
                out.append({**img, "rel": rel})
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"images": out}).encode("utf-8"))
            return

        # API: Load saved gallery placements for a template
        if path.startswith("/api/mockup_placements"):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            piece_dir = params.get("piece_dir", [""])[0]
            template_name = params.get("template", [""])[0]
            if not piece_dir or not os.path.isdir(piece_dir):
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid piece_dir"}).encode("utf-8"))
                return
            placements = self.load_mockup_placements(piece_dir, template_name)
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(placements).encode("utf-8"))
            return

        # API: Get niche presets
        if path == "/api/niche_presets":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            presets_path = os.path.join(HERE, "niche_presets.json")
            if os.path.exists(presets_path):
                with open(presets_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(json.dumps({}).encode('utf-8'))
            return

        if path == "/api/suite_settings":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "settings": load_suite_settings()}).encode("utf-8"))
            return

        # API: Mockup template registry (for Mockup Studio library tab)
        if path == "/api/mockup_templates":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            templates_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
            templates = []
            if os.path.exists(templates_path):
                with open(templates_path, "r", encoding="utf-8") as f:
                    templates = json.load(f)
            out = []
            for t in templates:
                calibrated = not t.get("needs_calibration") and (
                    t.get("calibrated") or t.get("quad") or t.get("quads")
                )
                out.append({
                    "name": t.get("name"),
                    "image": t.get("image"),
                    "orientation": t.get("orientation"),
                    "aspect": t.get("aspect"),
                    "tags": t.get("tags", []),
                    "calibrated": bool(calibrated),
                    "needs_calibration": bool(t.get("needs_calibration")),
                    "multi": len(t.get("quads", [])) or (1 if t.get("quad") else 0),
                    "quad": t.get("quad"),
                    "quads": t.get("quads"),
                    "box": t.get("box"),
                })
            self.wfile.write(json.dumps(out).encode("utf-8"))
            return

        # API: Typography editor font catalog
        if path == "/api/poster_fonts":
            try:
                from poster_compose import list_editor_fonts
                fonts = list_editor_fonts()
            except Exception:
                fonts = [{"family": "Arial", "style": "sans", "google": None}]
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"fonts": fonts}).encode("utf-8"))
            return

        # API: Saved research library (must be before /api/research — that prefix would steal this path)
        if path == "/api/research_library":
            from research_library import list_items
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            category = (qs.get("category") or ["all"])[0]
            kind = (qs.get("kind") or ["all"])[0]
            q = (qs.get("q") or [""])[0]
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(list_items(category=category, kind=kind, q=q), ensure_ascii=False).encode("utf-8"))
            return

        # API: Etsy Keyword Research
        if path == "/api/research":
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            query = params.get("q", [""])[0]
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            if not query:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return
                
            research_script = os.path.join(HERE, "etsy_research.py")
            cmd = [PYTHON_EXE, "-u", research_script, query]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=playwright_env())
                stdout = res.stdout or ""
                if res.returncode != 0:
                    print(f"Keyword research stderr: {(res.stderr or '')[:800]}")
                payload = self.extract_marker_json(stdout, "RESEARCH_RESULTS_JSON:")
                if payload is not None:
                    self.wfile.write(json.dumps(payload).encode('utf-8'))
                else:
                    print(f"Keyword research missing JSON marker. stdout tail: {stdout[-400:]}")
                    self.wfile.write(json.dumps({"error": "Failed to parse research results"}).encode('utf-8'))
            except Exception as e:
                print(f"Error running keyword research API: {e}")
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # API: Etsy Shop Analysis
        if path == "/api/analyze_shop" or self.path.startswith("/api/analyze_shop?"):
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)
            shop_name = params.get("name", [""])[0].strip()
            
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            if not shop_name:
                self.wfile.write(json.dumps({"error": "Shop name required"}).encode('utf-8'))
                return
                
            analyzer_script = os.path.join(HERE, "shop_analyzer.py")
            cmd = [PYTHON_EXE, analyzer_script, shop_name]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=playwright_env())
                stdout = res.stdout or ""
                if res.returncode != 0:
                    print(f"Shop analyzer stderr: {(res.stderr or '')[:800]}")
                payload = self.extract_marker_json(stdout, "SHOP_ANALYSIS_JSON:")
                if payload is not None:
                    self.wfile.write(json.dumps(payload).encode('utf-8'))
                else:
                    print(f"Shop analyzer missing JSON marker. stdout tail: {stdout[-400:]}")
                    self.wfile.write(json.dumps({"error": "Failed to parse analysis results"}).encode('utf-8'))
            except Exception as e:
                print(f"Error running shop analysis API: {e}")
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # API: Latest browser-captured shop snapshot
        if path == "/api/latest_shop_capture":
            with LATEST_SHOP_CAPTURE_LOCK:
                payload = LATEST_SHOP_CAPTURE
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload or {"waiting": True}).encode("utf-8"))
            return

        # API: Latest listing capture
        if path == "/api/latest_listing_capture":
            with LATEST_LISTING_CAPTURE_LOCK:
                payload = LATEST_LISTING_CAPTURE
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload or {"waiting": True}).encode("utf-8"))
            return

        # API: Public-domain image proxy (loc.gov is Cloudflare-blocked in-browser)
        if path == "/api/public_domain/image":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                from public_domain import resolve_pd_image_bytes
                data, mime = resolve_pd_image_bytes(
                    (qs.get("set") or [""])[0],
                    (qs.get("file") or [""])[0],
                    (qs.get("u") or [""])[0],
                )
                if not data:
                    self.send_response(404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Image not available"}).encode("utf-8"))
                    return
                self.send_response(200)
                self.send_header("Content-type", mime or "image/jpeg")
                self.send_header("Cache-Control", "public, max-age=120")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        # API: Public-domain Met search
        if path == "/api/public_domain/search":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get("q") or [""])[0]
            limit = (qs.get("limit") or ["48"])[0]
            offset = (qs.get("offset") or ["0"])[0]
            try:
                import importlib
                import public_domain as _pd_mod
                importlib.reload(_pd_mod)
                from public_domain import search_met
                results, meta = search_met(q, limit=limit, offset=offset, return_meta=True)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "results": results,
                    "count": len(results),
                    "source": "met_open_access",
                    "queries_tried": meta.get("queries_tried") or [],
                    "expanded": bool(meta.get("expanded")),
                    "offset": meta.get("offset", 0),
                    "has_more": bool(meta.get("has_more")),
                    "total_ranked": meta.get("total_ranked", len(results)),
                    "note": meta.get("note") or "Met, Library of Congress, and Wikimedia — verify before commercial use.",
                }).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e), "results": []}).encode("utf-8"))
            return

        # Bookmarklet installer pages
        if path == "/capture_helper":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            helper_path = os.path.join(HERE, "capture_helper.html")
            with open(helper_path, "rb") as f:
                self.wfile.write(f.read())
            return

        if path == "/listing_capture_helper":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            helper_path = os.path.join(HERE, "listing_capture_helper.html")
            with open(helper_path, "rb") as f:
                self.wfile.write(f.read())
            return
            
        return super().do_GET()

    def do_POST(self):
        try:
            global LATEST_SHOP_CAPTURE, LATEST_LISTING_CAPTURE
            path = self.api_path()
            content_length = int(self.headers.get("Content-Length") or 0)
            post_data = self.rfile.read(content_length)
            content_type = (self.headers.get("Content-Type") or "").lower()

            # Factory OS POST APIs (batches, rebuild, email test, draft resubmit)
            if path.startswith("/api/batches") or path in (
                "/api/jobs/resume-selection",
                "/api/products/rebuild",
                "/api/products/etsy-draft",
                "/api/settings/email/test",
            ):
                try:
                    data = json.loads(post_data.decode("utf-8") or "{}")
                except Exception:
                    data = {}
                try:
                    from factory import factory_routes
                    if factory_routes.handle_post(
                        self,
                        path,
                        data,
                        load_suite_settings=load_suite_settings,
                        save_suite_settings=save_suite_settings,
                    ):
                        return
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                    return

            if path.startswith("/api/archive"):
                try:
                    data = json.loads(post_data.decode("utf-8") or "{}")
                except Exception:
                    data = {}
                try:
                    from archive import routes as archive_routes
                    if archive_routes.handle_post(self, path, data):
                        return
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                    return

            # Form POST from bookmarklet (bypasses Chrome fetch block from HTTPS → localhost)
            if path in ("/api/import_listing_capture_form", "/api/import_shop_capture_form"):
                try:
                    from listing_capture import parse_listing_capture, append_listing_snapshot
                    from shop_capture import parse_page_text

                    form = urllib.parse.parse_qs(post_data.decode("utf-8", errors="replace"))
                    raw = (form.get("payload") or [""])[0]
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {}

                    if path.endswith("listing_capture_form"):
                        result = parse_listing_capture(
                            page_text=payload.get("page_text", ""),
                            listing_url=payload.get("listing_url", ""),
                            stats=payload.get("stats") or {},
                            tags=payload.get("tags"),
                            details=payload.get("details") or {},
                        )
                        append_listing_snapshot(result)
                        with LATEST_LISTING_CAPTURE_LOCK:
                            LATEST_LISTING_CAPTURE = result
                        label = result.get("title") or result.get("listing_id") or "listing"
                    else:
                        result = parse_page_text(
                            payload.get("page_text", ""),
                            shop_url=payload.get("shop_url", ""),
                            shop_name=payload.get("shop_name", ""),
                            listings=payload.get("listings") or [],
                            stats=payload.get("stats") or {},
                        )
                        result["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                        with LATEST_SHOP_CAPTURE_LOCK:
                            LATEST_SHOP_CAPTURE = result
                        label = result.get("shop_name") or "shop"

                    safe_label = (
                        str(label)
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Capture OK</title>
<style>body{{font-family:Georgia,serif;background:#111;color:#eee;padding:40px;}}
a{{color:#c5a880}}</style></head><body>
<h1>Captured</h1>
<p><strong>{safe_label}</strong> was sent to the Production Suite.</p>
<p><a href="/">Open dashboard → Market Research</a></p>
<script>setTimeout(function(){{ location.href='/'; }}, 1200);</script>
</body></html>"""
                    self.send_response(200)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                    return
                except Exception as form_err:
                    print(f"Form capture error: {form_err}")
                    err_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Capture Error</title>
<style>body{{font-family:Georgia,serif;background:#111;color:#eee;padding:40px;}}
a{{color:#c5a880}}</style></head><body>
<h1>Capture failed</h1>
<p>{str(form_err).replace('<','')}</p>
<p><a href="/">Back to dashboard</a> — try the bookmarklet again.</p>
</body></html>"""
                    self.send_response(500)
                    self.send_header("Content-type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(err_html.encode("utf-8"))
                    return

            # Artwork Studio — existing-file upload (multipart; not JSON)
            if path == "/api/studio_upload" or path.startswith("/api/studio_upload/"):
                try:
                    from studio_upload import handle_studio_upload
                    json_data = None
                    if "multipart/form-data" not in content_type:
                        try:
                            json_data = json.loads(post_data.decode("utf-8") or "{}")
                        except Exception:
                            json_data = {}
                    status, payload = handle_studio_upload(
                        content_type=self.headers.get("Content-Type") or "",
                        body=post_data,
                        runs_dir=RUNS_DIR,
                        root_dir=ROOT_DIR,
                        title_fn=lambda concept, spine: self.get_ai_title_suggestions(concept, spine),
                        gemini_key=self.get_gemini_key(),
                        json_data=json_data,
                        path=path,
                    )
                    self.send_response(status)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(payload).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            try:
                data = json.loads(post_data.decode("utf-8") or "{}")
            except json.JSONDecodeError as je:
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": f"Invalid JSON body: {je}"}).encode("utf-8"))
                return
            
            # API: Save metadata edits
            if path == "/api/save":
                piece_dir = data.get("piece_dir")
                title = data.get("title")
                description = data.get("description")
                tags = data.get("tags", [])
                price = data.get("price")
                quantity = data.get("quantity")
                materials = data.get("materials", None)
                
                success = self.save_metadata(piece_dir, title, description, tags, price, quantity, materials=materials)
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return

            if path == "/api/suite_settings":
                try:
                    settings = save_suite_settings(data)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "settings": settings}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            if path == "/api/generate_seo_pack":
                piece_dir = data.get("piece_dir")
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Invalid piece_dir"}).encode("utf-8"))
                    return
                try:
                    from seo_pack import apply_seo_pack_to_piece, generate_seo_pack_for_piece
                    pack = generate_seo_pack_for_piece(piece_dir)
                    apply_seo_pack_to_piece(piece_dir, pack)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "pack": pack}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            if path == "/api/suggest_bundles":
                piece_dirs = data.get("piece_dirs") or []
                try:
                    artworks = []
                    for pdir in piece_dirs:
                        meta_path = os.path.join(pdir, "meta.json")
                        if not os.path.isfile(meta_path):
                            continue
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        artworks.append({
                            "title": meta.get("title") or meta.get("slug") or os.path.basename(pdir),
                            "prompt": meta.get("prompt") or "",
                            "path": pdir,
                        })
                    from seo_pack import suggest_bundle_options
                    options = suggest_bundle_options(artworks)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "options": options}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            if path == "/api/create_library_bundle":
                try:
                    result = self.create_library_bundle(
                        data.get("piece_dirs") or [],
                        title=data.get("title") or "Art Bundle",
                        concept=data.get("concept") or "",
                        auto_seo=bool(data.get("auto_seo", True)),
                    )
                    code = 200 if result.get("success") else 400
                    self.send_response(code)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Generate mockups (async — compositing can take 1–2 min)
            if path == "/api/generate_mockups":
                piece_dir = data.get("piece_dir")
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "Invalid piece directory",
                    }).encode("utf-8"))
                    return

                selected_templates = data.get("templates") or data.get("selected_templates")
                only_templates = data.get("only_templates")
                persist_selection = bool(data.get("persist_selection"))
                if selected_templates is not None and persist_selection:
                    # Persist listing selection (Pick mockup templates flow)
                    templates_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
                    all_names = []
                    if os.path.exists(templates_path):
                        try:
                            with open(templates_path, "r", encoding="utf-8") as f:
                                all_names = [t.get("name") for t in json.load(f) if t.get("name")]
                        except Exception:
                            pass
                    selected_set = set(selected_templates)
                    disabled = [n for n in all_names if n not in selected_set]
                    extra = {}
                    for key in (
                        "repeat_mockups",
                        "generate_overview_grids",
                        "overview_max_sheets",
                        "max_room_mockups",
                    ):
                        if key in data:
                            extra[key] = data[key]
                    self.save_mockup_prefs(
                        piece_dir, disabled, include_zoom_gif=False,
                        selected_templates=list(selected_templates),
                        extra_prefs=extra or None,
                    )
                    only_templates = list(selected_templates)
                elif selected_templates and not only_templates:
                    # Backward compatible: treat templates as this-job-only filter
                    only_templates = list(selected_templates)

                overview_only = bool(data.get("overview_only"))
                if overview_only:
                    only_templates = None
                job_id = start_mockup_job(
                    piece_dir,
                    only_templates=only_templates,
                    overview_only=overview_only,
                )
                templates_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
                calibrated_count = 0
                needs_cal_count = 0
                if os.path.exists(templates_path):
                    try:
                        with open(templates_path, "r", encoding="utf-8") as f:
                            templates = json.load(f)
                        for t in templates:
                            ok = not t.get("needs_calibration") and (
                                t.get("calibrated") or t.get("quad") or t.get("quads")
                            )
                            if ok:
                                calibrated_count += 1
                            else:
                                needs_cal_count += 1
                    except Exception:
                        pass
                self.send_response(202)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "status": "running",
                    "job_id": job_id,
                    "calibrated_count": calibrated_count,
                    "needs_calibration_count": needs_cal_count,
                    "message": (
                        f"{calibrated_count} calibrated template(s) available; "
                        f"{needs_cal_count} skipped until calibrated."
                    ),
                }).encode("utf-8"))
                return

            # API: Save gallery-wall frame placements
            if path == "/api/mockup_placements":
                piece_dir = data.get("piece_dir")
                template_name = data.get("template")
                frames = data.get("frames", [])
                if not piece_dir or not template_name:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Missing fields"}).encode("utf-8"))
                    return
                success = self.save_mockup_placements(piece_dir, template_name, frames)
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode("utf-8"))
                return

            # API: Choose art for a single-frame mockup (and optional listing cover)
            if path == "/api/single_frame_source":
                piece_dir = data.get("piece_dir")
                template_name = data.get("template")
                image_ref = data.get("image")
                set_as_cover = bool(data.get("set_as_cover"))
                refresh = data.get("refresh", True)
                if not piece_dir or not os.path.isdir(piece_dir) or not image_ref:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "Need piece_dir and image",
                    }).encode("utf-8"))
                    return
                success, err = self.save_single_frame_source(
                    piece_dir, template_name, image_ref, set_as_cover=set_as_cover,
                )
                mockup_rel = None
                master_rel = None
                elapsed_ms = 0
                if success and template_name and refresh:
                    t0 = time.time()
                    try:
                        sys.path.insert(0, MOCKUPS_DIR)
                        import generate_mockups as gm
                        import importlib
                        importlib.reload(gm)
                        ok = gm.generate_mockups_for_piece(
                            piece_dir, only_templates=[template_name], fast=True,
                        )
                        if not ok:
                            success = False
                            err = err or "Fast mockup refresh failed"
                        else:
                            out_name = f"mockup_{template_name}.jpg"
                            out_path = os.path.join(piece_dir, out_name)
                            if os.path.isfile(out_path):
                                mockup_rel = os.path.relpath(out_path, ROOT_DIR).replace("\\", "/")
                    except Exception as e:
                        success = False
                        err = str(e)
                    elapsed_ms = int((time.time() - t0) * 1000)
                if success and set_as_cover:
                    master_path = os.path.join(piece_dir, "master.png")
                    if os.path.isfile(master_path):
                        master_rel = os.path.relpath(master_path, ROOT_DIR).replace("\\", "/")
                    master_preview = ensure_piece_master_watermark(piece_dir, force=True)
                else:
                    master_preview = None
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": success,
                    "error": err,
                    "mockup_rel": mockup_rel,
                    "master_rel": master_rel,
                    "master_preview": master_preview,
                    "template": template_name,
                    "elapsed_ms": elapsed_ms,
                }).encode("utf-8"))
                return

            # API: Delete a listing mockup (room or overview)
            if path == "/api/delete_mockup":
                piece_dir = data.get("piece_dir")
                source = data.get("source") or data.get("fname") or data.get("mockup")
                if not piece_dir or not os.path.isdir(piece_dir) or not source:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "Need piece_dir and source mockup filename",
                    }).encode("utf-8"))
                    return
                result = self.delete_mockup(piece_dir, source)
                ok = bool(result.get("success"))
                self.send_response(200 if ok else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
                return

            # API: Duplicate an existing room mockup so you can Change art on the copy
            if path == "/api/duplicate_mockup":
                piece_dir = data.get("piece_dir")
                source = data.get("source") or data.get("fname") or data.get("mockup")
                if not piece_dir or not os.path.isdir(piece_dir) or not source:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "Need piece_dir and source mockup filename",
                    }).encode("utf-8"))
                    return
                result = self.duplicate_mockup(piece_dir, source)
                ok = bool(result.get("success"))
                self.send_response(200 if ok else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
                return

            # API: Generate PDF
            if path == "/api/generate_pdf":
                piece_dir = data.get("piece_dir")
                drive_link = data.get("drive_link")
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Invalid piece_dir"}).encode("utf-8"))
                    return
                if not drive_link or "drive.google.com" not in (drive_link or "").lower():
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "Paste a Google Drive share link (drive.google.com/...)."
                    }).encode("utf-8"))
                    return
                success, stdout, stderr = self.run_subprocess([PYTHON_EXE, PDF_SCRIPT, piece_dir, drive_link])
                pdf_path = None
                if success:
                    for f in os.listdir(piece_dir):
                        if f.lower().endswith(".pdf") and f.lower().startswith("download_links"):
                            pdf_path = os.path.join(piece_dir, f)
                            break
                    if not pdf_path:
                        pdfs = [f for f in os.listdir(piece_dir) if f.lower().endswith(".pdf")]
                        if pdfs:
                            pdf_path = os.path.join(piece_dir, pdfs[0])
                    meta_path = os.path.join(piece_dir, "meta.json")
                    if pdf_path and os.path.isfile(meta_path):
                        try:
                            with open(meta_path, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            meta["pdf_path"] = pdf_path.replace("\\", "/")
                            meta["drive_link"] = drive_link
                            meta["pdf_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(meta, f, indent=2)
                        except Exception as e:
                            print(f"Warning: could not update meta after PDF: {e}")
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": success,
                    "pdf_path": (pdf_path or "").replace("\\", "/") if pdf_path else None,
                    "drive_link": drive_link if success else None,
                    "error": None if success else (stderr_tail(stderr) or stderr_tail(stdout) or "PDF generation failed"),
                }).encode('utf-8'))
                return

            # API: Trigger Etsy Upload (browser automation — fragile / bot-wall prone)
            if path == "/api/upload":
                piece_dir = data.get("piece_dir")
                success = False
                error = None
                if not piece_dir or not os.path.isdir(piece_dir):
                    error = "Invalid piece_dir"
                else:
                    try:
                        if not os.path.isfile(PYTHON_EXE):
                            raise FileNotFoundError(f"Python not found: {PYTHON_EXE}")
                        if not os.path.isfile(UPLOAD_SCRIPT):
                            raise FileNotFoundError(f"Upload script not found: {UPLOAD_SCRIPT}")
                        write_upload_status(piece_dir, "queued", "Upload console launching…")
                        # List argv + new console — never shell-join paths (spaces in "Etsy 2026" break cmd).
                        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                        subprocess.Popen(
                            [PYTHON_EXE, UPLOAD_SCRIPT, "--upload", os.path.abspath(piece_dir)],
                            cwd=HERE,
                            env=playwright_env(),
                            creationflags=creationflags,
                        )
                        success = True
                        print(f"Launched Etsy upload in new console window for: {piece_dir}")
                    except Exception as e:
                        error = str(e)
                        write_upload_status(piece_dir, "failed", f"Could not launch uploader: {e}")
                        print(f"Error launching uploader: {e}")
                    
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": success,
                    "launched": success,
                    "message": "Upload console started — watch status badge; success only after draft saves." if success else error,
                    "error": error,
                }).encode('utf-8'))
                return

            # API: Begin Etsy Open API OAuth (PKCE)
            if path == "/api/etsy/oauth/start":
                try:
                    from etsy_api import begin_oauth
                    payload = begin_oauth()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, **payload}).encode("utf-8"))
                except Exception as e:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Begin Google Drive OAuth
            if path == "/api/drive/oauth/start":
                try:
                    import drive_delivery
                    payload = drive_delivery.begin_oauth()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, **payload}).encode("utf-8"))
                except Exception as e:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Package listing to Drive (customer folder + private mockups) and compile PDF
            if path == "/api/drive/package":
                piece_dir = data.get("piece_dir")
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Invalid piece_dir"}).encode("utf-8"))
                    return
                try:
                    import drive_delivery
                    settings = load_suite_settings()
                    root_id = (data.get("root_folder_id")
                               or (settings.get("drive") or {}).get("root_folder_id")
                               or drive_delivery.DEFAULT_ROOT_FOLDER_ID)
                    result = drive_delivery.package_piece_to_drive(
                        piece_dir,
                        root_folder_id=root_id,
                        compile_pdf=data.get("compile_pdf", True) is not False,
                        pdf_script=PDF_SCRIPT,
                        python_exe=PYTHON_EXE,
                    )
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Create draft via Etsy Open API (preferred — no Seller Manager bot wall)
            if path == "/api/upload_api":
                piece_dir = data.get("piece_dir")
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Invalid piece_dir"}).encode("utf-8"))
                    return
                try:
                    from etsy_api import create_draft_from_piece
                    write_upload_status(piece_dir, "running", "Creating draft via Etsy Open API…")
                    result = create_draft_from_piece(piece_dir)
                    write_upload_status(
                        piece_dir,
                        "succeeded",
                        f"API draft created (listing {result.get('listing_id')})",
                        draft_url=result.get("draft_url"),
                    )
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    write_upload_status(piece_dir, "failed", str(e))
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Import shop capture from browser bookmarklet / paste
            if path == "/api/import_shop_capture":
                from shop_capture import parse_page_text, parse_paste_text

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()

                if data.get("paste_text"):
                    result = parse_paste_text(data.get("paste_text", ""), data.get("shop_name", ""))
                else:
                    result = parse_page_text(
                        data.get("page_text", ""),
                        shop_url=data.get("shop_url", ""),
                        shop_name=data.get("shop_name", ""),
                        listings=data.get("listings") or [],
                        stats=data.get("stats") or {},
                    )
                result["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                with LATEST_SHOP_CAPTURE_LOCK:
                    LATEST_SHOP_CAPTURE = result
                print(f"Shop capture imported: {result.get('shop_name')} sales={result.get('sales')}")
                self.wfile.write(json.dumps({"success": True, "shop": result}).encode("utf-8"))
                return

            # API: Import listing capture (EverBee-style listing analyzer Phase 1)
            if path == "/api/import_listing_capture":
                from listing_capture import parse_listing_capture, append_listing_snapshot

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                result = parse_listing_capture(
                    page_text=data.get("page_text", ""),
                    listing_url=data.get("listing_url", ""),
                    stats=data.get("stats") or {},
                    tags=data.get("tags"),
                    details=data.get("details") or {},
                )
                append_listing_snapshot(result)
                with LATEST_LISTING_CAPTURE_LOCK:
                    LATEST_LISTING_CAPTURE = result
                print(
                    f"Listing capture: {result.get('listing_id')} "
                    f"views={result.get('views')} favs={result.get('favorites')} "
                    f"est_mo={result.get('est_monthly_sales')}"
                )
                self.wfile.write(json.dumps({"success": True, "listing": result}).encode("utf-8"))
                return

            # API: Trigger Etsy Login
            if path == "/api/login":
                success = False
                error_msg = ""
                try:
                    if not os.path.isfile(PYTHON_EXE):
                        raise FileNotFoundError(f"Python not found: {PYTHON_EXE}")
                    if not os.path.isfile(UPLOAD_SCRIPT):
                        raise FileNotFoundError(f"Login script not found: {UPLOAD_SCRIPT}")
                    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    subprocess.Popen(
                        [PYTHON_EXE, UPLOAD_SCRIPT, "--login"],
                        cwd=HERE,
                        env=playwright_env(),
                        creationflags=creationflags,
                    )
                    success = True
                    print("Launched Etsy login in new console window.")
                except Exception as e:
                    error_msg = str(e)
                    print(f"Error launching login: {e}")

                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "error": error_msg}).encode('utf-8'))
                return

            # API: Open Folder in Explorer
            if path == "/api/open_folder":
                piece_dir = data.get("piece_dir")
                success = False
                if os.path.exists(piece_dir):
                    try:
                        os.startfile(piece_dir)
                        success = True
                    except Exception as e:
                        print(f"Error opening folder: {e}")
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return

            # API: Research library save / update / delete / category
            if path == "/api/research_library":
                from research_library import add_item, update_item, delete_item, add_category, list_items
                action = (data.get("action") or "save").strip().lower()
                try:
                    if action == "save":
                        item = add_item(
                            kind=data.get("kind"),
                            payload=data.get("payload") or {},
                            category=data.get("category"),
                            notes=data.get("notes") or "",
                            title=data.get("title"),
                            tags=data.get("tags"),
                        )
                        self.send_response(200)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "item": item}).encode("utf-8"))
                        return
                    if action == "update":
                        item = update_item(
                            data.get("id"),
                            category=data.get("category"),
                            notes=data.get("notes"),
                            title=data.get("title"),
                            tags=data.get("tags"),
                        )
                        self.send_response(200 if item else 404)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": bool(item), "item": item}).encode("utf-8"))
                        return
                    if action == "delete":
                        ok = delete_item(data.get("id"))
                        self.send_response(200 if ok else 404)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": ok}).encode("utf-8"))
                        return
                    if action == "add_category":
                        name = add_category(data.get("name"))
                        self.send_response(200 if name else 400)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": bool(name), "name": name, **list_items()}).encode("utf-8"))
                        return
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": f"Unknown action: {action}"}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Generate Candidates
            if path == "/api/generate_candidates":
                concept = data.get("concept")
                prompt = data.get("prompt")
                aspect = data.get("aspect", "4:5")
                model = data.get("model", "nano-banana-pro")

                preflight = build_preflight()
                if not preflight.get("can_generate"):
                    reasons = []
                    if not preflight.get("env_file_present"):
                        reasons.append(f"API keys file missing at {ENV_FILE_PATH}")
                    elif not preflight.get("gemini_key_set") and not preflight.get("cloudflare_ready"):
                        reasons.append(
                            "No image provider ready — set GEMINI_API_KEY or "
                            "CLOUDFLARE_WORKER_URL + CLOUDFLARE_WORKER_KEY in ~/.config/ai-images/env"
                        )
                    if not preflight.get("python_exe_present"):
                        reasons.append("Project venv Python not found")
                    err = "; ".join(reasons) or "Cannot generate — check preflight"
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": err,
                        "candidates": [],
                        "suggested_titles": [],
                        "run_dir": "",
                        "variant_errors": [],
                        "preflight": preflight,
                    }).encode("utf-8"))
                    return
                
                # Fetch suggested titles from Gemini
                suggested_titles = self.get_ai_title_suggestions(concept, prompt)
                
                success, candidates, run_dir, variant_errors, error = self.generate_run_candidates(
                    concept, prompt, aspect, model
                )
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": success,
                    "candidates": candidates,
                    "suggested_titles": suggested_titles,
                    "run_dir": (run_dir or "").replace("\\", "/"),
                    "variant_errors": variant_errors,
                    "error": error,
                }).encode('utf-8'))
                return

            # API: Import public-domain Met objects as candidates (always a pack)
            if path == "/api/public_domain/import":
                objects = data.get("objects") or []
                concept = (data.get("concept") or "public domain vintage").strip()
                if not objects:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Select at least one artwork."}).encode("utf-8"))
                    return
                try:
                    import importlib
                    import public_domain as _pd_mod
                    importlib.reload(_pd_mod)
                    from public_domain import import_objects_to_run
                    run_dir, candidates, errors, manifest = import_objects_to_run(
                        objects, RUNS_DIR, concept=concept, trim_borders=True
                    )
                    for c in candidates:
                        full = c["path"].replace("/", os.sep)
                        c["rel_path"] = os.path.relpath(full, ROOT_DIR).replace("\\", "/")
                        c["path"] = full.replace("\\", "/")
                    pack_title = concept.title() if concept else "Vintage Print Pack"
                    titles = [
                        f"{pack_title} — {len(candidates)}+ Vintage Digital Prints Bundle",
                        f"{pack_title} Gallery Wall Set, Printable Public Domain Art Pack",
                        f"Vintage Art Bundle ({len(candidates)} Prints), Eclectic Gallery Wall Download",
                    ]
                    err_note = None
                    if errors and candidates:
                        err_note = f"Imported {len(candidates)}; {len(errors)} failed."
                    self.send_response(200 if candidates else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": bool(candidates),
                        "product_type": "pd_bundle",
                        "pack_title": pack_title,
                        "candidates": candidates,
                        "suggested_titles": titles,
                        "run_dir": run_dir.replace("\\", "/"),
                        "manifest": manifest,
                        "errors": errors,
                        "error": None if candidates else (errors[0]["error"] if errors else "Import failed"),
                        "warning": err_note,
                    }).encode("utf-8"))
                except ValueError as e:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Graphic poster — generate visual + real text overlay
            if path == "/api/compose_poster":
                concept = (data.get("concept") or "").strip()
                headline = (data.get("headline") or "").strip()
                subtext = (data.get("subtext") or "").strip()
                style_spine = (data.get("prompt") or "").strip()
                aspect = data.get("aspect") or "4:5"
                model = data.get("model") or "cf-sdxl-lightning"
                layout = data.get("layout") or "hero_stack"
                n = max(1, min(int(data.get("n") or 2), 3))

                if not concept:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Concept / subject is required."}).encode("utf-8"))
                    return
                if not headline:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Headline text is required (we draw real fonts, not AI letters)."}).encode("utf-8"))
                    return

                preflight = build_preflight()
                if not preflight.get("can_generate"):
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "No image provider ready — check Cloudflare/Gemini keys.", "preflight": preflight}).encode("utf-8"))
                    return

                try:
                    from poster_compose import compose_poster, visual_prompt_for_poster
                    import re
                    from datetime import datetime

                    visual = visual_prompt_for_poster(concept, style_spine)
                    generate_script = os.path.join(ROOT_DIR, "tooling", "ad-creatives", "generate.py")
                    slug = re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_") or "poster"
                    run_dir = os.path.join(RUNS_DIR, f"poster_{slug}")
                    counter = 1
                    while os.path.exists(run_dir):
                        run_dir = os.path.join(RUNS_DIR, f"poster_{slug}_{counter}")
                        counter += 1
                    candidates_dir = os.path.join(run_dir, "_candidates")
                    raw_dir = os.path.join(run_dir, "_poster_raw")
                    os.makedirs(candidates_dir, exist_ok=True)
                    os.makedirs(raw_dir, exist_ok=True)

                    candidates = []
                    errors = []
                    for i in range(n):
                        label = f"poster{i+1}"
                        cmd = [
                            PYTHON_EXE, generate_script, visual,
                            "--model", model, "--aspect", aspect, "--n", "1",
                            "--label", label, "--out", raw_dir,
                        ]
                        ok, stdout, stderr = self.run_subprocess(cmd)
                        if not ok:
                            errors.append({"label": label, "error": stderr_tail(stderr) or stderr_tail(stdout) or "gen failed"})
                            continue
                        raws = sorted([
                            f for f in os.listdir(raw_dir)
                            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and label in f
                        ])
                        if not raws:
                            # any newest file
                            raws = sorted([
                                f for f in os.listdir(raw_dir)
                                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                            ], key=lambda x: os.path.getmtime(os.path.join(raw_dir, x)))
                        if not raws:
                            errors.append({"label": label, "error": "No raw image produced"})
                            continue
                        raw_path = os.path.join(raw_dir, raws[-1])
                        layers = None
                        try:
                            from poster_compose import default_layers_for_layout
                            layers = default_layers_for_layout(headline, subtext, layout=layout)
                        except Exception:
                            layers = None
                        png_bytes = compose_poster(
                            raw_path,
                            headline=headline,
                            subtext=subtext,
                            aspect=aspect,
                            layout=layout,
                            accent_circle=(layout == "hero_stack"),
                            layers=layers,
                        )
                        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                        out_path = os.path.join(candidates_dir, f"{ts}_{label}-composed.png")
                        with open(out_path, "wb") as f:
                            f.write(png_bytes)
                        candidates.append({
                            "label": label,
                            "rel_path": os.path.relpath(out_path, ROOT_DIR).replace("\\", "/"),
                            "path": out_path.replace("\\", "/"),
                            "raw_path": raw_path.replace("\\", "/"),
                            "raw_rel": os.path.relpath(raw_path, ROOT_DIR).replace("\\", "/"),
                            "prompt": f"{visual} | headline={headline} | sub={subtext}",
                            "model": model,
                            "aspect": aspect,
                            "layout": layout,
                            "headline": headline,
                            "subtext": subtext,
                            "text_layers": layers or [],
                            "product_kind": "graphic_poster",
                        })

                    titles = [
                        f"{headline.title()} Poster, Retro Kitchen Wall Art Digital Download",
                        f"{headline.title()} Print, Dopamine Decor Aesthetic Poster",
                        f"Bold {headline.title()} Wall Art, Vintage Graphic Poster",
                    ]
                    self.send_response(200 if candidates else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": bool(candidates),
                        "candidates": candidates,
                        "suggested_titles": titles,
                        "run_dir": run_dir.replace("\\", "/"),
                        "variant_errors": errors,
                        "error": None if candidates else (errors[0]["error"] if errors else "Poster compose failed"),
                    }).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Re-burn poster typography from editable layers (Figma-ish editor export)
            if path == "/api/recompose_poster":
                base_path = (data.get("base_path") or data.get("raw_path") or "").replace("/", os.sep)
                out_path = (data.get("out_path") or data.get("path") or "").replace("/", os.sep)
                layers = data.get("layers") or data.get("text_layers") or []
                aspect = data.get("aspect") or "4:5"
                layout = data.get("layout") or "hero_stack"
                paper_tint = data.get("paper_tint", True)
                accent_circle = bool(data.get("accent_circle"))
                # Explicit pad only — never auto-inset museum layouts (fake mats in frames)
                pad_subject = float(data.get("pad_subject") or 0)
                base_b64 = data.get("base_png_b64") or data.get("base_image_b64")
                if base_b64 and base_path:
                    try:
                        import base64
                        raw = base64.b64decode(base_b64)
                        os.makedirs(os.path.dirname(base_path) or ".", exist_ok=True)
                        with open(base_path, "wb") as f:
                            f.write(raw)
                    except Exception as e:
                        self.send_response(400)
                        self.send_header("Content-type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": False, "error": f"Failed to save patched base: {e}"}).encode("utf-8"))
                        return
                if not base_path or not os.path.isfile(base_path):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "base/raw image missing"}).encode("utf-8"))
                    return
                if not out_path:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "out_path required"}).encode("utf-8"))
                    return
                try:
                    from poster_compose import compose_from_layers
                    png_bytes = compose_from_layers(
                        base_path,
                        layers=layers,
                        aspect=aspect,
                        paper_tint=paper_tint,
                        accent_circle=accent_circle,
                        long_edge=2000,
                        pad_subject=pad_subject,
                    )
                    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(png_bytes)
                    # Persist layer sidecar next to output for reopen
                    side = out_path.rsplit(".", 1)[0] + ".layers.json"
                    with open(side, "w", encoding="utf-8") as f:
                        json.dump({
                            "layers": layers,
                            "aspect": aspect,
                            "layout": layout,
                            "base_path": base_path.replace("\\", "/"),
                            "pad_subject": pad_subject,
                            "accent_circle": accent_circle,
                        }, f, indent=2)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "path": out_path.replace("\\", "/"),
                        "rel_path": os.path.relpath(out_path, ROOT_DIR).replace("\\", "/"),
                        "layers": layers,
                        "base_updated": bool(base_b64),
                    }).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Re-burn typography on an existing Catalog piece (master + prints)
            if path == "/api/recompose_catalog_piece":
                piece_dir = (data.get("piece_dir") or "").replace("/", os.sep)
                layers = data.get("layers") or data.get("text_layers") or []
                refresh_prints = bool(data.get("refresh_prints", True))
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "piece_dir required"}).encode("utf-8"))
                    return
                try:
                    result = self.recompose_catalog_piece(piece_dir, layers, data, refresh_prints=refresh_prints)
                    self.send_response(200 if result.get("success") else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Ensure Catalog piece has poster_base + layers so Edit type always opens
            if path == "/api/bootstrap_poster_edit":
                piece_dir = (data.get("piece_dir") or "").replace("/", os.sep)
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "piece_dir required"}).encode("utf-8"))
                    return
                try:
                    result = self.bootstrap_poster_edit(piece_dir)
                    self.send_response(200 if result.get("success") else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Finalize Selected Winners
            if path == "/api/finalize_selected":
                run_dir = data.get("run_dir")
                keepers = data.get("keepers", [])
                trim_margin = float(data.get("trim_margin", 0))
                mode = (data.get("mode") or "").strip().lower()
                selected_templates = data.get("selected_templates") or []
                pack_title = data.get("pack_title") or ""
                if mode == "pd_bundle" or data.get("product_type") == "pd_bundle":
                    result = self.finalize_pd_bundle(
                        run_dir, keepers,
                        pack_title=pack_title,
                        selected_templates=selected_templates,
                        trim_borders=True,
                    )
                elif mode in ("ai_bundle", "bundle", "theme_bundle") or data.get("product_type") == "bundle":
                    result = self.finalize_ai_bundle(
                        run_dir, keepers,
                        pack_title=pack_title,
                        trim_margin=trim_margin,
                    )
                else:
                    result = self.finalize_selected_keepers(run_dir, keepers, trim_margin)
                status = 200 if result.get("any_success") else 500
                self.send_response(status)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
                return

            # API: Auto-place pack images into selected multi-frame mockups
            if path == "/api/pd_bundle_autoplace":
                piece_dir = (data.get("piece_dir") or "").replace("/", os.sep)
                template_names = data.get("templates") or []
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "piece_dir required"}).encode("utf-8"))
                    return
                try:
                    result = self.pd_bundle_autoplace(piece_dir, template_names)
                    self.send_response(200 if result.get("success") else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Auto-detect frame openings in mockup photo
            if path == "/api/detect_mockup_frames":
                image_data = data.get("image_data")
                if not image_data:
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "image_data required"}).encode("utf-8"))
                    return
                try:
                    sys.path.insert(0, os.path.join(ROOT_DIR, "tooling", "mockups"))
                    from detect_frames import detect_from_base64
                    result = detect_from_base64(image_data)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                except Exception as e:
                    print(f"Frame detection error: {e}")
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # API: Save Mockup Template
            if path == "/api/save_mockup_template":
                name = data.get("name")
                orientation = data.get("orientation")
                aspect = data.get("aspect")
                box = data.get("box")
                tags = data.get("tags", [])
                image_data = data.get("image_data")
                quad = data.get("quad")
                quads = data.get("quads")
                layout = data.get("layout")
                frame_count = data.get("frame_count")
                
                success = self.save_mockup_template(
                    name, orientation, aspect, box, image_data, tags, quad, quads,
                    layout=layout, frame_count=frame_count,
                )
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return

            if path == "/api/delete_mockup_template":
                name = data.get("name")
                success = self.delete_mockup_template(name)
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return

            if path == "/api/save_mockup_prefs":
                piece_dir = data.get("piece_dir")
                disabled = data.get("disabled_mockups", [])
                include_zoom = data.get("include_zoom_gif", True)
                selected = data.get("selected_templates", None)
                photo_order = data.get("photo_order", None)
                extra = {}
                for key in (
                    "repeat_mockups",
                    "generate_overview_grids",
                    "overview_max_sheets",
                    "max_room_mockups",
                ):
                    if key in data:
                        extra[key] = data[key]
                success = self.save_mockup_prefs(
                    piece_dir, disabled, include_zoom,
                    selected_templates=selected,
                    photo_order=photo_order,
                    extra_prefs=extra or None,
                )
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return

            if path == "/api/delete_piece":
                piece_dir = (data.get("piece_dir") or "").replace("/", os.sep)
                if not piece_dir or not os.path.isdir(piece_dir):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Invalid piece_dir"}).encode("utf-8"))
                    return
                # Safety: only delete under artwork-runs
                runs_norm = os.path.normcase(os.path.abspath(RUNS_DIR))
                piece_norm = os.path.normcase(os.path.abspath(piece_dir))
                if not piece_norm.startswith(runs_norm + os.sep) and piece_norm != runs_norm:
                    self.send_response(403)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Path not under artwork-runs"}).encode("utf-8"))
                    return
                if not os.path.exists(os.path.join(piece_dir, "meta.json")):
                    self.send_response(400)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Not a catalog piece (missing meta.json)"}).encode("utf-8"))
                    return
                try:
                    import shutil
                    parent = os.path.dirname(piece_dir)
                    shutil.rmtree(piece_dir)
                    # Remove empty run folder
                    if os.path.isdir(parent) and parent.startswith(os.path.abspath(RUNS_DIR)):
                        leftover = [x for x in os.listdir(parent) if not x.startswith(".")]
                        if not leftover:
                            try:
                                os.rmdir(parent)
                            except OSError:
                                pass
                    try:
                        from factory import events
                        from factory.audit import audit
                        audit("product.deleted", piece_dir=piece_dir)
                        events.publish("product.deleted", {"piece_dir": piece_dir})
                        events.invalidate("product.deleted")
                    except Exception:
                        pass
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

            # Unknown POST route — always reply (avoids browser "Failed to fetch")
            self.send_response(404)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": f"Unknown API route: {path}. Restart the Production Suite server to load new endpoints.",
            }).encode("utf-8"))
        except Exception as e:
            print(f"Exception in POST handler: {e}")
            try:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
            except Exception:
                pass

    def extract_marker_json(self, stdout, marker):
        if marker not in stdout:
            return None
        json_str = stdout.split(marker, 1)[1].strip()
        if not json_str:
            return None
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Some scripts print a label line before JSON — skip to first { or [
            for i, ch in enumerate(json_str):
                if ch in "{[":
                    try:
                        return json.loads(json_str[i:])
                    except json.JSONDecodeError:
                        break
        return None

    def get_calibrated_template_names(self):
        """Return template names that are calibrated and eligible for mockup output."""
        templates_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
        names = set()
        if not os.path.exists(templates_path):
            return names
        with open(templates_path, "r", encoding="utf-8") as f:
            templates = json.load(f)
        for t in templates:
            if t.get("needs_calibration"):
                continue
            if t.get("calibrated") or t.get("quad") or t.get("quads"):
                names.add(t.get("name"))
        return names

    def mockup_stem_from_filename(self, filename):
        lower = filename.lower()
        if not lower.startswith("mockup_") or not lower.endswith((".jpg", ".jpeg")):
            return None
        stem = filename[7:lower.rfind(".")]
        # Repeat variants: mockup_{template}_r01.jpg → template name
        if len(stem) > 4 and stem[-4] == "_" and stem[-3].lower() == "r" and stem[-2:].isdigit():
            stem = stem[:-4]
        return stem

    def scan_runs(self):
        runs = []
        if not os.path.exists(RUNS_DIR):
            return runs
            
        for run_name in sorted(os.listdir(RUNS_DIR)):
            run_path = os.path.join(RUNS_DIR, run_name)
            if not os.path.isdir(run_path):
                continue
                
            run_data = {
                "name": run_name,
                "path": run_path,
                "pieces": []
            }
            
            for piece_name in sorted(os.listdir(run_path)):
                piece_path = os.path.join(run_path, piece_name)
                meta_path = os.path.join(piece_path, "meta.json")
                if not os.path.isdir(piece_path) or not os.path.exists(meta_path):
                    continue
                    
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)

                    # Bundle member pieces are assembled into one listing piece — hide the parts.
                    if meta.get("exclude_from_catalog") or meta.get("batch_role") == "bundle_member":
                        continue
                    
                    listing_path = os.path.join(piece_path, "listing.json")
                    listing = {}
                    if os.path.exists(listing_path):
                        with open(listing_path, "r", encoding="utf-8") as f:
                            listing = json.load(f)
                            
                    # Get list of mockups — calibrated templates + overview grids + _rNN repeats
                    calibrated_names = self.get_calibrated_template_names()
                    all_mockup_files = sorted([
                        f for f in os.listdir(piece_path)
                        if f.lower().startswith("mockup_") and f.lower().endswith(".jpg")
                        and (
                            f.lower().startswith("mockup_overview_")
                            or self.mockup_stem_from_filename(f) in calibrated_names
                        )
                    ])
                    mockup_prefs = meta.get("mockup_prefs", {})
                    disabled = set(mockup_prefs.get("disabled_mockups", []))
                    include_zoom = mockup_prefs.get("include_zoom_gif", True)
                    mockups = [m for m in all_mockup_files if m not in disabled]
                    
                    # Check if PDF exists
                    has_pdf = any(f.lower().endswith(".pdf") for f in os.listdir(piece_path))
                    upload_st = read_upload_status(piece_path)
                    
                    # Check if Zoom GIF exists
                    has_zoom = "mockup_zoom.gif" in os.listdir(piece_path)
                    rel_zoom = None
                    if has_zoom:
                        rel_zoom = os.path.relpath(
                            os.path.join(piece_path, "mockup_zoom.gif"), ROOT_DIR
                        ).replace("\\", "/")
                    
                    # Get relative paths for images to render on dashboard
                    rel_master = os.path.relpath(os.path.join(piece_path, "master.png"), ROOT_DIR).replace("\\", "/")
                    rel_master_preview = ensure_piece_master_watermark(piece_path) or rel_master
                    rel_mockups = [os.path.relpath(os.path.join(piece_path, m), ROOT_DIR).replace("\\", "/") for m in mockups]
                    rel_all_mockups = [os.path.relpath(os.path.join(piece_path, m), ROOT_DIR).replace("\\", "/") for m in all_mockup_files]
                    
                    # Quality warnings from finalize / mockup scan
                    quality_warnings = meta.get("quality_warnings", [])
                    summary_path = os.path.join(piece_path, "mockup_summary.json")
                    if os.path.exists(summary_path):
                        try:
                            with open(summary_path, "r", encoding="utf-8") as f:
                                summary = json.load(f)
                            for w in summary.get("warnings", []):
                                if w not in quality_warnings:
                                    quality_warnings.append(w)
                        except Exception:
                            pass

                    print_jpg_count = 0
                    for name in os.listdir(piece_path):
                        sub = os.path.join(piece_path, name)
                        if os.path.isdir(sub) and ("print" in name.lower()):
                            print_jpg_count += len([
                                f for f in os.listdir(sub) if f.lower().endswith(".jpg")
                            ])
                    
                    try:
                        mtime = os.path.getmtime(meta_path)
                    except OSError:
                        mtime = 0

                    run_data["pieces"].append({
                        "title": meta.get("title"),
                        "slug": meta.get("slug"),
                        "path": piece_path,
                        "product_type": meta.get("product_type") or "print",
                        "product_kind": meta.get("product_kind"),
                        "bundle_count": meta.get("bundle_count"),
                        "orientation": meta.get("orientation"),
                        "aspect": meta.get("aspect") or (meta.get("typography") or {}).get("aspect"),
                        "sizes": meta.get("sizes", []),
                        "prompt": meta.get("prompt"),
                        "price": meta.get("price", "4.99"),
                        "quantity": meta.get("quantity", "999"),
                        "uploaded_at": meta.get("uploaded_at"),
                        "seo_title": listing.get("title", meta.get("seo", {}).get("title", "")),
                        "seo_tags": listing.get("tags", meta.get("seo", {}).get("tags", [])),
                        "seo_description": listing.get("description", meta.get("seo", {}).get("description", "")),
                        "seo_materials": listing.get("materials", meta.get("seo", {}).get("materials", [])),
                        "master_image": rel_master,
                        "master_preview": rel_master_preview,
                        "mockups": rel_mockups,
                        "all_mockups": rel_all_mockups,
                        "mockup_prefs": mockup_prefs,
                        "mockup_placements": meta.get("mockup_placements") or {},
                        "single_frame_sources": meta.get("single_frame_sources") or {},
                        "cover_image": meta.get("cover_image"),
                        "zoom_gif": rel_zoom,
                        "has_pdf": has_pdf,
                        "pdf_path": meta.get("pdf_path"),
                        "drive_link": meta.get("drive_link"),
                        "upload_status": upload_st,
                        "print_jpg_count": print_jpg_count,
                        "calibrated_mockup_count": len(all_mockup_files),
                        "quality_warnings": quality_warnings,
                        "mtime": mtime,
                        "run_name": run_name,
                        "text_layers": meta.get("text_layers") or (meta.get("typography") or {}).get("layers") or [],
                        "typography": self._typography_catalog_payload(piece_path, meta),
                        "stale_artifacts": meta.get("stale_artifacts") or [],
                        "stale_reason": meta.get("stale_reason"),
                        "batch_id": meta.get("batch_id"),
                        "listing_id": meta.get("listing_id"),
                        "dry_run": bool(meta.get("dry_run")),
                    })
                except Exception as e:
                    print(f"Error reading piece {piece_name}: {e}")
                    
            if run_data["pieces"]:
                runs.append(run_data)
                
        return runs

    def _typography_catalog_payload(self, piece_path, meta):
        """Normalize typography fields for Catalog UI."""
        typo = dict(meta.get("typography") or {})
        layers = meta.get("text_layers") or typo.get("layers") or []

        # Recover layers from sidecar next to master (written by recompose)
        if not layers:
            for name in ("master.layers.json", "master.png.layers.json"):
                side = os.path.join(piece_path, name)
                if not os.path.isfile(side) and name == "master.png.layers.json":
                    side = os.path.join(piece_path, "master.layers.json")
                if os.path.isfile(side):
                    try:
                        with open(side, "r", encoding="utf-8") as f:
                            side_data = json.load(f)
                        layers = side_data.get("layers") or []
                        if layers and not typo.get("aspect"):
                            typo["aspect"] = side_data.get("aspect") or typo.get("aspect")
                            typo["layout"] = side_data.get("layout") or typo.get("layout")
                        break
                    except Exception:
                        pass
            # Also any *.layers.json in the piece folder
            if not layers:
                try:
                    for fname in os.listdir(piece_path):
                        if fname.lower().endswith(".layers.json"):
                            with open(os.path.join(piece_path, fname), "r", encoding="utf-8") as f:
                                side_data = json.load(f)
                            layers = side_data.get("layers") or []
                            if layers:
                                typo.setdefault("aspect", side_data.get("aspect"))
                                typo.setdefault("layout", side_data.get("layout"))
                                break
                except Exception:
                    pass

        poster_base = (typo.get("poster_base") or "").replace("/", os.sep)
        if not poster_base:
            candidate = os.path.join(piece_path, "poster_base.png")
            if os.path.isfile(candidate):
                poster_base = candidate
        # Fallback: if base path stored in sidecar
        if not poster_base or not os.path.isfile(poster_base):
            try:
                side = os.path.join(piece_path, "master.layers.json")
                if os.path.isfile(side):
                    with open(side, "r", encoding="utf-8") as f:
                        side_data = json.load(f)
                    bp = (side_data.get("base_path") or "").replace("/", os.sep)
                    if bp and os.path.isfile(bp):
                        # Copy into piece so future edits are self-contained
                        dest = os.path.join(piece_path, "poster_base.png")
                        if not os.path.isfile(dest):
                            import shutil
                            shutil.copy(bp, dest)
                        poster_base = dest if os.path.isfile(dest) else bp
            except Exception:
                pass

        master_path = os.path.join(piece_path, "master.png")
        has_base = bool(poster_base and os.path.isfile(poster_base))
        # Editable if we have a base art file; layers optional (can add text fresh)
        editable = has_base
        # Also treat graphic posters / chilli runs as candidates even without base
        # (button still shows; open will guide the user)
        product_kind = (meta.get("product_kind") or "").strip()
        run_hint = (meta.get("run_dir") or piece_path or "").lower()
        looks_poster = product_kind == "graphic_poster" or "poster_" in run_hint.replace("\\", "/")

        payload = {
            "editable": editable,
            "layers": layers,
            "aspect": typo.get("aspect") or meta.get("aspect") or "4:5",
            "layout": typo.get("layout") or "hero_stack",
            "poster_base_path": poster_base.replace("\\", "/") if poster_base else "",
            "poster_base_rel": (
                os.path.relpath(poster_base, ROOT_DIR).replace("\\", "/")
                if poster_base and os.path.isfile(poster_base) else ""
            ),
            "master_path": master_path.replace("\\", "/"),
            "looks_poster": looks_poster,
            "has_layers": bool(layers),
        }
        return payload

    def bootstrap_poster_edit(self, piece_dir):
        """Make any Catalog piece editable: ensure poster_base.png + typography meta exist."""
        import shutil
        meta_path = os.path.join(piece_dir, "meta.json")
        master_path = os.path.join(piece_dir, "master.png")
        if not os.path.isfile(meta_path):
            return {"success": False, "error": "meta.json missing"}
        if not os.path.isfile(master_path):
            return {"success": False, "error": "master.png missing"}

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        typo = dict(meta.get("typography") or {})
        layers = meta.get("text_layers") or typo.get("layers") or []
        bootstrapped = False

        # Recover layers from sidecars
        if not layers:
            for fname in os.listdir(piece_dir):
                if fname.lower().endswith(".layers.json"):
                    try:
                        with open(os.path.join(piece_dir, fname), "r", encoding="utf-8") as f:
                            side = json.load(f)
                        layers = side.get("layers") or []
                        typo.setdefault("aspect", side.get("aspect"))
                        typo.setdefault("layout", side.get("layout"))
                        if layers:
                            break
                    except Exception:
                        pass

        poster_base = os.path.join(piece_dir, "poster_base.png")
        existing = (typo.get("poster_base") or "").replace("/", os.sep)
        if existing and os.path.isfile(existing):
            if os.path.abspath(existing) != os.path.abspath(poster_base):
                try:
                    shutil.copy(existing, poster_base)
                except Exception:
                    poster_base = existing
        elif not os.path.isfile(poster_base):
            # Try run_dir raws
            run_dir = (meta.get("run_dir") or "").replace("/", os.sep)
            found_raw = None
            if run_dir and os.path.isdir(run_dir):
                raw_dir = os.path.join(run_dir, "_poster_raw")
                search_dirs = [raw_dir, os.path.join(run_dir, "_candidates"), run_dir]
                for d in search_dirs:
                    if not os.path.isdir(d):
                        continue
                    pngs = sorted(
                        [os.path.join(d, f) for f in os.listdir(d)
                         if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                         and "raw" in f.lower()],
                        key=lambda p: os.path.getmtime(p),
                        reverse=True,
                    )
                    if not pngs:
                        pngs = sorted(
                            [os.path.join(d, f) for f in os.listdir(d)
                             if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))],
                            key=lambda p: os.path.getmtime(p),
                            reverse=True,
                        )
                    if pngs:
                        found_raw = pngs[0]
                        break
            if found_raw and os.path.isfile(found_raw):
                shutil.copy(found_raw, poster_base)
            else:
                # Last resort: use master (text may be burned in — user heals with marquee)
                shutil.copy(master_path, poster_base)
                bootstrapped = True

        typo.update({
            "editable": True,
            "layers": layers,
            "aspect": typo.get("aspect") or meta.get("aspect") or "4:5",
            "layout": typo.get("layout") or "hero_stack",
            "poster_base": poster_base.replace("\\", "/"),
            "master_path": master_path.replace("\\", "/"),
            "bootstrapped_from_master": bootstrapped,
        })
        meta["typography"] = typo
        meta["text_layers"] = layers
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        payload = self._typography_catalog_payload(piece_dir, meta)
        payload["bootstrapped_from_master"] = bootstrapped
        return {
            "success": True,
            "typography": payload,
            "layers": layers,
            "bootstrapped_from_master": bootstrapped,
        }

    def recompose_catalog_piece(self, piece_dir, layers, data=None, refresh_prints=True):
        """Re-burn text layers onto poster_base → master.png and optionally refresh print crops."""
        import shutil
        data = data or {}
        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.isfile(meta_path):
            return {"success": False, "error": "meta.json missing"}
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        typo = meta.get("typography") or {}
        base_path = (typo.get("poster_base") or "").replace("/", os.sep)
        if not base_path or not os.path.isfile(base_path):
            alt = os.path.join(piece_dir, "poster_base.png")
            if os.path.isfile(alt):
                base_path = alt
        if not base_path or not os.path.isfile(base_path):
            # Auto-bootstrap from master so Apply never dead-ends
            master_path = os.path.join(piece_dir, "master.png")
            if os.path.isfile(master_path):
                base_path = os.path.join(piece_dir, "poster_base.png")
                shutil.copy(master_path, base_path)
            else:
                return {"success": False, "error": "poster_base.png missing — cannot re-edit type for this listing"}

        base_b64 = data.get("base_png_b64") or data.get("base_image_b64")
        if base_b64:
            try:
                import base64
                raw = base64.b64decode(base_b64)
                with open(base_path, "wb") as f:
                    f.write(raw)
            except Exception as e:
                return {"success": False, "error": f"Failed to save patched base: {e}"}

        aspect = data.get("aspect") or typo.get("aspect") or meta.get("aspect") or "4:5"
        layout = data.get("layout") or typo.get("layout") or "hero_stack"
        pad_subject = float(data.get("pad_subject") or 0)
        master_path = os.path.join(piece_dir, "master.png")

        long_edge = 4800
        if os.path.isfile(master_path):
            try:
                from PIL import Image as _PilImage
                with _PilImage.open(master_path) as _im:
                    long_edge = max(4800, max(_im.size))
            except Exception:
                pass

        from poster_compose import compose_from_layers
        png_bytes = compose_from_layers(
            base_path,
            layers=layers,
            aspect=aspect,
            paper_tint=True,
            accent_circle=False,
            long_edge=long_edge,
            pad_subject=pad_subject,
        )
        with open(master_path, "wb") as f:
            f.write(png_bytes)

        typo.update({
            "editable": True,
            "layers": layers,
            "aspect": aspect,
            "layout": layout,
            "poster_base": base_path.replace("\\", "/"),
            "master_path": master_path.replace("\\", "/"),
        })
        meta["typography"] = typo
        meta["text_layers"] = layers
        meta["aspect"] = aspect
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        side = master_path.rsplit(".", 1)[0] + ".layers.json"
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"layers": layers, "aspect": aspect, "layout": layout, "base_path": base_path.replace("\\", "/")}, f, indent=2)

        prints_refreshed = False
        if refresh_prints:
            artwork_script = os.path.join(
                ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py"
            )
            if os.path.isfile(artwork_script):
                cmd = [
                    PYTHON_EXE, artwork_script, "finalize", meta_path,
                    "--upscale-mode", "lanczos",
                ]
                ok, stdout, stderr = self.run_subprocess(cmd)
                prints_refreshed = bool(ok)
                if ok:
                    piece_slug = meta.get("slug") or os.path.basename(piece_dir)
                    default_prints = os.path.join(piece_dir, "prints")
                    named_prints = os.path.join(piece_dir, f"{piece_slug}_prints")
                    if os.path.exists(default_prints) and not os.path.exists(named_prints):
                        try:
                            os.rename(default_prints, named_prints)
                        except Exception:
                            pass

        return {
            "success": True,
            "master_rel": os.path.relpath(master_path, ROOT_DIR).replace("\\", "/"),
            "master_preview": ensure_piece_master_watermark(piece_dir, force=True),
            "layers": layers,
            "prints_refreshed": prints_refreshed,
        }

    def save_metadata(self, piece_dir, title, description, tags, price, quantity, materials=None):
        meta_path = os.path.join(piece_dir, "meta.json")
        listing_path = os.path.join(piece_dir, "listing.json")
        
        if not os.path.exists(meta_path):
            return False
            
        try:
            # Update meta.json
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                
            meta["title"] = title
            meta["price"] = price
            meta["quantity"] = quantity
            if "seo" not in meta:
                meta["seo"] = {}
            meta["seo"]["title"] = title
            meta["seo"]["description"] = description
            meta["seo"]["tags"] = tags
            if materials is not None:
                cleaned = [str(m).strip()[:45] for m in materials if str(m).strip()][:13]
                meta["seo"]["materials"] = cleaned
            
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
                
            # Update listing.json / seo.md
            listing_payload = {
                "title": title,
                "tags": tags,
                "description": description
            }
            if materials is not None:
                listing_payload["materials"] = meta["seo"].get("materials", [])
            with open(listing_path, "w", encoding="utf-8") as f:
                json.dump(listing_payload, f, indent=2)
                
            seo_md_path = os.path.join(piece_dir, "seo.md")
            with open(seo_md_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(f"**Listing title**: {title}\n\n")
                f.write("**Tags**:\n")
                for t in tags:
                    f.write(f"- {t}\n")
                mats = meta.get("seo", {}).get("materials") or []
                if mats:
                    f.write("\n**Materials**:\n")
                    for m in mats:
                        f.write(f"- {m}\n")
                f.write(f"\n**Description:**\n\n{description}\n")
                
            return True
        except Exception as e:
            print(f"Error saving metadata: {e}")
            return False

    def run_subprocess(self, cmd):
        return run_python_subprocess(cmd)

    def sanitize_visual_concept(self, concept):
        """Strip words that invite AI gibberish labels (chart, anatomy, taxonomy…)."""
        import re
        text = (concept or "").strip()
        ban = (
            r"\b(anatomy|anatomical|chart|diagram|infographic|taxonomy|"
            r"labeled|labels|label|caption|captions|legend|key|plate|"
            r"scientific name|latin name|handwriting|typography|text)\b"
        )
        cleaned = re.sub(ban, " ", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
        return cleaned or text

    def generate_run_candidates(self, concept, prompt_spine, aspect, model):
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", concept.strip().lower()).strip("_")
        if not slug:
            slug = "run"
        run_dir = os.path.join(RUNS_DIR, slug)
        counter = 1
        while os.path.exists(run_dir):
            run_dir = os.path.join(RUNS_DIR, f"{slug}_{counter}")
            counter += 1
            
        candidates_dir = os.path.join(run_dir, "_candidates")
        os.makedirs(candidates_dir, exist_ok=True)
        
        generate_script = os.path.join(ROOT_DIR, "tooling", "ad-creatives", "generate.py")
        variant_errors = []
        visual = self.sanitize_visual_concept(concept)
        no_text = (
            "pure visual artwork only, absolutely no text, no letters, no words, "
            "no typography, no labels, no captions, no diagrams, no charts"
        )
        
        variants = [
            ("faithful", f"{visual}, {prompt_spine}, {no_text}", []),
            ("signature", f"{visual}, signature art composition, {prompt_spine}, {no_text}", []),
            ("wildcard", f"wildcard interpretation: {visual}, atmospheric creative digital print, {prompt_spine}, {no_text}", []),
        ]

        # Signature style refs for tonal oil
        ref_args = []
        if "plein-air" in prompt_spine or "tonal oil" in prompt_spine or "tonal_oil" in prompt_spine:
            ref_dir = os.path.join(ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "references", "style-refs", "plein-air-tonal-oil")
            ref1 = os.path.join(ref_dir, "ref-farmhouse.png")
            ref2 = os.path.join(ref_dir, "ref-mountains.png")
            if os.path.exists(ref1):
                ref_args += ["--ref", ref1]
            if os.path.exists(ref2):
                ref_args += ["--ref", ref2]
        variants[1] = (variants[1][0], variants[1][1], ref_args)

        for label, prompt_text, extra_args in variants:
            cmd = [
                PYTHON_EXE, generate_script, prompt_text,
                "--model", model, "--aspect", aspect, "--n", "1",
                "--label", label, "--out", candidates_dir,
            ] + list(extra_args)
            ok, stdout, stderr = self.run_subprocess(cmd)
            if not ok:
                detail = stderr_tail(stderr) or stderr_tail(stdout) or f"{label} generation failed (exit non-zero)"
                variant_errors.append({"label": label, "error": detail})
        
        # Scan candidates dir for outputs
        candidates = []
        if os.path.exists(candidates_dir):
            for f in sorted(os.listdir(candidates_dir)):
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    full_path = os.path.join(candidates_dir, f)
                    rel_path = os.path.relpath(full_path, ROOT_DIR).replace("\\", "/")
                    label = "faithful"
                    if "signature" in f:
                        label = "signature"
                    elif "wildcard" in f:
                        label = "wildcard"
                    
                    candidates.append({
                        "label": label,
                        "rel_path": rel_path,
                        "path": full_path.replace("\\", "/"),
                        "prompt": f"{visual} {label}",
                        "model": model,
                        "aspect": aspect,
                    })

        success = len(candidates) > 0
        error = None
        if not success:
            if variant_errors:
                error = variant_errors[0]["error"]
                if len(variant_errors) > 1:
                    error += f" (+{len(variant_errors) - 1} more variant error(s))"
            else:
                error = "Generation finished but produced no PNG candidates."
                    
        return success, candidates, run_dir, variant_errors, error

    def make_piece_slug(self, title, label, run_dir):
        import re
        # Keep short — Windows MAX_PATH breaks long nested print/mockup paths
        slug_text = re.sub(r"[—–]", "-", title or "")
        slug_text = re.sub(r"[^\w\s-]", "", slug_text).strip().lower()
        piece_slug = re.sub(r"[\s_-]+", "-", slug_text) or f"piece-{label or 'art'}"
        if label and label not in piece_slug.split("-"):
            piece_slug = f"{piece_slug}-{label}"
        piece_slug = piece_slug[:48].strip("-")
        base = piece_slug
        counter = 2
        while os.path.exists(os.path.join(run_dir, piece_slug)):
            piece_slug = f"{base}-{counter}"[:56]
            counter += 1
        return piece_slug

    def finalize_selected_keepers(self, run_dir, keepers, trim_margin=0):
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def finalize_one(k):
            source_image = (k.get("source_image") or "").replace("/", os.sep)
            label = clean_win_text(k.get("label") or "art")
            title = clean_win_text(k.get("title") or f"Print {label}")

            if not source_image or not os.path.exists(source_image):
                return {
                    "title": title, "label": label, "success": False,
                    "error": f"Source image not found: {k.get('source_image')}",
                }

            piece_slug = self.make_piece_slug(title, label, run_dir)
            piece_dir = os.path.join(run_dir, piece_slug)
            os.makedirs(piece_dir, exist_ok=True)

            dest_master = os.path.join(piece_dir, "master.png")
            try:
                from PIL import Image
                with Image.open(source_image) as im:
                    im = im.convert("RGB")
                    im.save(dest_master, format="PNG")
            except Exception:
                shutil.copy(source_image, dest_master)

            # Preserve poster typography for Catalog re-edit
            typography = None
            text_layers = k.get("text_layers")
            raw_src = (k.get("raw_path") or "").replace("/", os.sep)
            product_kind = (k.get("product_kind") or "").strip()
            aspect_early = (k.get("aspect") or "").strip() or "4:5"
            if text_layers or product_kind == "graphic_poster" or raw_src:
                poster_base = os.path.join(piece_dir, "poster_base.png")
                if raw_src and os.path.isfile(raw_src):
                    try:
                        shutil.copy(raw_src, poster_base)
                    except Exception:
                        poster_base = None
                else:
                    try:
                        shutil.copy(dest_master, poster_base)
                    except Exception:
                        poster_base = None
                if poster_base and os.path.isfile(poster_base):
                    typography = {
                        "editable": bool(text_layers),
                        "layers": text_layers or [],
                        "aspect": aspect_early,
                        "layout": k.get("layout") or "hero_stack",
                        "poster_base": poster_base.replace("\\", "/"),
                        "master_path": dest_master.replace("\\", "/"),
                    }

            tags = ["printable wall art", "digital art print", "wall decor"]
            description = (
                "Welcome to Aethelgard Art Co.!\n\n"
                "This is a high-resolution 300 DPI digital print ready for instant download "
                "and printing in over 20+ frame sizes.\n\n"
                "Included files are formatted for aspect ratios:\n"
                "- 4:5 (for sizes 4x5, 8x10, 16x20 inches)\n"
                "- 3:2 (for sizes 4x6, 6x9, 8x12, 12x18, 20x30 inches)\n"
                "- 11:14 paper size\n\n"
                "Thank you for supporting our shop!"
            )

            presets_path = os.path.join(HERE, "niche_presets.json")
            if os.path.exists(presets_path):
                try:
                    with open(presets_path, "r", encoding="utf-8") as f:
                        presets = json.load(f)
                    run_name_lower = os.path.basename(run_dir).lower()
                    matched_niche = None
                    if "plaster" in run_name_lower or "arches" in run_name_lower or "japandi" in run_name_lower:
                        matched_niche = next((n for n in presets.get("niches", []) if n["id"] == "japandi_plaster"), None)
                    elif "academia" in run_name_lower or "gothic" in run_name_lower or "moody" in run_name_lower:
                        matched_niche = next((n for n in presets.get("niches", []) if n["id"] == "dark_academia"), None)
                    elif "mushroom" in run_name_lower or "botanical" in run_name_lower or "specimen" in run_name_lower:
                        matched_niche = next((n for n in presets.get("niches", []) if n["id"] == "vintage_specimen"), None)

                    if matched_niche:
                        tags = matched_niche.get("starter_tags", tags)
                        description = (
                            f"Welcome to Aethelgard Art Co.!\n\n"
                            f"This is a premium high-resolution 300 DPI digital print ready for instant download.\n\n"
                            f"Style: {matched_niche.get('name')}\n\n"
                            f"Description: {matched_niche.get('summary')}\n\n"
                            f"Included files are formatted for standard frame aspect ratios:\n"
                            f"- 4:5 ratio (for printing: 4x5\", 8x10\", 12x15\", 16x20\", 40x50cm)\n"
                            f"- 3:2 ratio (for printing: 4x6\", 6x9\", 8x12\", 12x18\", 20x30\", 24x36\", 60x90cm)\n"
                            f"- 11:14\" paper size\n\n"
                            f"Thank you for choosing Aethelgard Art Co.!"
                        )
                except Exception as e:
                    print(f"Error loading presets for finalization: {e}")

            orientation = "portrait"
            aspect = (k.get("aspect") or "").strip()
            if aspect in ("3:2", "16:9"):
                orientation = "landscape"

            piece_meta = {
                "run_dir": run_dir.replace("\\", "/"),
                "title": title,
                "slug": piece_slug,
                "source_image": dest_master.replace("\\", "/"),
                "orientation": orientation,
                "aspect": aspect or aspect_early,
                "sizes": "all",
                "model": clean_win_text(k.get("model", "nano-banana-pro")),
                "prompt": clean_win_text(k.get("prompt", "")),
                "upscale": 4,
                "upscale_mode": "lanczos",
                "price": price_for_product_type(
                    product_kind or "print",
                    product_kind=product_kind or ("graphic_poster" if typography else None),
                ),
                "quantity": str(load_suite_settings().get("default_quantity", 999)),
                "trim_margin": trim_margin,
                "seo": {
                    "title": f"{title} - Printable Wall Art, Vintage Digital Print Decor",
                    "tags": tags,
                    "description": description,
                },
            }
            if typography:
                piece_meta["product_kind"] = product_kind or "graphic_poster"
                piece_meta["text_layers"] = typography.get("layers") or []
                piece_meta["typography"] = typography

            meta_json_path = os.path.join(piece_dir, "meta.json")
            with open(meta_json_path, "w", encoding="utf-8") as f:
                json.dump(piece_meta, f, indent=2)

            artwork_script = os.path.join(
                ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py"
            )
            # Fast path: Lanczos (seconds) — Real-ESRGAN is optional later from Catalog
            cmd_finalize = [
                PYTHON_EXE, artwork_script, "finalize", meta_json_path,
                "--upscale-mode", "lanczos",
            ]
            res, stdout, stderr = self.run_subprocess(cmd_finalize)

            if res:
                default_prints = os.path.join(piece_dir, "prints")
                named_prints = os.path.join(piece_dir, f"{piece_slug}_prints")
                if os.path.exists(default_prints) and not os.path.exists(named_prints):
                    os.rename(default_prints, named_prints)
                # Do NOT block on full mockup library — user regenerates in Catalog (seconds per template)
                return {
                    "title": title,
                    "label": label,
                    "success": True,
                    "piece_dir": piece_dir.replace("\\", "/"),
                    "mockups_deferred": True,
                }

            error_msg = stderr_tail(stderr) or stderr_tail(stdout) or "Finalize pipeline failed (check server console)."
            print(f"Finalize failed for {title}: {error_msg}")
            return {
                "title": title,
                "label": label,
                "success": False,
                "error": error_msg,
                "piece_dir": piece_dir.replace("\\", "/"),
            }

        results = []
        workers = min(4, max(1, len(keepers)))
        if len(keepers) <= 1:
            results = [finalize_one(k) for k in keepers]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(finalize_one, k): k for k in keepers}
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        k = futures[fut]
                        results.append({
                            "title": clean_win_text(k.get("title") or k.get("label") or "art"),
                            "label": clean_win_text(k.get("label") or "art"),
                            "success": False,
                            "error": str(e),
                        })

        artwork_script = os.path.join(
            ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py"
        )
        cmd_index = [PYTHON_EXE, artwork_script, "index", run_dir]
        self.run_subprocess(cmd_index)

        any_success = any(r.get("success") for r in results)
        if any_success and all(r.get("success") for r in results):
            candidates_dir = os.path.join(run_dir, "_candidates")
            if os.path.exists(candidates_dir):
                try:
                    shutil.rmtree(candidates_dir)
                except Exception:
                    pass
        
        return {
            "success": any_success and all(r.get("success") for r in results),
            "any_success": any_success,
            "finalized_count": sum(1 for r in results if r.get("success")),
            "total": len(results),
            "results": results,
        }

    def _mark_bundle_members(self, piece_dirs):
        """Hide member singles from Catalog listings (they live under the set)."""
        for pdir in piece_dirs or []:
            pdir = (pdir or "").replace("/", os.sep)
            meta_path = os.path.join(pdir, "meta.json")
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["exclude_from_catalog"] = True
                meta["batch_role"] = "bundle_member"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception as e:
                print(f"mark bundle member failed for {pdir}: {e}")

    def finalize_ai_bundle(self, run_dir, keepers, pack_title="", trim_margin=0):
        """
        Finalize each AI keeper as a member print, then compose ONE set listing
        (product_type=bundle) — same Catalog shape as library / batch sets.
        """
        if len(keepers or []) < 2:
            return self.finalize_selected_keepers(run_dir, keepers, trim_margin)

        singles = self.finalize_selected_keepers(run_dir, keepers, trim_margin)
        piece_dirs = [
            r["piece_dir"]
            for r in (singles.get("results") or [])
            if r.get("success") and r.get("piece_dir")
        ]
        if len(piece_dirs) < 2:
            return singles

        self._mark_bundle_members(piece_dirs)
        title = clean_win_text(
            pack_title
            or (keepers[0].get("title") if keepers else None)
            or f"Set of {len(piece_dirs)} Prints"
        )
        concept = clean_win_text(
            (keepers[0].get("prompt") if keepers else "") or f"Theme set: {title}"
        )
        bundle = self.create_library_bundle(
            piece_dirs,
            title=title,
            concept=concept,
            auto_seo=True,
            mark_members=False,  # already marked
        )
        if not bundle.get("success"):
            return {
                "success": False,
                "any_success": True,
                "finalized_count": len(piece_dirs),
                "total": len(keepers),
                "results": singles.get("results") or [],
                "error": bundle.get("error") or "Bundle assemble failed after finals",
            }

        member_results = singles.get("results") or []
        return {
            "success": True,
            "any_success": True,
            "finalized_count": 1,
            "total": 1,
            "bundle_count": bundle.get("bundle_count") or len(piece_dirs),
            "piece_dir": bundle.get("piece_dir"),
            "product_type": "bundle",
            "needs_mockup_picker": True,
            "results": member_results + [{
                "title": title,
                "label": "set listing",
                "success": True,
                "piece_dir": bundle.get("piece_dir"),
            }],
            "seo_pack": bundle.get("seo_pack"),
            "member_piece_dirs": piece_dirs,
        }

    def finalize_pd_bundle(self, run_dir, keepers, pack_title="", selected_templates=None, trim_borders=True):
        """One Catalog piece = one Etsy listing; images stay native-aspect in bundle/."""
        import shutil
        from PIL import Image

        if not run_dir or not os.path.isdir(run_dir):
            return {
                "success": False,
                "any_success": False,
                "finalized_count": 0,
                "total": 0,
                "results": [{"title": pack_title or "Pack", "success": False, "error": "Invalid run_dir"}],
            }
        if not keepers:
            return {
                "success": False,
                "any_success": False,
                "finalized_count": 0,
                "total": 0,
                "results": [{"title": pack_title or "Pack", "success": False, "error": "No images selected"}],
            }

        title = clean_win_text(pack_title or keepers[0].get("title") or "Vintage Print Pack")
        piece_slug = self.make_piece_slug(title, "pack", run_dir)
        piece_dir = os.path.join(run_dir, piece_slug)
        bundle_dir = os.path.join(piece_dir, "bundle")
        os.makedirs(bundle_dir, exist_ok=True)

        try:
            from pd_prep import prep_image_file, classify_aspect
        except ImportError:
            prep_image_file = None
            classify_aspect = None

        copied = []
        orientations = {"portrait": 0, "landscape": 0, "square": 0}
        for i, k in enumerate(keepers):
            source_image = (k.get("source_image") or "").replace("/", os.sep)
            if not source_image or not os.path.exists(source_image):
                continue
            stem = clean_win_text(k.get("file_stem") or k.get("art_title") or k.get("label") or f"print-{i+1}")
            stem = re.sub(r"[^\w\s-]", "", stem.lower()).strip()
            stem = re.sub(r"[\s_-]+", "-", stem)[:48].strip("-") or f"print-{i+1}"
            dest = os.path.join(bundle_dir, f"{i+1:02d}-{stem}.png")
            try:
                if prep_image_file:
                    prep = prep_image_file(source_image, dest, trim_borders=trim_borders)
                    orient = prep.get("orientation") or "portrait"
                else:
                    with Image.open(source_image) as im:
                        im = im.convert("RGB")
                        im.save(dest, format="PNG")
                        w, h = im.size
                    if classify_aspect:
                        _, orient, _ = classify_aspect(w, h)
                    else:
                        orient = "landscape" if w > h * 1.08 else ("square" if abs(w - h) / max(w, h) < 0.08 else "portrait")
                    prep = {"orientation": orient}
                orientations[orient] = orientations.get(orient, 0) + 1
                copied.append({
                    "file": os.path.basename(dest),
                    "path": dest.replace("\\", "/"),
                    "label": k.get("label"),
                    "art_title": k.get("art_title") or k.get("title"),
                    "orientation": orient,
                    "aspect": (prep or {}).get("aspect") or k.get("aspect"),
                    "attribution": k.get("attribution"),
                })
            except Exception as e:
                print(f"PD bundle copy failed for {source_image}: {e}")

        if not copied:
            try:
                shutil.rmtree(piece_dir)
            except Exception:
                pass
            return {
                "success": False,
                "any_success": False,
                "finalized_count": 0,
                "total": 1,
                "results": [{"title": title, "success": False, "error": "No valid source images"}],
            }

        # Cover / catalog preview = first pack member (native aspect)
        master_path = os.path.join(piece_dir, "master.png")
        try:
            shutil.copy(copied[0]["path"].replace("/", os.sep), master_path)
        except Exception:
            with Image.open(copied[0]["path"].replace("/", os.sep)) as im:
                im.convert("RGB").save(master_path, format="PNG")

        dominant = max(orientations, key=orientations.get) if any(orientations.values()) else "portrait"
        if orientations.get("landscape", 0) and orientations.get("portrait", 0):
            dominant = "mixed"

        tags = [
            "printable wall art", "digital art print", "vintage art bundle",
            "gallery wall set", "public domain art", "instant download",
            "eclectic gallery wall", "museum print pack", "printable vintage prints",
            "digital download art", "wall decor set", "art print collection",
        ]
        description = (
            f"Welcome to Aethelgard Art Co.!\n\n"
            f"This digital download pack includes {len(copied)} high-resolution vintage / public-domain art prints "
            f"for your gallery wall. Files keep their native proportions (portrait, landscape, and square as applicable) — "
            f"no forced crop to a single frame size.\n\n"
            f"Delivery: PDF guide + Google Drive folder with all print-ready PNGs.\n\n"
            f"Always verify public-domain / Open Access status for commercial use.\n\n"
            f"Thank you for supporting our shop!"
        )

        selected = [t for t in (selected_templates or []) if t]
        piece_meta = {
            "run_dir": run_dir.replace("\\", "/"),
            "title": title,
            "slug": piece_slug,
            "source_image": master_path.replace("\\", "/"),
            "product_type": "pd_bundle",
            "bundle_dir": bundle_dir.replace("\\", "/"),
            "bundle_count": len(copied),
            "bundle_orientations": orientations,
            "orientation": "portrait" if dominant == "mixed" else dominant,
            "orientation_mode": dominant,
            "sizes": "native",
            "model": "public-domain-met",
            "prompt": f"Public domain pack: {title}",
            "upscale": 0,
            "price": price_for_product_type("pd_bundle"),
            "quantity": str(load_suite_settings().get("default_quantity", 999)),
            "trim_margin": 0,
            "seo": {
                "title": f"{title} — {len(copied)} Vintage Digital Prints Bundle, Gallery Wall Set",
                "tags": tags,
                "description": description,
            },
            "mockup_prefs": {
                "disabled_mockups": [],
                "selected_templates": selected,
                "include_zoom_gif": False,
            },
            "mockup_placements": {},
            "skip_print_crops": True,
        }
        meta_json_path = os.path.join(piece_dir, "meta.json")
        with open(meta_json_path, "w", encoding="utf-8") as f:
            json.dump(piece_meta, f, indent=2)

        manifest = {
            "product_type": "pd_bundle",
            "title": title,
            "count": len(copied),
            "files": copied,
            "delivery": "pdf_plus_google_drive",
            "note": "Native aspects preserved; no AI print-ratio crops.",
        }
        with open(os.path.join(piece_dir, "bundle_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        artwork_script = os.path.join(ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py")
        self.run_subprocess([PYTHON_EXE, artwork_script, "index", run_dir])

        # Keep _candidates until user is done; do not auto-generate mockups — picker comes next
        return {
            "success": True,
            "any_success": True,
            "finalized_count": 1,
            "total": 1,
            "product_type": "pd_bundle",
            "needs_mockup_picker": True,
            "piece_dir": piece_dir.replace("\\", "/"),
            "bundle_count": len(copied),
            "results": [{
                "title": title,
                "label": "pack",
                "success": True,
                "piece_dir": piece_dir.replace("\\", "/"),
                "product_type": "pd_bundle",
            }],
        }

    def create_library_bundle(self, piece_dirs, title="Art Bundle", concept="", auto_seo=True, mark_members=True):
        """Compose a theme bundle from existing catalog piece masters."""
        import shutil
        from PIL import Image

        paths = []
        for p in piece_dirs or []:
            p = (p or "").replace("/", os.sep)
            if p and os.path.isdir(p) and os.path.isfile(os.path.join(p, "master.png")):
                paths.append(os.path.abspath(p))
        if len(paths) < 2:
            return {"success": False, "error": "Need at least 2 valid artwork pieces with master.png"}

        stamp = time.strftime("%Y%m%d_%H%M%S")
        slug_base = re.sub(r"[^a-z0-9]+", "-", (title or "bundle").lower()).strip("-")[:40] or "bundle"
        run_name = f"library_bundle_{stamp}_{slug_base}"
        run_dir = os.path.join(RUNS_DIR, run_name)
        piece_slug = f"{slug_base}_bundle"
        piece_dir = os.path.join(run_dir, piece_slug)
        bundle_dir = os.path.join(piece_dir, "bundle")
        os.makedirs(bundle_dir, exist_ok=True)

        copied = []
        orientations = {"portrait": 0, "landscape": 0, "square": 0}
        for i, src_piece in enumerate(paths, 1):
            src_master = os.path.join(src_piece, "master.png")
            dest_name = f"{i:02d}_{os.path.basename(src_piece)}.png"
            dest = os.path.join(bundle_dir, dest_name)
            shutil.copy2(src_master, dest)
            orient = "portrait"
            try:
                with Image.open(dest) as im:
                    w, h = im.size
                    if abs(w - h) < max(w, h) * 0.05:
                        orient = "square"
                    elif w > h:
                        orient = "landscape"
                orientations[orient] = orientations.get(orient, 0) + 1
            except Exception:
                orientations["portrait"] += 1
            copied.append({
                "path": dest.replace("\\", "/"),
                "source": src_piece.replace("\\", "/"),
                "orientation": orient,
            })

        master_path = os.path.join(piece_dir, "master.png")
        shutil.copy2(copied[0]["path"].replace("/", os.sep), master_path)
        ensure_piece_master_watermark(piece_dir, force=True)

        dominant = max(orientations, key=orientations.get) if any(orientations.values()) else "portrait"
        settings = load_suite_settings()
        description = (
            (f"{concept.strip()}\n\n" if concept else "")
            + f"Digital download pack with {len(copied)} high-resolution art prints from Aethelgard Art Co. "
            + "Delivery via PDF guide + Google Drive folder. Personal use."
        )
        piece_meta = {
            "run_dir": run_dir.replace("\\", "/"),
            "title": title,
            "slug": piece_slug,
            "source_image": master_path.replace("\\", "/"),
            "product_type": "bundle",
            "bundle_dir": bundle_dir.replace("\\", "/"),
            "bundle_count": len(copied),
            "bundle_orientations": orientations,
            "bundle_sources": [c["source"] for c in copied],
            "orientation": dominant,
            "sizes": "native",
            "model": "library-bundle",
            "prompt": concept or f"Theme bundle: {title}",
            "upscale": 0,
            "price": price_for_product_type("bundle"),
            "quantity": str(settings.get("default_quantity", 999)),
            "seo": {
                "title": f"{title} — {len(copied)} Printable Wall Art Bundle",
                "tags": ["printable wall art", "digital art print", "gallery wall set", "art print bundle"],
                "description": description,
                "materials": ["Digital download", "PDF", "Printable wall art"],
            },
            "mockup_prefs": {
                "disabled_mockups": [],
                "selected_templates": [],
                "include_zoom_gif": False,
            },
            "skip_print_crops": True,
        }
        with open(os.path.join(piece_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(piece_meta, f, indent=2)
        with open(os.path.join(piece_dir, "listing.json"), "w", encoding="utf-8") as f:
            json.dump({
                "title": piece_meta["seo"]["title"],
                "tags": piece_meta["seo"]["tags"],
                "description": description,
                "materials": piece_meta["seo"]["materials"],
            }, f, indent=2)
        with open(os.path.join(piece_dir, "bundle_manifest.json"), "w", encoding="utf-8") as f:
            json.dump({
                "product_type": "bundle",
                "title": title,
                "count": len(copied),
                "files": copied,
                "concept": concept,
            }, f, indent=2, ensure_ascii=False)

        if mark_members:
            self._mark_bundle_members(paths)

        artwork_script = os.path.join(ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py")
        if os.path.isfile(artwork_script) and os.path.isfile(PYTHON_EXE):
            self.run_subprocess([PYTHON_EXE, artwork_script, "index", run_dir])

        seo_pack = None
        if auto_seo:
            try:
                from seo_pack import apply_seo_pack_to_piece, generate_seo_pack_for_piece
                seo_pack = generate_seo_pack_for_piece(piece_dir)
                apply_seo_pack_to_piece(piece_dir, seo_pack)
            except Exception as e:
                print(f"Library bundle SEO skipped: {e}")

        return {
            "success": True,
            "piece_dir": piece_dir.replace("\\", "/"),
            "bundle_count": len(copied),
            "needs_mockup_picker": True,
            "seo_pack": seo_pack,
        }

    def pd_bundle_autoplace(self, piece_dir, template_names):
        """Aspect-aware assign pack images into selected multi-frame templates."""
        sys.path.insert(0, MOCKUPS_DIR)
        import generate_mockups as gm

        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.exists(meta_path):
            return {"success": False, "error": "meta.json missing"}
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        templates_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
        with open(templates_path, "r", encoding="utf-8") as f:
            all_templates = json.load(f)
        by_name = {t.get("name"): t for t in all_templates}

        pool = [img["path"] for img in gm.list_bundle_images(piece_dir, max_count=500)]
        if not pool:
            return {"success": False, "error": "No bundle images found"}

        placements = meta.get("mockup_placements") or {}
        placed = []
        for name in template_names or []:
            t = by_name.get(name)
            if not t or not t.get("quads"):
                continue
            quads = [tuple(tuple(pt) for pt in q) for q in t["quads"]]
            paths = gm.assign_prints_to_quads(pool, quads)
            frames = []
            for p in paths:
                try:
                    if os.path.commonpath([os.path.abspath(p), os.path.abspath(piece_dir)]) == os.path.abspath(piece_dir):
                        rel = os.path.relpath(p, piece_dir).replace("\\", "/")
                    else:
                        rel = p.replace("\\", "/")
                except ValueError:
                    rel = p.replace("\\", "/")
                frames.append({"image": rel, "pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0})
            placements[name] = {"frames": frames}
            placed.append({"template": name, "frames": len(frames)})

        prefs = meta.get("mockup_prefs") or {}
        prefs["selected_templates"] = list(template_names or [])
        all_names = [t.get("name") for t in all_templates if t.get("name")]
        selected_set = set(template_names or [])
        prefs["disabled_mockups"] = [n for n in all_names if n not in selected_set]
        meta["mockup_prefs"] = prefs
        meta["mockup_placements"] = placements
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return {
            "success": True,
            "placed": placed,
            "selected_templates": list(template_names or []),
            "pool_count": len(pool),
        }

    def get_gemini_key(self):
        load_env_keys_into_os()
        return (os.environ.get("GEMINI_API_KEY") or "").strip() or None

    def get_ai_title_suggestions(self, concept, prompt_spine):
        key = self.get_gemini_key()
        if not key:
            return [
                f"{concept.title()} Wall Art, Botanical Specimen Print",
                f"Minimalist {concept.title()} Poster, Modern Japandi Decor",
                f"Moody {concept.title()} Oil Painting, Dark Academia Print"
            ]
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        
        # Deduce style name
        style = "vintage botanical"
        if "plaster" in prompt_spine or "japandi" in prompt_spine:
            style = "minimalist Japandi plaster texture"
        elif "academia" in prompt_spine or "gothic" in prompt_spine or "moody" in prompt_spine:
            style = "moody dark academia oil painting"
            
        prompt = (
            f"You are an Etsy SEO expert. Suggest 3 highly creative, optimized, and clickable product titles "
            f"(each strictly under 130 characters, separated by newlines, with no prefix numbering like '1.' or 'Title:') "
            f"for a digital wall art print listing on Etsy. "
            f"Subject: {concept}. Style/Niche: {style}. "
            f"Use high-converting keywords like 'Printable Wall Art, Vintage Digital Print Decor, Gallery Wall Set'."
        )
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        try:
            r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                lines = [line.strip().replace('"', '').strip() for line in text.split("\n") if line.strip()]
                cleaned_lines = []
                for line in lines:
                    cleaned = re.sub(r"^(\d+[\.\-\)]\s*|title\s*\d*:\s*)", "", line, flags=re.IGNORECASE).strip()
                    if cleaned:
                        cleaned_lines.append(cleaned[:130])
                if len(cleaned_lines) >= 3:
                    return cleaned_lines[:3]
        except Exception as e:
            print(f"Error getting title suggestions: {e}")
            
        return [
            f"{concept.title()} Wall Art, {style.title()} Digital Print",
            f"Minimalist {concept.title()} Poster, Aesthetic {style.title()} Decor",
            f"Textured {concept.title()} Artwork, Wabi-Sabi {style.title()} Print"
        ]

    def save_mockup_template(self, name, orientation, aspect, box, image_data, tags=None, quad=None, quads=None, layout=None, frame_count=None):
        import base64
        try:
            template_dir = os.path.join(ROOT_DIR, "tooling", "mockups", "templates")
            os.makedirs(template_dir, exist_ok=True)
            img_path = os.path.join(template_dir, f"{name}.png")
            
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(image_data))
                
            templates_json_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
            templates = []
            if os.path.exists(templates_json_path):
                try:
                    with open(templates_json_path, "r", encoding="utf-8") as f:
                        templates = json.load(f)
                except Exception:
                    templates = []
                    
            templates = [t for t in templates if t.get("name") != name]
            
            new_tpl = {
                "name": name,
                "image": f"templates/{name}.png",
                "orientation": orientation,
                "aspect": aspect,
                "box": box,
                "tags": tags or ["neutral"],
                "calibrated": True,
            }
            if quad:
                new_tpl["quad"] = quad
            if quads:
                new_tpl["quads"] = quads
            if layout:
                new_tpl["layout"] = layout
            if frame_count:
                new_tpl["frame_count"] = int(frame_count)
            elif quads:
                new_tpl["frame_count"] = len(quads)
                
            templates.append(new_tpl)
            
            with open(templates_json_path, "w", encoding="utf-8") as f:
                json.dump(templates, f, indent=2)
                
            return True
        except Exception as e:
            print(f"Error saving mockup template: {e}")
            return False

    def delete_mockup_template(self, name):
        try:
            templates_json_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates.json")
            templates = []
            if os.path.exists(templates_json_path):
                with open(templates_json_path, "r", encoding="utf-8") as f:
                    templates = json.load(f)
            templates = [t for t in templates if t.get("name") != name]
            with open(templates_json_path, "w", encoding="utf-8") as f:
                json.dump(templates, f, indent=2)
            img_path = os.path.join(ROOT_DIR, "tooling", "mockups", "templates", f"{name}.png")
            if os.path.exists(img_path):
                os.remove(img_path)
            return True
        except Exception as e:
            print(f"Error deleting mockup template: {e}")
            return False

    def save_mockup_prefs(
        self,
        piece_dir,
        disabled_mockups,
        include_zoom_gif=True,
        selected_templates=None,
        photo_order=None,
        extra_prefs=None,
    ):
        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            prefs = meta.get("mockup_prefs") or {}
            prefs["disabled_mockups"] = list(disabled_mockups or [])
            prefs["include_zoom_gif"] = bool(include_zoom_gif)
            if selected_templates is not None:
                prefs["selected_templates"] = list(selected_templates)
            if photo_order is not None:
                prefs["photo_order"] = [str(x) for x in photo_order if x]
            if isinstance(extra_prefs, dict):
                for k, v in extra_prefs.items():
                    if v is None:
                        continue
                    prefs[k] = v
            meta["mockup_prefs"] = prefs
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving mockup prefs: {e}")
            return False

    def load_mockup_placements(self, piece_dir, template_name=""):
        meta_path = os.path.join(piece_dir, "meta.json")
        all_placements = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                all_placements = meta.get("mockup_placements", {})
            except Exception:
                pass
        if template_name:
            return {
                "template": template_name,
                "frames": all_placements.get(template_name, {}).get("frames", []),
            }
        return {"placements": all_placements}

    def save_mockup_placements(self, piece_dir, template_name, frames):
        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if "mockup_placements" not in meta:
                meta["mockup_placements"] = {}
            meta["mockup_placements"][template_name] = {"frames": frames}
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving mockup placements: {e}")
            return False



    def delete_mockup(self, piece_dir, source):
        """Remove a mockup jpg and clean photo_order / placements / single_frame_sources."""
        src_name = os.path.basename(str(source)).replace('\\', '/')
        if not src_name.lower().startswith('mockup_'):
            if not src_name.lower().endswith(('.jpg', '.jpeg')):
                src_name = f"mockup_{src_name}.jpg"
        if src_name.lower() in ('master_wm.jpg', 'master_wm.jpeg'):
            return {"success": False, "error": "Use the checkbox to exclude the watermark — it is not a mockup file."}
        src_path = os.path.join(piece_dir, src_name)
        if not os.path.isfile(src_path):
            return {"success": False, "error": f"Mockup not found: {src_name}"}
        try:
            os.remove(src_path)
        except OSError as e:
            return {"success": False, "error": str(e)}
        stem = src_name[7:src_name.lower().rfind('.')]
        meta_path = os.path.join(piece_dir, 'meta.json')
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            placements = meta.get('mockup_placements') or {}
            placements.pop(stem, None)
            meta['mockup_placements'] = placements
            sources = meta.get('single_frame_sources') or {}
            sources.pop(stem, None)
            meta['single_frame_sources'] = sources
            prefs = meta.get('mockup_prefs') or {}
            order = [str(x) for x in (prefs.get('photo_order') or []) if x and x != src_name]
            prefs['photo_order'] = order
            disabled = [d for d in (prefs.get('disabled_mockups') or []) if d != src_name]
            prefs['disabled_mockups'] = disabled
            meta['mockup_prefs'] = prefs
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            return {"success": False, "error": f"Deleted file but failed meta cleanup: {e}", "fname": src_name}
        return {"success": True, "fname": src_name, "photo_order": prefs.get('photo_order') or []}

    def duplicate_mockup(self, piece_dir, source):
        """Copy a room mockup to mockup_{base}_rNN.jpg and clone placements/art sources."""
        from shutil import copy2
        src_name = os.path.basename(str(source)).replace('\\', '/')
        if src_name.lower().startswith('mockup_overview_'):
            return {"success": False, "error": "Overview grids cannot be duplicated — regenerate them instead."}
        if not src_name.lower().startswith('mockup_') or not src_name.lower().endswith(('.jpg', '.jpeg')):
            # allow bare stem
            if not src_name.lower().endswith(('.jpg', '.jpeg')):
                src_name = f"mockup_{src_name}.jpg"
        src_path = os.path.join(piece_dir, src_name)
        if not os.path.isfile(src_path):
            return {"success": False, "error": f"Mockup not found: {src_name}"}
        stem = src_name[7:src_name.lower().rfind('.')]
        # Resolve base template (strip existing _rNN)
        m = re.match(r'^(.*)_r(\d{2})$', stem, flags=re.IGNORECASE)
        base = m.group(1) if m else stem
        used = set()
        for f in os.listdir(piece_dir):
            low = f.lower()
            if not (low.startswith('mockup_') and low.endswith(('.jpg', '.jpeg'))):
                continue
            s = f[7:low.rfind('.')]
            mm = re.match(r'^' + re.escape(base) + r'_r(\d{2})$', s, flags=re.IGNORECASE)
            if mm:
                used.add(int(mm.group(1)))
        n = 1
        while n in used:
            n += 1
            if n > 99:
                return {"success": False, "error": "Too many duplicates for this mockup"}
        new_stem = f"{base}_r{n:02d}"
        new_name = f"mockup_{new_stem}.jpg"
        new_path = os.path.join(piece_dir, new_name)
        try:
            copy2(src_path, new_path)
        except Exception as e:
            return {"success": False, "error": str(e)}
        meta_path = os.path.join(piece_dir, 'meta.json')
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            placements = meta.get('mockup_placements') or {}
            sources = meta.get('single_frame_sources') or {}
            # Prefer exact source stem placements, else base
            src_pl = placements.get(stem) or placements.get(base)
            if src_pl:
                import copy as _copy
                placements[new_stem] = _copy.deepcopy(src_pl)
                meta['mockup_placements'] = placements
            src_art = sources.get(stem) or sources.get(base)
            if src_art:
                sources[new_stem] = src_art
                meta['single_frame_sources'] = sources
            prefs = meta.get('mockup_prefs') or {}
            order = [str(x) for x in (prefs.get('photo_order') or []) if x]
            if new_name not in order:
                # Insert after source if present, else append
                if src_name in order:
                    i = order.index(src_name)
                    order.insert(i + 1, new_name)
                else:
                    order.append(new_name)
            prefs['photo_order'] = order[:10]
            prefs['repeat_mockups'] = False
            meta['mockup_prefs'] = prefs
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            return {"success": False, "error": f"Copied file but failed meta update: {e}", "fname": new_name}
        rel = os.path.relpath(new_path, ROOT_DIR).replace('\\', '/')
        return {
            "success": True,
            "fname": new_name,
            "stem": new_stem,
            "base": base,
            "mockup_rel": rel,
            "photo_order": prefs.get('photo_order') or [],
        }

    def save_single_frame_source(self, piece_dir, template_name, image_ref, set_as_cover=False):
        """Remember which pack image fills a single-frame mockup; optionally update master.png."""
        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.exists(meta_path):
            return False, "meta.json missing"
        try:
            sys.path.insert(0, MOCKUPS_DIR)
            import generate_mockups as gm
            from shutil import copy2
            resolved = gm.resolve_print_path(piece_dir, image_ref)
            if not resolved or not os.path.isfile(resolved):
                return False, f"Image not found: {image_ref}"
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            # Store piece-relative path when possible
            try:
                store_ref = os.path.relpath(resolved, piece_dir).replace("\\", "/")
            except ValueError:
                store_ref = image_ref
            if template_name:
                sources = meta.get("single_frame_sources") or {}
                sources[template_name] = store_ref
                meta["single_frame_sources"] = sources
                # Also mirror into placements so Composer-style data stays consistent
                placements = meta.get("mockup_placements") or {}
                placements[template_name] = {
                    "frames": [{"image": store_ref, "pan_x": 0, "pan_y": 0, "zoom": 1}],
                }
                meta["mockup_placements"] = placements
            if set_as_cover:
                dest = os.path.join(piece_dir, "master.png")
                try:
                    from PIL import Image
                    with Image.open(resolved) as im:
                        im.convert("RGB").save(dest, "PNG")
                except Exception:
                    copy2(resolved, dest)
                meta["cover_image"] = store_ref
                ensure_piece_master_watermark(piece_dir, force=True)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            return True, None
        except Exception as e:
            print(f"Error saving single_frame_source: {e}")
            return False, str(e)

def start_server(port=8080):
    try:
        from factory.factory_routes import boot_factory
        boot_factory(load_suite_settings)
        print("Factory OS: job worker + SQLite store ready", flush=True)
    except Exception as e:
        print(f"Warning: factory boot failed: {e}", flush=True)
    try:
        from archive.routes import boot_archive
        boot_archive()
        print("Archive Studio: job worker + SQLite store ready", flush=True)
    except Exception as e:
        print(f"Warning: archive boot failed: {e}", flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', port), DashboardHandler)
    print("", flush=True)
    print("=" * 60, flush=True)
    print(f"Etsy Automated Pipeline Dashboard running at http://127.0.0.1:{port}", flush=True)
    print("Factory Dashboard is the live operational control centre.", flush=True)
    print("Press Ctrl+C to stop the server.", flush=True)
    print("=" * 60, flush=True)
    print("", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()

if __name__ == "__main__":
    port = 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    start_server(port)
