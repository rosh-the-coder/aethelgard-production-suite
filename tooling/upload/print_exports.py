"""Export print-ready JPEG size packs from a master artwork.

Default = multi-ratio Etsy pack (not locked to the generation aspect).
Master is center-cropped to each target ratio, then sized at 300 DPI.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Tuple

from PIL import Image

DPI = 300
JPEG_QUALITY = 95
PRINT_PACK_VERSION = "multi_ratio_v1"

# Industry-standard digital-download ratios → inch sizes (portrait w×h).
# Landscape masters flip each pair automatically.
ETSY_RATIO_PACK: Dict[str, Dict[str, Tuple[float, float]]] = {
    "2x3": {
        "4x6": (4, 6),
        "8x12": (8, 12),
        "12x18": (12, 18),
        "16x24": (16, 24),
        "20x30": (20, 30),
        "24x36": (24, 36),
    },
    "3x4": {
        "6x8": (6, 8),
        "9x12": (9, 12),
        "12x16": (12, 16),
        "15x20": (15, 20),
        "18x24": (18, 24),
    },
    "4x5": {
        "4x5": (4, 5),
        "8x10": (8, 10),
        "16x20": (16, 20),
        "20x25": (20, 25),
    },
    "5x7": {
        "5x7": (5, 7),
        "10x14": (10, 14),
    },
    "11x14": {
        "11x14": (11, 14),
    },
    "ISO_A": {
        "A5": (5.83, 8.27),
        "A4": (8.27, 11.69),
        "A3": (11.69, 16.54),
    },
}


def center_crop_resize(img: Image.Image, w_px: int, h_px: int) -> Image.Image:
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Invalid source image")
    src_ratio = src_w / src_h
    target_ratio = w_px / h_px
    if src_ratio > target_ratio:
        new_w = int(round(src_h * target_ratio))
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = int(round(src_w / target_ratio))
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return img.crop(box).resize((w_px, h_px), Image.LANCZOS)


def _oriented_inches(
    w_in: float, h_in: float, orientation: str
) -> Tuple[float, float]:
    orientation = (orientation or "portrait").lower()
    if orientation == "landscape" and h_in > w_in:
        return (h_in, w_in)
    if orientation == "portrait" and w_in > h_in:
        return (h_in, w_in)
    return (w_in, h_in)


def size_labels_for_meta(orientation: str = "portrait", aspect: str = "4:5") -> List[str]:
    """Flat list of inch labels for SEO / badges."""
    labels: List[str] = []
    for _ratio, sizes in ETSY_RATIO_PACK.items():
        for label, (w, h) in sizes.items():
            ow, oh = _oriented_inches(w, h, orientation)
            # Keep friendly label; flip text for landscape when needed
            if orientation == "landscape" and (w, h) != (ow, oh):
                if "x" in label and not label.upper().startswith("A"):
                    a, b = label.lower().split("x", 1)
                    labels.append(f"{b}x{a}")
                else:
                    labels.append(label)
            else:
                labels.append(label)
    return labels


def ratio_size_summary(orientation: str = "portrait") -> str:
    """Human line for SEO: '2:3 (4x6, 8x12…); 4:5 (4x5, 8x10…); …'"""
    parts = []
    for ratio, sizes in ETSY_RATIO_PACK.items():
        labels = []
        for label, (w, h) in sizes.items():
            ow, oh = _oriented_inches(w, h, orientation)
            if orientation == "landscape" and (w, h) != (ow, oh) and "x" in label and not label.upper().startswith("A"):
                a, b = label.lower().split("x", 1)
                labels.append(f'{b}x{a}"')
            else:
                labels.append(f'{label}"' if not label.upper().startswith("A") else label)
        nice = ratio.replace("x", ":") if ratio != "ISO_A" else "ISO A"
        parts.append(f"{nice} — " + ", ".join(labels))
    return "; ".join(parts)


def export_print_set(
    master_path: str,
    prints_dir: str,
    slug: str,
    *,
    orientation: str = "portrait",
    aspect: str = "4:5",
    dry_run: bool = False,
) -> List[str]:
    """
    Write a full multi-ratio print pack under prints_dir/{ratio}/.
    Returns flat list of size labels written.
    """
    if not os.path.isfile(master_path):
        raise FileNotFoundError(f"Master missing: {master_path}")

    # Clean previous pack so old single-ratio stubs don't linger
    if os.path.isdir(prints_dir):
        shutil.rmtree(prints_dir)
    os.makedirs(prints_dir, exist_ok=True)

    img = Image.open(master_path).convert("RGB")
    written: List[str] = []
    manifest = {"version": PRINT_PACK_VERSION, "orientation": orientation, "ratios": {}}

    for ratio, sizes in ETSY_RATIO_PACK.items():
        ratio_dir = os.path.join(prints_dir, ratio)
        os.makedirs(ratio_dir, exist_ok=True)
        ratio_files = []
        for label, (w_in, h_in) in sizes.items():
            ow, oh = _oriented_inches(w_in, h_in, orientation)
            file_label = label
            if orientation == "landscape" and (w_in, h_in) != (ow, oh) and "x" in label and not label.upper().startswith("A"):
                a, b = label.lower().split("x", 1)
                file_label = f"{b}x{a}"
            if dry_run:
                w_px = max(80, int(round(ow * 40)))
                h_px = max(80, int(round(oh * 40)))
                quality = 70
            else:
                w_px = int(round(ow * DPI))
                h_px = int(round(oh * DPI))
                quality = JPEG_QUALITY
            out_name = f"{slug}_{file_label}.jpg"
            out = os.path.join(ratio_dir, out_name)
            cropped = center_crop_resize(img, w_px, h_px)
            cropped.save(out, "JPEG", quality=quality, dpi=(DPI, DPI))
            written.append(file_label)
            ratio_files.append({"label": file_label, "file": out_name, "px": [w_px, h_px]})
        manifest["ratios"][ratio] = ratio_files

    with open(os.path.join(prints_dir, "sizes_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return written


def prints_look_like_stubs(prints_dir: str) -> bool:
    """True if pack missing, stubby, or still old single-ratio flat export."""
    if not os.path.isdir(prints_dir):
        return True
    manifest = os.path.join(prints_dir, "sizes_manifest.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") == PRINT_PACK_VERSION and len(data.get("ratios") or {}) >= 4:
                return False
        except Exception:
            pass
    # Ratio subfolders present?
    ratio_dirs = [d for d in ETSY_RATIO_PACK if os.path.isdir(os.path.join(prints_dir, d))]
    if len(ratio_dirs) >= 4:
        return False
    # Flat old 4:5-only or 800x1000 stubs
    dims = []
    for root, _dirs, files in os.walk(prints_dir):
        for name in files:
            if not name.lower().endswith((".jpg", ".jpeg")):
                continue
            path = os.path.join(root, name)
            try:
                with Image.open(path) as im:
                    dims.append(im.size)
            except Exception:
                continue
    if not dims:
        return True
    if all(d == (800, 1000) for d in dims):
        return True
    # Same pixel dims for differently named sizes = stub clones (classic 8x10==16x20 bug)
    if len(dims) >= 2 and len(set(dims)) == 1:
        return True
    return True  # force upgrade to multi-ratio when incomplete


def iter_print_files(prints_dir: str) -> List[Tuple[str, str]]:
    """Return (absolute_path, upload_relative_name) for all print JPGs."""
    out: List[Tuple[str, str]] = []
    if not os.path.isdir(prints_dir):
        return out
    for root, _dirs, files in os.walk(prints_dir):
        for name in sorted(files):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            if name.lower() == "sizes_manifest.json":
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, prints_dir).replace("\\", "/")
            # Drive-friendly flat-ish name: 4x5__slug_8x10.jpg
            upload_name = rel.replace("/", "__")
            out.append((full, upload_name))
    return out


def ensure_real_prints(
    piece_dir: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> List[str]:
    """Ensure piece_dir/prints has a full multi-ratio pack."""
    master = os.path.join(piece_dir, "master.png")
    if not os.path.isfile(master):
        for alt in ("master.jpg", "master.jpeg"):
            p = os.path.join(piece_dir, alt)
            if os.path.isfile(p):
                master = p
                break
    if not os.path.isfile(master):
        raise FileNotFoundError("No master image in piece")

    meta_path = os.path.join(piece_dir, "meta.json")
    meta: Dict = {}
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    slug = meta.get("slug") or os.path.basename(piece_dir.rstrip("\\/"))
    orientation = meta.get("orientation") or "portrait"
    aspect = meta.get("aspect") or meta.get("aspect_ratio") or "4:5"
    prints_dir = os.path.join(piece_dir, "prints")

    needs = force or prints_look_like_stubs(prints_dir) or meta.get("print_pack") != PRINT_PACK_VERSION
    if needs:
        labels = export_print_set(
            master,
            prints_dir,
            slug,
            orientation=orientation,
            aspect=aspect,
            dry_run=dry_run or bool(meta.get("dry_run")),
        )
        meta["sizes"] = labels
        meta["print_dpi"] = DPI
        meta["print_pack"] = PRINT_PACK_VERSION
        meta["print_ratios"] = list(ETSY_RATIO_PACK.keys())
        meta["sizes_summary"] = ratio_size_summary(orientation)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return labels

    existing = meta.get("sizes")
    if isinstance(existing, list) and existing:
        return existing
    labels = size_labels_for_meta(orientation, aspect)
    meta["sizes"] = labels
    meta["print_pack"] = PRINT_PACK_VERSION
    meta["sizes_summary"] = ratio_size_summary(orientation)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return labels


def ensure_customer_prints(
    piece_dir: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> List[str]:
    """
    Ensure print packs for whatever customers actually download.
    PD packs (pd_bundle): keep native masters — do not invent multi-ratio crops.
    AI theme bundles: rebuild multi-ratio packs on each bundle_sources member.
    Singles: rebuild on the piece itself.
    """
    meta_path = os.path.join(piece_dir, "meta.json")
    meta: Dict = {}
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    product_type = (meta.get("product_type") or "").lower()
    if product_type == "pd_bundle":
        # Museum / open-access packs ship native files only — no multi-ratio crops.
        meta["sizes"] = "native"
        meta["skip_print_crops"] = True
        meta.pop("print_pack", None)
        meta.pop("sizes_summary", None)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return ["native"]

    sources = meta.get("bundle_sources") or []
    if product_type == "bundle" and sources:
        for src in sources:
            src = (src or "").replace("/", os.sep)
            if not os.path.isdir(src):
                continue
            ensure_real_prints(src, force=force, dry_run=dry_run)
        orientation = meta.get("orientation") or "portrait"
        labels = size_labels_for_meta(orientation)
        meta["sizes"] = labels
        meta["print_dpi"] = DPI
        meta["print_pack"] = PRINT_PACK_VERSION
        meta["print_ratios"] = list(ETSY_RATIO_PACK.keys())
        meta["sizes_summary"] = ratio_size_summary(orientation)
        meta["skip_print_crops"] = False
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return labels

    return ensure_real_prints(piece_dir, force=force, dry_run=dry_run)
