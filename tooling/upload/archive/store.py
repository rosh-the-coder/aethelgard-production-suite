"""SQLite store for Archive Studio assets, collections, jobs, and rules.

Kept separate from factory `.factory/jobs.sqlite3` so existing production
jobs and Art Studio runs are never touched.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .paths import DB_PATH, SETTINGS_PATH, DEFAULT_DRIVE_FOLDERS, ensure_archive_dirs
from .schema import NormalizedRecord, classify_orientation

_LOCK = threading.RLock()
_INIT = False

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    source_url TEXT,
    source_image_url TEXT,
    thumbnail_url TEXT,
    title TEXT,
    artist TEXT,
    year TEXT,
    date_display TEXT,
    description TEXT,
    rights_status TEXT,
    licence_type TEXT,
    is_public_domain INTEGER NOT NULL DEFAULT 0,
    media_type TEXT,
    medium TEXT,
    width INTEGER,
    height INTEGER,
    orientation TEXT,
    categories_json TEXT,
    tags_json TEXT,
    theme TEXT,
    ingested_at REAL NOT NULL,
    import_batch_id TEXT,
    local_thumb_path TEXT,
    local_file_path TEXT,
    drive_path TEXT,
    drive_file_id TEXT,
    processing_status TEXT,
    mockup_status TEXT,
    seo_status TEXT,
    listing_status TEXT,
    drive_status TEXT,
    dedupe_hash TEXT,
    perceptual_hash TEXT,
    file_sha256 TEXT,
    qc_flags_json TEXT,
    extra_json TEXT,
    duplicate_of TEXT,
    allow_duplicate INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source, source_object_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_source ON assets(source);
CREATE INDEX IF NOT EXISTS idx_assets_rights ON assets(rights_status);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(processing_status);
CREATE INDEX IF NOT EXISTS idx_assets_hash ON assets(file_sha256);
CREATE INDEX IF NOT EXISTS idx_assets_phash ON assets(perceptual_hash);
CREATE INDEX IF NOT EXISTS idx_assets_ingested ON assets(ingested_at);
CREATE INDEX IF NOT EXISTS idx_assets_title ON assets(title);

CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT,
    description TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    drive_folder TEXT,
    meta_json TEXT
);

CREATE TABLE IF NOT EXISTS collection_assets (
    collection_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    added_at REAL NOT NULL,
    PRIMARY KEY (collection_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_col_assets_asset ON collection_assets(asset_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    payload_json TEXT,
    cursor_json TEXT,
    result_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS job_items (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    asset_id TEXT,
    status TEXT NOT NULL,
    message TEXT,
    error TEXT,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_items_job ON job_items(job_id);

CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    query TEXT,
    sources_json TEXT,
    filters_json TEXT,
    actions_json TEXT,
    last_run_at REAL,
    last_result_json TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    job_id TEXT,
    asset_id TEXT,
    source TEXT,
    message TEXT,
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
"""


def _connect() -> sqlite3.Connection:
    ensure_archive_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    with _LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    global _INIT
    with db() as conn:
        conn.executescript(SCHEMA_SQL)
    _INIT = True


def ensure_init() -> None:
    if not _INIT:
        init_db()


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_load(text: Any, default: Any = None):
    if default is None:
        default = []
    if not text:
        return default
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except Exception:
        return default


