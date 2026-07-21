"""Graphic poster composer — AI visual (no text) + real typography overlay.

SDXL invents gibberish letters. For chilli-style posters we generate the subject
only, then draw crisp headline/subtext with system fonts via Pillow.
"""
from __future__ import annotations

import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


LAYOUTS = {
    "hero_stack": {
        "name": "Hero Stack (chilli-style)",
        "headline_y": 0.08,
        "sub_y": 0.88,
        "subject_bias": "center",
    },
    "bottom_banner": {
        "name": "Bottom Banner",
        "headline_y": 0.78,
        "sub_y": 0.90,
        "subject_bias": "upper",
    },
    "top_banner": {
        "name": "Top Banner",
        "headline_y": 0.10,
        "sub_y": 0.18,
        "subject_bias": "lower",
    },
}


def find_font(bold=True, size=64):
    """Pick a strong display font available on Windows / common paths."""
    candidates = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts = os.path.join(windir, "Fonts")
    if bold:
        candidates += [
            os.path.join(fonts, "arialbd.ttf"),
            os.path.join(fonts, "ARIALBD.TTF"),
            os.path.join(fonts, "Impact.ttf"),
            os.path.join(fonts, "segoeuib.ttf"),
            os.path.join(fonts, "georgiab.ttf"),
            os.path.join(fonts, "framdit.ttf"),
        ]
    candidates += [
        os.path.join(fonts, "arial.ttf"),
        os.path.join(fonts, "Arial.ttf"),
        os.path.join(fonts, "segoeui.ttf"),
        os.path.join(fonts, "georgia.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def aspect_size(aspect="4:5", long_edge=1600):
    try:
        aw, ah = [int(x) for x in str(aspect).split(":", 1)]
        ratio = aw / float(ah)
    except Exception:
        ratio = 4 / 5.0
    if ratio >= 1:
        w = long_edge
        h = max(1, int(round(long_edge / ratio)))
    else:
        h = long_edge
        w = max(1, int(round(long_edge * ratio)))
    return w, h


def fit_cover(im, tw, th):
    im = im.convert("RGB")
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return im.crop((left, top, left + tw, top + th))


def _text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def fit_font(draw, text, max_width, bold=True, start=120, min_size=28):
    size = start
    while size >= min_size:
        font = find_font(bold=bold, size=size)
        w, _ = _text_size(draw, text, font)
        if w <= max_width:
            return font
        size -= 4
    return find_font(bold=bold, size=min_size)


def draw_centered_text(draw, text, cy, font, fill, stroke_fill=None, stroke_width=0, canvas_w=0):
    tw, th = _text_size(draw, text, font)
    x = (canvas_w - tw) // 2
    y = int(cy - th / 2)
    kwargs = {"font": font, "fill": fill}
    if stroke_fill and stroke_width:
        kwargs["stroke_width"] = stroke_width
        kwargs["stroke_fill"] = stroke_fill
    draw.text((x, y), text, **kwargs)


def compose_poster(
    base_image_path_or_bytes,
    headline,
    subtext="",
    aspect="4:5",
    layout="hero_stack",
    accent_circle=True,
    paper_tint=True,
    headline_color="#111111",
    sub_color="#222222",
):
    """Return PNG bytes of a designed poster with real typography."""
    if isinstance(base_image_path_or_bytes, (bytes, bytearray)):
        base = Image.open(BytesIO(base_image_path_or_bytes))
    else:
        base = Image.open(base_image_path_or_bytes)

    tw, th = aspect_size(aspect, long_edge=1800)
    canvas = Image.new("RGB", (tw, th), "#f4efe6")
    subject = fit_cover(base, tw, th)

    if paper_tint:
        # Soft vintage paper wash behind / blended
        wash = Image.new("RGB", (tw, th), "#f3ead8")
        subject = Image.blend(subject, wash, 0.12)
        subject = ImageEnhance.Color(subject).enhance(1.05)

    canvas.paste(subject, (0, 0))

    if accent_circle:
        # Subtle sun/disc behind center (chilli-style cue) — only if layout is hero
        overlay = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        cx, cy = tw // 2, int(th * 0.48)
        r = int(min(tw, th) * 0.28)
        od.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(240, 200, 60, 55))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(canvas)
    layout_spec = LAYOUTS.get(layout) or LAYOUTS["hero_stack"]
    margin = int(tw * 0.08)
    max_text_w = tw - margin * 2

    headline = (headline or "").strip().upper()
    subtext = (subtext or "").strip()

    if headline:
        h_font = fit_font(draw, headline, max_text_w, bold=True, start=int(th * 0.09), min_size=36)
        draw_centered_text(
            draw,
            headline,
            int(th * layout_spec["headline_y"]) + _text_size(draw, headline, h_font)[1] // 2,
            h_font,
            headline_color,
            stroke_fill="#ffffff",
            stroke_width=2,
            canvas_w=tw,
        )

    if subtext:
        s_font = fit_font(draw, subtext, max_text_w, bold=False, start=int(th * 0.035), min_size=22)
        draw_centered_text(
            draw,
            subtext,
            int(th * layout_spec["sub_y"]),
            s_font,
            sub_color,
            stroke_fill="#ffffff",
            stroke_width=1,
            canvas_w=tw,
        )

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def visual_prompt_for_poster(concept, style_spine=""):
    """Prompt that asks for subject-only art (no letters)."""
    concept = (concept or "iconic subject").strip()
    spine = (style_spine or "").strip()
    return (
        f"{concept}. bold graphic poster illustration, strong silhouette, "
        f"limited color palette, high contrast, centered composition, "
        f"full-bleed artwork, vintage paper texture background, "
        f"{spine + ', ' if spine else ''}"
        "absolutely no text, no letters, no typography, no watermark, no signature, "
        "no frame, no mockup, no room"
    )
