"""Exact and approximate duplicate detection."""
from __future__ import annotations

from io import BytesIO
from typing import List, Optional, Tuple

from . import store
from .log import log_event


def average_hash(data: bytes, hash_size: int = 16) -> str:
    from PIL import Image

    im = Image.open(BytesIO(data)).convert("L")
    im = im.resize((hash_size, hash_size))
    pixels = list(im.getdata())
    avg = sum(pixels) / max(1, len(pixels))
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return format(int(bits, 2), f"0{hash_size * hash_size // 4}x")


def hamming_hex(a: str, b: str) -> int:
    if not a or not b:
        return 64
    try:
        xa, xb = int(a, 16), int(b, 16)
    except ValueError:
        return 64
    return bin(xa ^ xb).count("1")


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def apply_hashes(asset_id: str, data: bytes) -> dict:
    sha = sha256_bytes(data)
    try:
        phash = average_hash(data)
    except Exception as e:
        phash = ""
        log_event("dedupe.phash_failed", level="warn", asset_id=asset_id, message=str(e))
    store.update_asset(asset_id, file_sha256=sha, perceptual_hash=phash, dedupe_hash=sha)
    return {"file_sha256": sha, "perceptual_hash": phash}


def find_duplicates(asset: dict, *, hamming_threshold: int = 8) -> List[dict]:
    hits = []
    sha = asset.get("file_sha256")
    if sha:
        for other in store.find_by_file_hash(sha, exclude_id=asset.get("id")):
            hits.append({**other, "match": "sha256"})
    phash = asset.get("perceptual_hash")
    if phash:
        for aid, other_hash in store.list_phashes(limit=4000):
            if aid == asset.get("id"):
                continue
            dist = hamming_hex(phash, other_hash)
            if dist <= hamming_threshold:
                other = store.get_asset(aid)
                if other:
                    hits.append({**other, "match": "phash", "distance": dist})
    # source identity
    if asset.get("source") and asset.get("source_object_id"):
        existing = store.get_asset_by_source(asset["source"], asset["source_object_id"])
        if existing and existing.get("id") != asset.get("id"):
            hits.append({**existing, "match": "source_id"})
    return hits


def mark_duplicate(asset_id: str, duplicate_of: str, *, flag: bool = True) -> Optional[dict]:
    flags = list((store.get_asset(asset_id) or {}).get("qc_flags") or [])
    if flag and "possible_duplicate" not in flags:
        flags.append("possible_duplicate")
    return store.update_asset(asset_id, duplicate_of=duplicate_of, qc_flags=flags)