def _row_to_asset(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["is_public_domain"] = bool(d.get("is_public_domain"))
    d["allow_duplicate"] = bool(d.get("allow_duplicate"))
    d["categories"] = _json_load(d.pop("categories_json", None), [])
    d["tags"] = _json_load(d.pop("tags_json", None), [])
    d["qc_flags"] = _json_load(d.pop("qc_flags_json", None), [])
    d["extra"] = _json_load(d.pop("extra_json", None), {})
    return d


def _row_to_job(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["payload"] = _json_load(d.pop("payload_json", None), {})
    d["cursor"] = _json_load(d.pop("cursor_json", None), {})
    d["result"] = _json_load(d.pop("result_json", None), {})
    return d


def _row_to_rule(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["enabled"] = bool(d.get("enabled"))
    d["sources"] = _json_load(d.pop("sources_json", None), [])
    d["filters"] = _json_load(d.pop("filters_json", None), {})
    d["actions"] = _json_load(d.pop("actions_json", None), [])
    d["last_result"] = _json_load(d.pop("last_result_json", None), {})
    return d


def _row_to_collection(row: Optional[sqlite3.Row], *, asset_count: int = 0) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["meta"] = _json_load(d.pop("meta_json", None), {})
    d["asset_count"] = asset_count
    return d


def load_settings() -> Dict[str, Any]:
    ensure_archive_dirs()
    settings = {
        "drive_folders": dict(DEFAULT_DRIVE_FOLDERS),
        "min_width": 1200,
        "min_height": 1200,
        "default_rights": ["public_domain", "cc0"],
        "search_page_size": 48,
        "download_concurrency": 3,
    }
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                folders = disk.get("drive_folders")
                if isinstance(folders, dict):
                    settings["drive_folders"].update({k: str(v) for k, v in folders.items() if v})
                for key in ("min_width", "min_height", "search_page_size", "download_concurrency"):
                    if disk.get(key) is not None:
                        settings[key] = int(disk[key])
                if isinstance(disk.get("default_rights"), list):
                    settings["default_rights"] = [str(x) for x in disk["default_rights"]]
        except Exception:
            pass
    return settings


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = load_settings()
    if isinstance(patch.get("drive_folders"), dict):
        current["drive_folders"].update({k: str(v) for k, v in patch["drive_folders"].items() if v})
    for key in ("min_width", "min_height", "search_page_size", "download_concurrency"):
        if patch.get(key) is not None:
            current[key] = int(patch[key])
    if isinstance(patch.get("default_rights"), list):
        current["default_rights"] = [str(x) for x in patch["default_rights"]]
    ensure_archive_dirs()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return current


def new_id(prefix: str = "a") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def upsert_record(
    record: NormalizedRecord,
    *,
    import_batch_id: Optional[str] = None,
    allow_duplicate: bool = False,
) -> Tuple[Dict[str, Any], bool]:
    """Insert or refresh a metadata record. Returns (asset, created)."""
    ensure_init()
    existing = get_asset_by_source(record.source, record.source_object_id)
    now = time.time()
    orientation = record.orientation or classify_orientation(record.width, record.height)
    if existing and not allow_duplicate:
        aid = existing["id"]
        with db() as conn:
            conn.execute(
                """
                UPDATE assets SET
                    source_url=?, source_image_url=?, thumbnail_url=?,
                    title=?, artist=?, year=?, date_display=?, description=?,
                    rights_status=?, licence_type=?, is_public_domain=?,
                    media_type=?, medium=?, width=COALESCE(?, width), height=COALESCE(?, height),
                    orientation=CASE WHEN ? != 'unknown' THEN ? ELSE orientation END,
                    categories_json=?, tags_json=?, extra_json=?
                WHERE id=?
                """,
                (
                    record.source_url or existing.get("source_url"),
                    record.source_image_url or existing.get("source_image_url"),
                    record.thumbnail_url or existing.get("thumbnail_url"),
                    record.title or existing.get("title"),
                    record.artist or existing.get("artist"),
                    record.year or existing.get("year"),
                    record.date_display or existing.get("date_display"),
                    record.description or existing.get("description"),
                    record.rights_status or existing.get("rights_status"),
                    record.licence_type or existing.get("licence_type"),
                    1 if record.is_public_domain else 0,
                    record.media_type or existing.get("media_type"),
                    record.medium or existing.get("medium"),
                    record.width,
                    record.height,
                    orientation,
                    orientation,
                    _json_dump(record.categories or existing.get("categories")),
                    _json_dump(record.tags or existing.get("tags")),
                    _json_dump({**(existing.get("extra") or {}), **(record.extra or {})}),
                    aid,
                ),
            )
        return get_asset(aid), False

    aid = new_id("ast")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO assets (
                id, source, source_object_id, source_url, source_image_url, thumbnail_url,
                title, artist, year, date_display, description, rights_status, licence_type,
                is_public_domain, media_type, medium, width, height, orientation,
                categories_json, tags_json, theme, ingested_at, import_batch_id,
                processing_status, mockup_status, seo_status, listing_status, drive_status,
                qc_flags_json, extra_json, allow_duplicate
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                aid,
                record.source,
                str(record.source_object_id),
                record.source_url,
                record.source_image_url,
                record.thumbnail_url,
                record.title,
                record.artist,
                record.year,
                record.date_display,
                record.description,
                record.rights_status,
                record.licence_type,
                1 if record.is_public_domain else 0,
                record.media_type,
                record.medium,
                record.width,
                record.height,
                orientation,
                _json_dump(record.categories),
                _json_dump(record.tags),
                record.theme,
                now,
                import_batch_id,
                "metadata",
                "pending",
                "pending",
                "pending",
                "pending",
                _json_dump([]),
                _json_dump(record.extra),
                1 if allow_duplicate else 0,
            ),
        )
    return get_asset(aid), True


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    asset = _row_to_asset(row)
    if asset:
        asset["collections"] = list_asset_collection_ids(asset_id)
    return asset


def get_asset_by_source(source: str, source_object_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM assets WHERE source=? AND source_object_id=?",
            (source, str(source_object_id)),
        ).fetchone()
    return _row_to_asset(row)


def update_asset(asset_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    ensure_init()
    allowed = {
        "source_url", "source_image_url", "thumbnail_url", "title", "artist", "year",
        "date_display", "description", "rights_status", "licence_type", "is_public_domain",
        "media_type", "medium", "width", "height", "orientation", "theme",
        "import_batch_id", "local_thumb_path", "local_file_path", "drive_path",
        "drive_file_id", "processing_status", "mockup_status", "seo_status",
        "listing_status", "drive_status", "dedupe_hash", "perceptual_hash",
        "file_sha256", "duplicate_of", "allow_duplicate",
    }
    json_fields = {
        "categories": "categories_json",
        "tags": "tags_json",
        "qc_flags": "qc_flags_json",
        "extra": "extra_json",
    }
    sets = []
    values: List[Any] = []
    for key, value in fields.items():
        if key in json_fields:
            sets.append(f"{json_fields[key]}=?")
            values.append(_json_dump(value))
        elif key in allowed:
            if key in ("is_public_domain", "allow_duplicate"):
                value = 1 if value else 0
            sets.append(f"{key}=?")
            values.append(value)
    if not sets:
        return get_asset(asset_id)
    values.append(asset_id)
    with db() as conn:
        conn.execute(f"UPDATE assets SET {', '.join(sets)} WHERE id=?", values)
    return get_asset(asset_id)


def delete_assets(asset_ids: Sequence[str]) -> int:
    ensure_init()
    ids = [str(a) for a in asset_ids if a]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with db() as conn:
        conn.execute(f"DELETE FROM collection_assets WHERE asset_id IN ({placeholders})", ids)
        cur = conn.execute(f"DELETE FROM assets WHERE id IN ({placeholders})", ids)
        return cur.rowcount or 0


def list_assets(
    *,
    q: str = "",
    source: str = "",
    sources: Optional[Sequence[str]] = None,
    rights: Optional[Sequence[str]] = None,
    orientation: str = "",
    processing_status: str = "",
    collection_id: str = "",
    has_fullres: Optional[bool] = None,
    has_image: Optional[bool] = None,
    min_width: Optional[int] = None,
    qc_flag: str = "",
    tags: Optional[Sequence[str]] = None,
    limit: int = 48,
    offset: int = 0,
) -> Dict[str, Any]:
    ensure_init()
    where = ["1=1"]
    args: List[Any] = []
    if q:
        where.append("(title LIKE ? OR artist LIKE ? OR description LIKE ? OR source_object_id LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like, like, like])
    if source:
        where.append("source=?")
        args.append(source)
    if sources:
        placeholders = ",".join("?" * len(sources))
        where.append(f"source IN ({placeholders})")
        args.extend(list(sources))
    if rights:
        placeholders = ",".join("?" * len(rights))
        where.append(f"rights_status IN ({placeholders})")
        args.extend(list(rights))
    if orientation:
        where.append("orientation=?")
        args.append(orientation)
    if processing_status:
        where.append("processing_status=?")
        args.append(processing_status)
    if has_fullres is True:
        where.append("local_file_path IS NOT NULL AND local_file_path != ''")
    elif has_fullres is False:
        where.append("(local_file_path IS NULL OR local_file_path = '')")
    if has_image is True:
        where.append("(source_image_url IS NOT NULL AND source_image_url != '')")
    elif has_image is False:
        where.append("(source_image_url IS NULL OR source_image_url = '')")
    if min_width:
        where.append("COALESCE(width,0) >= ?")
        args.append(int(min_width))
    if qc_flag:
        where.append("qc_flags_json LIKE ?")
        args.append(f"%{qc_flag}%")
    if tags:
        for tag in tags:
            where.append("tags_json LIKE ?")
            args.append(f"%{tag}%")
    join = ""
    if collection_id:
        join = "INNER JOIN collection_assets ca ON ca.asset_id = assets.id"
        where.append("ca.collection_id=?")
        args.append(collection_id)
    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit or 48), 200))
    offset = max(0, int(offset or 0))
    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM assets {join} WHERE {where_sql}",
            args,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT assets.* FROM assets {join} WHERE {where_sql} ORDER BY ingested_at DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    items = [_row_to_asset(r) for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def stats() -> Dict[str, Any]:
    ensure_init()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        fullres = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE local_file_path IS NOT NULL AND local_file_path != ''"
        ).fetchone()[0]
        pd = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE rights_status IN ('public_domain','cc0')"
        ).fetchone()[0]
        flagged = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE qc_flags_json IS NOT NULL AND qc_flags_json != '[]'"
        ).fetchone()[0]
        by_source = {
            r["source"]: r["n"]
            for r in conn.execute("SELECT source, COUNT(*) AS n FROM assets GROUP BY source").fetchall()
        }
        by_status = {
            r["processing_status"]: r["n"]
            for r in conn.execute(
                "SELECT processing_status, COUNT(*) AS n FROM assets GROUP BY processing_status"
            ).fetchall()
        }
        collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
        ).fetchone()[0]
    return {
        "assets": total,
        "fullres": fullres,
        "clear_rights": pd,
        "flagged": flagged,
        "collections": collections,
        "active_jobs": queued,
        "by_source": by_source,
        "by_status": by_status,
    }


