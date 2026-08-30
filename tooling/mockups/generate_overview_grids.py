"""Flat overview / contact-sheet grids of bundle artworks for Etsy listing photos.

Style: cream ground + thin beige frames. Arts are contained (never stretched)
inside frames sized to each artwork's own aspect ratio.
"""
from __future__ import annotations

import math
import os
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw


# Near-square listing canvas — denser, less tall skinny cells
CANVAS_W = 2400
CANVAS_H = 2400
BG = (245, 241, 234)
FRAME = (214, 196, 168)
FRAME_INNER = (252, 250, 246)
MARGIN = 64
GAP = 32
FRAME_BORDER = 8
INNER_PAD = 10
JPEG_QUALITY = 92


def _chunk_sizes(n: int, min_per: int = 4, max_per: int = 6, max_sheets: int = 5) -> List[int]:
    """Split n items into 1–max_sheets chunks of min_per..max_per (last may be smaller)."""
    if n <= 0:
        return []
    if n <= max_per:
        return [n]
    sheets = min(max_sheets, max(3, math.ceil(n / 5)))
    base = n // sheets
    rem = n % sheets
    while base > max_per and sheets < max_sheets:
        sheets += 1
        base = n // sheets
        rem = n % sheets
    while base < min_per and sheets > 1:
        sheets -= 1
        base = n // sheets
        rem = n % sheets
    sizes = [base + (1 if i < rem else 0) for i in range(sheets)]
    if len(sizes) >= 2 and sizes[-1] < min_per:
        sizes[-2] += sizes[-1]
        sizes.pop()
        if sizes[-1] > max_per and len(sizes) < max_sheets:
            overflow = sizes[-1] - max_per
            sizes[-1] = max_per
            sizes.append(overflow)
    return [s for s in sizes if s > 0]


def _grid_shape(count: int) -> Tuple[int, int]:
    """cols, rows — prefer wider grids so cells stay closer to print proportions."""
    if count <= 1:
        return 1, 1
    if count == 2:
        return 2, 1
    if count == 3:
        return 3, 1
    if count == 4:
        return 2, 2
    if count == 5:
        return 3, 2
    if count == 6:
        return 3, 2
    cols = min(4, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / cols)
    return cols, rows


def _image_size(path: str) -> Tuple[int, int]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (1000, 1250)


def _fit_contain(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Fit entire artwork inside the frame — never stretch, cream letterbox."""
    img = img.convert("RGB")
    iw, ih = img.size
    if iw <= 0 or ih <= 0 or box_w <= 0 or box_h <= 0:
        return Image.new("RGB", (max(1, box_w), max(1, box_h)), FRAME_INNER)
    scale = min(box_w / iw, box_h / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (box_w, box_h), FRAME_INNER)
    canvas.paste(resized, ((box_w - nw) // 2, (box_h - nh) // 2))
    return canvas


def _draw_sheet(paths: Sequence[str]) -> Image.Image:
    """Lay out arts in a grid; each frame matches that artwork's true aspect (no stretch)."""
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    draw = ImageDraw.Draw(canvas)
    n = len(paths)
    cols, rows = _grid_shape(n)

    usable_w = CANVAS_W - 2 * MARGIN - GAP * (cols - 1)
    usable_h = CANVAS_H - 2 * MARGIN - GAP * (rows - 1)
    cell_w = usable_w // cols
    cell_h = usable_h // rows

    for i, path in enumerate(paths):
        r, c = i // cols, i % cols
        row_items = min(cols, n - r * cols)
        row_offset = 0
        if row_items < cols:
            row_offset = ((cols - row_items) * (cell_w + GAP)) // 2
        x0 = MARGIN + c * (cell_w + GAP) + row_offset
        y0 = MARGIN + r * (cell_h + GAP)

        max_inner_w = cell_w - 2 * FRAME_BORDER - 2 * INNER_PAD
        max_inner_h = cell_h - 2 * FRAME_BORDER - 2 * INNER_PAD
        try:
            with Image.open(path) as raw:
                art = raw.convert("RGB")
            iw, ih = art.size
            if iw <= 0 or ih <= 0:
                continue
            scale = min(max_inner_w / iw, max_inner_h / ih)
            inner_w = max(1, int(round(iw * scale)))
            inner_h = max(1, int(round(ih * scale)))
            fitted = art.resize((inner_w, inner_h), Image.LANCZOS)

            frame_w = inner_w + 2 * INNER_PAD + 2 * FRAME_BORDER
            frame_h = inner_h + 2 * INNER_PAD + 2 * FRAME_BORDER
            fx = x0 + (cell_w - frame_w) // 2
            fy = y0 + (cell_h - frame_h) // 2

            draw.rectangle([fx, fy, fx + frame_w - 1, fy + frame_h - 1], fill=FRAME)
            inner = [
                fx + FRAME_BORDER,
                fy + FRAME_BORDER,
                fx + frame_w - FRAME_BORDER,
                fy + frame_h - FRAME_BORDER,
            ]
            draw.rectangle(inner, fill=FRAME_INNER)
            canvas.paste(fitted, (inner[0] + INNER_PAD, inner[1] + INNER_PAD))
        except Exception:
            continue
    return canvas


def generate_bundle_overview_grids(
    piece_dir: str,
    *,
    image_paths: Optional[List[str]] = None,
    max_sheets: int = 5,
    min_per: int = 4,
    max_per: int = 6,
) -> List[str]:
    """
    Write mockup_overview_01.jpg … covering all bundle arts.
    Returns list of absolute paths written.
    """
    if image_paths is None:
        from generate_mockups import list_bundle_images

        image_paths = [img["path"] for img in list_bundle_images(piece_dir, max_count=500)]

    paths = [p for p in (image_paths or []) if p and os.path.isfile(p)]
    for fname in os.listdir(piece_dir):
        low = fname.lower()
        if low.startswith("mockup_overview_") and low.endswith((".jpg", ".jpeg")):
            try:
                os.remove(os.path.join(piece_dir, fname))
            except OSError:
                pass

    if not paths:
        return []

    # Group similar orientations together so sheets look coherent
    def _orient_key(p: str) -> Tuple[int, str]:
        w, h = _image_size(p)
        if h <= 0:
            return (1, p)
        a = w / float(h)
        if a < 0.92:
            return (0, p)  # portrait first
        if a > 1.08:
            return (2, p)  # landscape
        return (1, p)

    paths = sorted(paths, key=_orient_key)

    sizes = _chunk_sizes(len(paths), min_per=min_per, max_per=max_per, max_sheets=max_sheets)
    written: List[str] = []
    idx = 0
    for sheet_i, count in enumerate(sizes, 1):
        chunk = paths[idx : idx + count]
        idx += count
        sheet = _draw_sheet(chunk)
        out_name = f"mockup_overview_{sheet_i:02d}.jpg"
        out_path = os.path.join(piece_dir, out_name)
        sheet.save(out_path, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True)
        written.append(out_path)
        print(f"  Overview grid {sheet_i}/{len(sizes)} ({count} arts) -> {out_name}")
    return written
