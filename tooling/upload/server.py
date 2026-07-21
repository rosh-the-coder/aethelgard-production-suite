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
MOCKUP_JOBS = {}
MOCKUP_JOBS_LOCK = threading.Lock()
LATEST_SHOP_CAPTURE = None
LATEST_SHOP_CAPTURE_LOCK = threading.Lock()
LATEST_LISTING_CAPTURE = None
LATEST_LISTING_CAPTURE_LOCK = threading.Lock()


def playwright_env():
    env = os.environ.copy()
    browsers = os.path.join(ROOT_DIR, "tooling", "ad-creatives", ".playwright-browsers")
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers)
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
        with open(ENV_FILE_PATH, "r", encoding="utf-8-sig") as f:
            for line in f:
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


def start_mockup_job(piece_dir):
    job_id = uuid.uuid4().hex[:10]
    initial = {
        "status": "running",
        "piece_dir": piece_dir,
        "started_at": time.time(),
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
        # Route dashboard home
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            dashboard_path = os.path.join(HERE, "dashboard.html")
            with open(dashboard_path, "rb") as f:
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
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "authenticated": exists,
                "auth_file": auth_path if exists else None,
            }).encode('utf-8'))
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

        # API: Etsy Keyword Research
        if self.path.startswith("/api/research"):
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
        if self.path.startswith("/api/analyze_shop"):
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

        # API: Saved research library
        if path == "/api/research_library":
            from research_library import list_items
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            category = (qs.get("category") or ["all"])[0]
            kind = (qs.get("kind") or ["all"])[0]
            q = (qs.get("q") or [""])[0]
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(list_items(category=category, kind=kind, q=q)).encode("utf-8"))
            return

        # API: Public-domain Met search
        if path == "/api/public_domain/search":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get("q") or [""])[0]
            limit = (qs.get("limit") or ["24"])[0]
            try:
                from public_domain import search_met
                results = search_met(q, limit=limit)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "results": results,
                    "count": len(results),
                    "source": "met_open_access",
                    "note": "Met Open Access only — verify before commercial use.",
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

            data = json.loads(post_data.decode("utf-8"))
            
            # API: Save metadata edits
            if path == "/api/save":
                piece_dir = data.get("piece_dir")
                title = data.get("title")
                description = data.get("description")
                tags = data.get("tags", [])
                price = data.get("price")
                quantity = data.get("quantity")
                
                success = self.save_metadata(piece_dir, title, description, tags, price, quantity)
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
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

                job_id = start_mockup_job(piece_dir)
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
                        f"{calibrated_count} calibrated template(s) will run; "
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

            # API: Trigger Etsy Upload
            if path == "/api/upload":
                piece_dir = data.get("piece_dir")
                success = False
                error = None
                if not piece_dir or not os.path.isdir(piece_dir):
                    error = "Invalid piece_dir"
                else:
                    try:
                        write_upload_status(piece_dir, "queued", "Upload console launching…")
                        cmd = f'start cmd /k "{PYTHON_EXE} {UPLOAD_SCRIPT} --upload \\"{piece_dir}\\""'
                        subprocess.Popen(cmd, shell=True)
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

            # API: Import public-domain Met objects as candidates
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
                    from public_domain import import_objects_to_run
                    run_dir, candidates, errors = import_objects_to_run(objects, RUNS_DIR, concept=concept)
                    for c in candidates:
                        full = c["path"].replace("/", os.sep)
                        c["rel_path"] = os.path.relpath(full, ROOT_DIR).replace("\\", "/")
                        c["path"] = full.replace("\\", "/")
                    titles = [
                        f"{(o.get('title') or 'Vintage Print')[:80]} Wall Art, Printable Vintage Decor"
                        for o in objects[:3]
                    ]
                    self.send_response(200 if candidates else 500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": bool(candidates),
                        "candidates": candidates,
                        "suggested_titles": titles,
                        "run_dir": run_dir.replace("\\", "/"),
                        "errors": errors,
                        "error": None if candidates else (errors[0]["error"] if errors else "Import failed"),
                    }).encode("utf-8"))
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
                        png_bytes = compose_poster(
                            raw_path,
                            headline=headline,
                            subtext=subtext,
                            aspect=aspect,
                            layout=layout,
                        )
                        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                        out_path = os.path.join(candidates_dir, f"{ts}_{label}-composed.png")
                        with open(out_path, "wb") as f:
                            f.write(png_bytes)
                        candidates.append({
                            "label": label,
                            "rel_path": os.path.relpath(out_path, ROOT_DIR).replace("\\", "/"),
                            "path": out_path.replace("\\", "/"),
                            "prompt": f"{visual} | headline={headline} | sub={subtext}",
                            "model": model,
                            "aspect": aspect,
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

            # API: Finalize Selected Winners
            if path == "/api/finalize_selected":
                run_dir = data.get("run_dir")
                keepers = data.get("keepers", [])
                trim_margin = float(data.get("trim_margin", 0))
                
                result = self.finalize_selected_keepers(run_dir, keepers, trim_margin)
                status = 200 if result.get("any_success") else 500
                self.send_response(status)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
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
                success = self.save_mockup_prefs(piece_dir, disabled, include_zoom)
                self.send_response(200 if success else 500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                return
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
        return filename[7:lower.rfind(".")]

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
                    
                    listing_path = os.path.join(piece_path, "listing.json")
                    listing = {}
                    if os.path.exists(listing_path):
                        with open(listing_path, "r", encoding="utf-8") as f:
                            listing = json.load(f)
                            
                    # Get list of mockups — only from calibrated templates
                    calibrated_names = self.get_calibrated_template_names()
                    all_mockup_files = sorted([
                        f for f in os.listdir(piece_path)
                        if f.lower().startswith("mockup_") and f.lower().endswith(".jpg")
                        and self.mockup_stem_from_filename(f) in calibrated_names
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
                    
                    run_data["pieces"].append({
                        "title": meta.get("title"),
                        "slug": meta.get("slug"),
                        "path": piece_path,
                        "orientation": meta.get("orientation"),
                        "sizes": meta.get("sizes", []),
                        "prompt": meta.get("prompt"),
                        "price": meta.get("price", "4.99"),
                        "quantity": meta.get("quantity", "999"),
                        "uploaded_at": meta.get("uploaded_at"),
                        "seo_title": listing.get("title", meta.get("seo", {}).get("title", "")),
                        "seo_tags": listing.get("tags", meta.get("seo", {}).get("tags", [])),
                        "seo_description": listing.get("description", meta.get("seo", {}).get("description", "")),
                        "master_image": rel_master,
                        "mockups": rel_mockups,
                        "all_mockups": rel_all_mockups,
                        "mockup_prefs": mockup_prefs,
                        "zoom_gif": rel_zoom,
                        "has_pdf": has_pdf,
                        "pdf_path": meta.get("pdf_path"),
                        "drive_link": meta.get("drive_link"),
                        "upload_status": upload_st,
                        "print_jpg_count": print_jpg_count,
                        "calibrated_mockup_count": len(all_mockup_files),
                        "quality_warnings": quality_warnings,
                    })
                except Exception as e:
                    print(f"Error reading piece {piece_name}: {e}")
                    
            if run_data["pieces"]:
                runs.append(run_data)
                
        return runs

    def save_metadata(self, piece_dir, title, description, tags, price, quantity):
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
            
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
                
            # Update listing.json / seo.md
            with open(listing_path, "w", encoding="utf-8") as f:
                json.dump({
                    "title": title,
                    "tags": tags,
                    "description": description
                }, f, indent=2)
                
            seo_md_path = os.path.join(piece_dir, "seo.md")
            with open(seo_md_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
                f.write(f"**Listing title**: {title}\n\n")
                f.write("**Tags**:\n")
                for t in tags:
                    f.write(f"- {t}\n")
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
        results = []
        
        for k in keepers:
            source_image = (k.get("source_image") or "").replace("/", os.sep)
            label = clean_win_text(k.get("label") or "art")
            title = clean_win_text(k.get("title") or f"Print {label}")
            piece_dir = None
            error_msg = None
            
            if not source_image or not os.path.exists(source_image):
                error_msg = f"Source image not found: {k.get('source_image')}"
                results.append({"title": title, "label": label, "success": False, "error": error_msg})
                continue

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
            
            tags = ["printable wall art", "digital art print", "wall decor"]
            description = "Welcome to Aethelgard Art Co.!\n\nThis is a high-resolution 300 DPI digital print ready for instant download and printing in over 20+ frame sizes.\n\nIncluded files are formatted for aspect ratios:\n- 4:5 (for sizes 4x5, 8x10, 16x20 inches)\n- 3:2 (for sizes 4x6, 6x9, 8x12, 12x18, 20x30 inches)\n- 11:14 paper size\n\nThank you for supporting our shop!"
            
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
                        description = f"Welcome to Aethelgard Art Co.!\n\nThis is a premium high-resolution 300 DPI digital print ready for instant download.\n\nStyle: {matched_niche.get('name')}\n\nDescription: {matched_niche.get('summary')}\n\nIncluded files are formatted for standard frame aspect ratios:\n- 4:5 ratio (for printing: 4x5\", 8x10\", 12x15\", 16x20\", 40x50cm)\n- 3:2 ratio (for printing: 4x6\", 6x9\", 8x12\", 12x18\", 20x30\", 24x36\", 60x90cm)\n- 11:14\" paper size\n\nThank you for choosing Aethelgard Art Co.!"
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
                "sizes": "all",
                "model": clean_win_text(k.get("model", "nano-banana-pro")),
                "prompt": clean_win_text(k.get("prompt", "")),
                "upscale": 4,
                "price": "5.99",
                "quantity": "999",
                "trim_margin": trim_margin,
                "seo": {
                    "title": f"{title} - Printable Wall Art, Vintage Digital Print Decor",
                    "tags": tags,
                    "description": description
                }
            }
            
            meta_json_path = os.path.join(piece_dir, "meta.json")
            with open(meta_json_path, "w", encoding="utf-8") as f:
                json.dump(piece_meta, f, indent=2)
                
            artwork_script = os.path.join(ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py")
            cmd_finalize = [PYTHON_EXE, artwork_script, "finalize", meta_json_path]
            res, stdout, stderr = self.run_subprocess(cmd_finalize)
            
            if res:
                default_prints = os.path.join(piece_dir, "prints")
                named_prints = os.path.join(piece_dir, f"{piece_slug}_prints")
                if os.path.exists(default_prints) and not os.path.exists(named_prints):
                    os.rename(default_prints, named_prints)
                
                self.run_subprocess([PYTHON_EXE, MOCKUPS_SCRIPT, piece_dir])
                results.append({
                    "title": title,
                    "label": label,
                    "success": True,
                    "piece_dir": piece_dir.replace("\\", "/"),
                })
            else:
                error_msg = stderr_tail(stderr) or stderr_tail(stdout) or "Finalize pipeline failed (check server console)."
                print(f"Finalize failed for {title}: {error_msg}")
                results.append({
                    "title": title,
                    "label": label,
                    "success": False,
                    "error": error_msg,
                    "piece_dir": piece_dir.replace("\\", "/"),
                })
                
        artwork_script = os.path.join(ROOT_DIR, ".claude", "skills", "artwork-orchestrator", "scripts", "artwork.py")
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

    def save_mockup_prefs(self, piece_dir, disabled_mockups, include_zoom_gif=True):
        meta_path = os.path.join(piece_dir, "meta.json")
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["mockup_prefs"] = {
                "disabled_mockups": list(disabled_mockups or []),
                "include_zoom_gif": bool(include_zoom_gif),
            }
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

def start_server(port=8080):
    server = ThreadingHTTPServer(('127.0.0.1', port), DashboardHandler)
    print(f"\n" + "="*60)
    print(f"Etsy Automated Pipeline Dashboard running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop the server.")
    print("="*60 + "\n")
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