def find_by_file_hash(sha256: str, exclude_id: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_init()
    if not sha256:
        return []
    sql = "SELECT * FROM assets WHERE file_sha256=?"
    args: List[Any] = [sha256]
    if exclude_id:
        sql += " AND id!=?"
        args.append(exclude_id)
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_asset(r) for r in rows]


def find_by_phash(phash: str, exclude_id: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_init()
    if not phash:
        return []
    sql = "SELECT * FROM assets WHERE perceptual_hash=?"
    args: List[Any] = [phash]
    if exclude_id:
        sql += " AND id!=?"
        args.append(exclude_id)
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_asset(r) for r in rows]


def list_phashes(limit: int = 5000) -> List[Tuple[str, str]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, perceptual_hash FROM assets WHERE perceptual_hash IS NOT NULL AND perceptual_hash != '' LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [(r["id"], r["perceptual_hash"]) for r in rows]


# --- collections ---

def create_collection(name: str, *, description: str = "", drive_folder: str = "") -> Dict[str, Any]:
    ensure_init()
    cid = new_id("col")
    now = time.time()
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in (name or "collection")).strip("-")[:60]
    with db() as conn:
        conn.execute(
            """
            INSERT INTO collections (id, name, slug, description, created_at, updated_at, drive_folder, meta_json)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (cid, name.strip() or "Untitled", slug, description, now, now, drive_folder, "{}"),
        )
    return get_collection(cid)


def get_collection(collection_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM collection_assets WHERE collection_id=?",
            (collection_id,),
        ).fetchone()[0]
    return _row_to_collection(row, asset_count=count)


def list_collections() -> List[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute("SELECT * FROM collections ORDER BY updated_at DESC").fetchall()
        counts = {
            r["collection_id"]: r["n"]
            for r in conn.execute(
                "SELECT collection_id, COUNT(*) AS n FROM collection_assets GROUP BY collection_id"
            ).fetchall()
        }
    return [_row_to_collection(r, asset_count=counts.get(r["id"], 0)) for r in rows]


def update_collection(collection_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    ensure_init()
    allowed = {"name", "description", "drive_folder", "slug"}
    sets = ["updated_at=?"]
    values: List[Any] = [time.time()]
    for key, value in fields.items():
        if key == "meta":
            sets.append("meta_json=?")
            values.append(_json_dump(value))
        elif key in allowed:
            sets.append(f"{key}=?")
            values.append(value)
    values.append(collection_id)
    with db() as conn:
        conn.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id=?", values)
    return get_collection(collection_id)


def delete_collection(collection_id: str) -> bool:
    ensure_init()
    with db() as conn:
        conn.execute("DELETE FROM collection_assets WHERE collection_id=?", (collection_id,))
        cur = conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
        return bool(cur.rowcount)


def add_assets_to_collection(collection_id: str, asset_ids: Sequence[str]) -> int:
    ensure_init()
    now = time.time()
    added = 0
    with db() as conn:
        for aid in asset_ids:
            if not aid:
                continue
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO collection_assets (collection_id, asset_id, added_at) VALUES (?,?,?)",
                    (collection_id, aid, now),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
        conn.execute("UPDATE collections SET updated_at=? WHERE id=?", (now, collection_id))
    return added


def remove_assets_from_collection(collection_id: str, asset_ids: Sequence[str]) -> int:
    ensure_init()
    ids = [str(a) for a in asset_ids if a]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with db() as conn:
        cur = conn.execute(
            f"DELETE FROM collection_assets WHERE collection_id=? AND asset_id IN ({placeholders})",
            [collection_id, *ids],
        )
        conn.execute("UPDATE collections SET updated_at=? WHERE id=?", (time.time(), collection_id))
        return cur.rowcount or 0


def list_asset_collection_ids(asset_id: str) -> List[str]:
    ensure_init()
    with db() as conn:
        rows = conn.execute(
            "SELECT collection_id FROM collection_assets WHERE asset_id=?",
            (asset_id,),
        ).fetchall()
    return [r["collection_id"] for r in rows]


# --- jobs ---

def create_job(kind: str, payload: Optional[Dict[str, Any]] = None, *, total: int = 0) -> Dict[str, Any]:
    ensure_init()
    jid = new_id("job")
    now = time.time()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, kind, status, created_at, updated_at, total, done, failed, payload_json, cursor_json, result_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (jid, kind, "queued", now, now, int(total or 0), 0, 0, _json_dump(payload or {}), "{}", "{}"),
        )
    return get_job(jid)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        items = conn.execute(
            "SELECT * FROM job_items WHERE job_id=? ORDER BY updated_at DESC LIMIT 80",
            (job_id,),
        ).fetchall()
    job = _row_to_job(row)
    if job:
        job["items"] = [dict(r) for r in items]
        job["percentage"] = 0
        if job.get("total"):
            job["percentage"] = round(100.0 * (job.get("done") or 0) / max(1, job["total"]), 1)
    return job


def list_jobs(limit: int = 80) -> List[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    out = []
    for row in rows:
        job = _row_to_job(row)
        if job.get("total"):
            job["percentage"] = round(100.0 * (job.get("done") or 0) / max(1, job["total"]), 1)
        else:
            job["percentage"] = 0
        out.append(job)
    return out


def claim_next_job() -> Optional[Dict[str, Any]]:
    ensure_init()
    now = time.time()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','retry') ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE jobs SET status=?, started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?",
            ("running", now, now, row["id"]),
        )
    return get_job(row["id"])


def update_job(job_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    ensure_init()
    allowed = {
        "status", "total", "done", "failed", "message", "error",
        "started_at", "completed_at",
    }
    sets = ["updated_at=?"]
    values: List[Any] = [time.time()]
    for key, value in fields.items():
        if key in ("payload", "cursor", "result"):
            sets.append(f"{key}_json=?")
            values.append(_json_dump(value))
        elif key in allowed:
            sets.append(f"{key}=?")
            values.append(value)
    values.append(job_id)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)
    return get_job(job_id)


def add_job_item(job_id: str, *, asset_id: Optional[str] = None, status: str = "ok", message: str = "", error: str = "") -> None:
    ensure_init()
    with db() as conn:
        conn.execute(
            "INSERT INTO job_items (id, job_id, asset_id, status, message, error, updated_at) VALUES (?,?,?,?,?,?,?)",
            (new_id("ji"), job_id, asset_id, status, message, error, time.time()),
        )


def bump_job(job_id: str, *, ok: bool = True, message: str = "", total: Optional[int] = None) -> None:
    ensure_init()
    with db() as conn:
        if ok:
            conn.execute(
                "UPDATE jobs SET done=done+1, updated_at=?, message=COALESCE(?, message) WHERE id=?",
                (time.time(), message or None, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET failed=failed+1, updated_at=?, message=COALESCE(?, message) WHERE id=?",
                (time.time(), message or None, job_id),
            )
        if total is not None:
            conn.execute("UPDATE jobs SET total=? WHERE id=?", (int(total), job_id))


# --- rules ---

def create_rule(data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_init()
    rid = new_id("rule")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO rules (id, name, enabled, created_at, query, sources_json, filters_json, actions_json)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                (data.get("name") or "Untitled rule").strip(),
                1 if data.get("enabled", True) else 0,
                time.time(),
                data.get("query") or "",
                _json_dump(data.get("sources") or []),
                _json_dump(data.get("filters") or {}),
                _json_dump(data.get("actions") or []),
            ),
        )
    return get_rule(rid)


def get_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
    return _row_to_rule(row)


def list_rules() -> List[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute("SELECT * FROM rules ORDER BY created_at DESC").fetchall()
    return [_row_to_rule(r) for r in rows]


def update_rule(rule_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ensure_init()
    sets = []
    values: List[Any] = []
    mapping = {
        "name": "name",
        "query": "query",
        "enabled": "enabled",
        "sources": "sources_json",
        "filters": "filters_json",
        "actions": "actions_json",
        "last_run_at": "last_run_at",
        "last_result": "last_result_json",
    }
    for key, col in mapping.items():
        if key not in data:
            continue
        value = data[key]
        if key == "enabled":
            value = 1 if value else 0
        if key in ("sources", "filters", "actions", "last_result"):
            value = _json_dump(value)
        sets.append(f"{col}=?")
        values.append(value)
    if not sets:
        return get_rule(rule_id)
    values.append(rule_id)
    with db() as conn:
        conn.execute(f"UPDATE rules SET {', '.join(sets)} WHERE id=?", values)
    return get_rule(rule_id)


def delete_rule(rule_id: str) -> bool:
    ensure_init()
    with db() as conn:
        cur = conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        return bool(cur.rowcount)


def insert_log(payload: Dict[str, Any]) -> None:
    ensure_init()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO logs (ts, level, event, job_id, asset_id, source, message, detail_json)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                payload.get("ts") or time.time(),
                payload.get("level") or "info",
                payload.get("event") or "",
                payload.get("job_id"),
                payload.get("asset_id"),
                payload.get("source"),
                payload.get("message") or "",
                _json_dump(payload.get("detail") or {}),
            ),
        )


def list_logs(limit: int = 120) -> List[Dict[str, Any]]:
    ensure_init()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["detail"] = _json_load(d.pop("detail_json", None), {})
        out.append(d)
    return out
