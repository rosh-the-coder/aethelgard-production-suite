"""Public-domain image prep: measure aspect, trim museum mats/borders, no force-resize."""
from __future__ import annotations

import json
import os
from io import BytesIO

from PIL import Image, ImageStat


def classify_aspect(width, height):
    """Return aspect ratio string + orientation label from pixel size."""
    if height <= 0 or width <= 0:
        return "4:5", "portrait", 0.8
    ratio = width / float(height)
    if 0.92 <= ratio <= 1.08:
        return "1:1", "square", ratio
    if ratio >= 1.08:
        # landscape families
        if abs(ratio - 3 / 2) <= abs(ratio - 16 / 9):
            return "3:2", "landscape", ratio
        return "16:9", "landscape", ratio
    # portrait
    if abs(ratio - 4 / 5) <= abs(ratio - 2 / 3):
        return "4:5", "portrait", ratio
    return "2:3", "portrait", ratio


def _edge_band_is_uniform(im, side, max_frac=0.12, std_thresh=12.0, mean_hi=245, mean_lo=25):
    """Detect a near-solid border (mat/white/black) along one edge."""
    w, h = im.size
    gray = im.convert("L")
    if side == "top":
        band_h = max(1, int(h * max_frac))
        crop = gray.crop((0, 0, w, band_h))
    elif side == "bottom":
        band_h = max(1, int(h * max_frac))
        crop = gray.crop((0, h - band_h, w, h))
    elif side == "left":
        band_w = max(1, int(w * max_frac))
        crop = gray.crop((0, 0, band_w, h))
    else:
        band_w = max(1, int(w * max_frac))
        crop = gray.crop((w - band_w, 0, w, h))
    stats = ImageStat.Stat(crop)
    mean = stats.mean[0]
    std = stats.stddev[0]
    # Uniform light mat or dark frame edge
    if std > std_thresh:
        return False, 0
    if mean >= mean_hi or mean <= mean_lo or std < 6:
        # return how many pixels to trim by scanning inward for content jump
        return True, _measure_trim(gray, side)
    return False, 0


def _measure_trim(gray, side, max_frac=0.18, jump=18):
    w, h = gray.size
    px = gray.load()
    if side in ("top", "bottom"):
        limit = max(1, int(h * max_frac))
        rows = range(limit) if side == "top" else range(h - 1, h - 1 - limit, -1)
        edge_vals = []
        for y in list(rows)[:3]:
            row = [px[x, y] for x in range(0, w, max(1, w // 40))]
            edge_vals.append(sum(row) / len(row))
        edge_mean = sum(edge_vals) / max(1, len(edge_vals))
        trim = 0
        seq = range(limit) if side == "top" else range(h - 1, h - 1 - limit, -1)
        for i, y in enumerate(seq):
            row = [px[x, y] for x in range(0, w, max(1, w // 40))]
            m = sum(row) / len(row)
            if abs(m - edge_mean) >= jump:
                trim = i
                break
            trim = i + 1
        return min(trim, limit)
    limit = max(1, int(w * max_frac))
    cols = range(limit) if side == "left" else range(w - 1, w - 1 - limit, -1)
    edge_vals = []
    for x in list(cols)[:3]:
        col = [px[x, y] for y in range(0, h, max(1, h // 40))]
        edge_vals.append(sum(col) / len(col))
    edge_mean = sum(edge_vals) / max(1, len(edge_vals))
    trim = 0
    seq = range(limit) if side == "left" else range(w - 1, w - 1 - limit, -1)
    for i, x in enumerate(seq):
        col = [px[x, y] for y in range(0, h, max(1, h // 40))]
        m = sum(col) / len(col)
        if abs(m - edge_mean) >= jump:
            trim = i
            break
        trim = i + 1
    return min(trim, limit)


def smart_trim_borders(im, enabled=True):
    """
    Conservatively crop uniform mats/borders. Never changes aspect via forced resize —
    only removes detected edge bands. Returns (image, trim_box or None).
    """
    if not enabled:
        return im, None
    im = im.convert("RGB")
    w, h = im.size
    if w < 64 or h < 64:
        return im, None

    trims = {}
    for side in ("top", "bottom", "left", "right"):
        ok, amount = _edge_band_is_uniform(im, side)
        trims[side] = amount if ok else 0

    # Require at least two opposite or adjacent sides to avoid eating painted edges
    active = sum(1 for v in trims.values() if v > 2)
    if active < 2:
        return im, None

    left = trims["left"]
    top = trims["top"]
    right = w - trims["right"]
    bottom = h - trims["bottom"]
    if right - left < w * 0.55 or bottom - top < h * 0.55:
        return im, None
    box = (left, top, right, bottom)
    return im.crop(box), box


def prep_image_file(src_path, dest_path, trim_borders=True, min_long_edge_upscale=2000):
    """
    Load image, smart-trim borders, optionally upscale tiny images, save PNG.
    Preserves native aspect (no center-crop to print ratios).
    Returns prep metadata dict.
    """
    with Image.open(src_path) as im0:
        im = im0.convert("RGB")
        orig_size = im.size
        im, trim_box = smart_trim_borders(im, enabled=trim_borders)
        w, h = im.size
        aspect, orientation, ratio = classify_aspect(w, h)

        upscaled = False
        long_edge = max(w, h)
        if long_edge < min_long_edge_upscale and long_edge > 0:
            scale = min_long_edge_upscale / float(long_edge)
            # Cap aggressive upscale
            scale = min(scale, 3.0)
            nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
            im = im.resize((nw, nh), Image.LANCZOS)
            w, h = im.size
            upscaled = True
            aspect, orientation, ratio = classify_aspect(w, h)

        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        im.save(dest_path, format="PNG", optimize=True)

    meta = {
        "source_path": src_path.replace("\\", "/"),
        "dest_path": dest_path.replace("\\", "/"),
        "original_size": list(orig_size),
        "final_size": [w, h],
        "aspect": aspect,
        "orientation": orientation,
        "aspect_ratio": round(ratio, 4),
        "trim_box": list(trim_box) if trim_box else None,
        "upscaled": upscaled,
        "force_resized": False,
    }
    sidecar = dest_path + ".prep.json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def prep_image_bytes(img_bytes, dest_path, trim_borders=True):
    tmp = dest_path + ".tmp_src"
    with open(tmp, "wb") as f:
        f.write(img_bytes)
    try:
        return prep_image_file(tmp, dest_path, trim_borders=trim_borders)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
