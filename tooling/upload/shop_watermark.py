"""Diagonal tiled shop watermark for listing hero / preview exports.

Clean master.png and print crops stay untouched (buyer Drive files).
Watermarked previews are written beside the piece as master_wm.jpg.
"""
from __future__ import annotations

import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

DEFAULT_MARK = "Aethelgard Art Co."
WM_FILENAME = "master_wm.jpg"


def _find_font(size: int) -> ImageFont.ImageFont:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "fonts", "Inter-Bold.ttf"),
        os.path.join(here, "fonts", "Inter-SemiBold.ttf"),
        os.path.join(here, "fonts", "Oswald-Bold.ttf"),
        os.path.join(here, "fonts", "Montserrat-Bold.ttf"),
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def apply_diagonal_shop_watermark(
    img: Image.Image,
    text: str = DEFAULT_MARK,
    opacity: float = 0.18,
) -> Image.Image:
    """Tile shop name diagonally at low opacity across the full image."""
    text = (text or DEFAULT_MARK).strip() or DEFAULT_MARK
    opacity = max(0.05, min(0.45, float(opacity)))
    rgba = img.convert("RGBA")
    w, h = rgba.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    font_size = max(22, min(w, h) // 18)
    font = _find_font(font_size)

    # Measure on a scratch canvas
    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = scratch.textbbox((0, 0), text, font=font)
    tw = max(1, bbox[2] - bbox[0])
    th = max(1, bbox[3] - bbox[1])
    pad_x = int(font_size * 1.8)
    pad_y = int(font_size * 1.4)
    stamp = Image.new("RGBA", (tw + pad_x * 2, th + pad_y * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    # Soft dark underlay so mark reads on light art; white on dark art
    alpha = int(255 * opacity)
    sd.text((pad_x + 1, pad_y + 1), text, font=font, fill=(0, 0, 0, min(255, int(alpha * 0.7))))
    sd.text((pad_x, pad_y), text, font=font, fill=(255, 255, 255, alpha))

    rotated = stamp.rotate(32, expand=True, resample=Image.Resampling.BICUBIC)
    sw, sh = rotated.size
    step_x = max(int(sw * 0.72), font_size * 6)
    step_y = max(int(sh * 0.62), font_size * 4)

    for row, y in enumerate(range(-sh, h + sh, step_y)):
        x_off = (step_x // 2) if (row % 2) else 0
        for x in range(-sw, w + sw, step_x):
            layer.alpha_composite(rotated, (x + x_off, y))

    out = Image.alpha_composite(rgba, layer)
    return out.convert("RGB")


def ensure_master_watermarked(
    piece_dir: str,
    text: str = DEFAULT_MARK,
    opacity: float = 0.18,
    force: bool = False,
) -> Optional[str]:
    """Create/update master_wm.jpg from master.png. Returns absolute path or None."""
    if not piece_dir or not os.path.isdir(piece_dir):
        return None
    master = os.path.join(piece_dir, "master.png")
    if not os.path.isfile(master):
        # Some covers may only be jpg
        for alt in ("master.jpg", "master.jpeg"):
            cand = os.path.join(piece_dir, alt)
            if os.path.isfile(cand):
                master = cand
                break
        else:
            return None

    out_path = os.path.join(piece_dir, WM_FILENAME)
    try:
        if (
            not force
            and os.path.isfile(out_path)
            and os.path.getmtime(out_path) >= os.path.getmtime(master)
        ):
            return out_path
    except OSError:
        pass

    try:
        with Image.open(master) as im:
            wm = apply_diagonal_shop_watermark(im, text=text, opacity=opacity)
        # Cap preview export size slightly for faster dashboard loads
        max_side = 2400
        if max(wm.size) > max_side:
            scale = max_side / float(max(wm.size))
            wm = wm.resize(
                (max(1, int(round(wm.size[0] * scale))), max(1, int(round(wm.size[1] * scale)))),
                Image.Resampling.LANCZOS,
            )
        wm.save(out_path, "JPEG", quality=90, optimize=True)
        return out_path
    except Exception as e:
        print(f"Watermark failed for {piece_dir}: {e}")
        return None
