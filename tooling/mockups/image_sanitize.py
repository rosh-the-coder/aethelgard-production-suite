"""Detect and fix common AI image artifacts before print export / mockup compositing."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageStat


def _region_variance(img_gray: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = img_gray.crop(box)
    if crop.width < 2 or crop.height < 2:
        return 0.0
    stat = ImageStat.Stat(crop)
    return float(stat.var[0])


def _avg_rgb(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    crop = img.crop(box).resize((24, 8), Image.Resampling.BILINEAR)
    stat = ImageStat.Stat(crop)
    return tuple(int(v) for v in stat.mean[:3])


def detect_signature_mark(img: Image.Image) -> bool:
    """
    Heuristic: AI models often leave a small signature/watermark in the bottom-left.
    Compare variance and darkness of that corner vs a clean reference strip above it.
    """
    w, h = img.size
    if w < 80 or h < 80:
        return False

    gray = img.convert("L")
    sw = max(32, int(w * 0.14))
    sh = max(28, int(h * 0.10))

    corner = (0, h - sh, sw, h)
    ref = (sw, h - sh - max(16, int(h * 0.04)), min(w, sw * 3), h - sh)

    corner_var = _region_variance(gray, corner)
    ref_var = _region_variance(gray, ref)

    corner_stat = ImageStat.Stat(gray.crop(corner))
    ref_stat = ImageStat.Stat(gray.crop(ref))
    corner_mean = corner_stat.mean[0]
    ref_mean = ref_stat.mean[0]

    # Dark ink-like mark on lighter surround
    darker_corner = corner_mean < ref_mean - 18
    high_local_detail = corner_var > max(120.0, ref_var * 2.2)
    return darker_corner and high_local_detail


def remove_signature_corner(img: Image.Image) -> tuple[Image.Image, bool]:
    """Paint over detected bottom-left signature using sampled surround color."""
    if not detect_signature_mark(img):
        return img, False

    w, h = img.size
    sw = max(32, int(w * 0.14))
    sh = max(28, int(h * 0.10))

    fill_box = (sw, max(0, h - sh - int(h * 0.05)), min(w, sw * 4), max(0, h - sh))
    fill = _avg_rgb(img, fill_box)

    out = img.copy()
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, h - sh, sw, h), fill=fill)
    return out, True


def normalize_trim_pct(value) -> float:
    """Dashboard sends 0–10 (percent). Legacy payloads may send 0.03 (fraction)."""
    v = float(value or 0)
    if v <= 0:
        return 0.0
    if v < 0.2:
        return v * 100.0
    return v


def scan_image_quality(img: Image.Image) -> list[str]:
    """Return human-readable warnings for dashboard tooltips."""
    warnings: list[str] = []
    if detect_signature_mark(img):
        warnings.append("Possible AI signature in bottom-left corner — will be auto-removed on export.")
    w, h = img.size
    if w < 1200 or h < 1200:
        warnings.append("Source resolution is low — mockup edges may look soft until upscaled.")
    return warnings


def sanitize_master(img: Image.Image, trim_pct: float = 0.0) -> tuple[Image.Image, list[str]]:
    """Full sanitize pass used during finalize and mockup prep."""
    warnings = scan_image_quality(img)
    out = img.convert("RGB")
    out, removed = remove_signature_corner(out)
    if removed:
        warnings.append("Auto-removed AI signature/watermark from bottom-left.")

    trim = normalize_trim_pct(trim_pct)
    if trim > 0:
        w, h = out.size
        dx = int(w * (trim / 100.0))
        dy = int(h * (trim / 100.0))
        if dx > 0 or dy > 0:
            out = out.crop((dx, dy, w - dx, h - dy))
            warnings.append(f"Trimmed {trim:g}% canvas margin.")

    return out, warnings
