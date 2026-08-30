"""Filesystem paths for Archive Studio. Isolated from factory / Art Studio data."""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.dirname(HERE)
ROOT_DIR = os.path.abspath(os.path.join(UPLOAD_DIR, "..", ".."))
RUNS_DIR = os.path.join(ROOT_DIR, "tooling", "digital-product-research", "artwork-runs")

ARCHIVE_DATA_DIR = os.path.join(UPLOAD_DIR, ".archive")
FILES_DIR = os.path.join(ARCHIVE_DATA_DIR, "files")
THUMBS_DIR = os.path.join(ARCHIVE_DATA_DIR, "thumbs")
CACHE_DIR = os.path.join(ARCHIVE_DATA_DIR, "cache")
DB_PATH = os.path.join(ARCHIVE_DATA_DIR, "archive.sqlite3")
LOG_PATH = os.path.join(ARCHIVE_DATA_DIR, "archive.jsonl")
SETTINGS_PATH = os.path.join(ARCHIVE_DATA_DIR, "settings.json")
ENV_FILE = os.path.expanduser("~/.config/ai-images/env")

DEFAULT_DRIVE_FOLDERS = {
    "source_archive": "Aethelgard/Source Archive",
    "processed": "Aethelgard/Processed Assets",
    "mockups": "Aethelgard/Mockups",
    "seo": "Aethelgard/SEO",
    "listings": "Aethelgard/Listing Packages",
}


def ensure_archive_dirs() -> bool:
    """Create archive data dirs. Returns False if the drive is briefly unavailable."""
    try:
        for path in (ARCHIVE_DATA_DIR, FILES_DIR, THUMBS_DIR, CACHE_DIR):
            os.makedirs(path, exist_ok=True)
        return True
    except OSError as e:
        print(f"archive: could not ensure dirs ({e})", flush=True)
        return False


def read_env(name: str) -> str:
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


def safe_id(value: str, label: str = "id") -> str:
    text = str(value or "").strip()
    if not text or ".." in text or "/" in text or "\\" in text:
        raise ValueError(f"Invalid {label}")
    for ch in text:
        if not (ch.isalnum() or ch in "-_."):
            raise ValueError(f"Invalid {label}")
    return text


def resolve_under(base: str, *parts: str) -> str:
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if not target.startswith(base_abs + os.sep) and target != base_abs:
        raise ValueError("Path escapes base directory")
    return target
