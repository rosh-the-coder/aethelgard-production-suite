"""Graphic poster composer — AI visual (no text) + real typography overlay.

SDXL invents gibberish letters. We generate the subject only, then draw crisp
type with Pillow using curated free fonts (Google Fonts / system fallbacks).
"""
from __future__ import annotations

import os
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(HERE, "fonts")

# Curated free fonts — downloaded once into tooling/upload/fonts/ (jsDelivr / fontsource)
FONT_CATALOG = {
    "Playfair Display": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@5.2.5/latin-400-italic.ttf",
            "bold_italic": "https://cdn.jsdelivr.net/fontsource/fonts/playfair-display@5.2.5/latin-700-italic.ttf",
        },
        "style": "serif",
    },
    "Cormorant Garamond": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/cormorant-garamond@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/cormorant-garamond@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/cormorant-garamond@5.2.5/latin-400-italic.ttf",
            "bold_italic": "https://cdn.jsdelivr.net/fontsource/fonts/cormorant-garamond@5.2.5/latin-700-italic.ttf",
        },
        "style": "serif",
    },
    "Libre Baskerville": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/libre-baskerville@5.2.5/latin-400-italic.ttf",
        },
        "style": "serif",
    },
    "Montserrat": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@5.2.5/latin-400-italic.ttf",
            "bold_italic": "https://cdn.jsdelivr.net/fontsource/fonts/montserrat@5.2.5/latin-700-italic.ttf",
        },
        "style": "sans",
    },
    "Oswald": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/oswald@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/oswald@5.2.5/latin-700-normal.ttf",
        },
        "style": "sans",
    },
    "Bebas Neue": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@5.2.5/latin-400-normal.ttf",
        },
        "style": "display",
    },
    "Anton": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/anton@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/anton@5.2.5/latin-400-normal.ttf",
        },
        "style": "display",
    },
    "Archivo Black": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/archivo-black@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/archivo-black@5.2.5/latin-400-normal.ttf",
        },
        "style": "display",
    },
    "Great Vibes": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/great-vibes@5.2.5/latin-400-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/great-vibes@5.2.5/latin-400-normal.ttf",
        },
        "style": "script",
    },
    "Pacifico": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/pacifico@5.2.5/latin-400-normal.ttf",
        },
        "style": "script",
    },
    "Caveat": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/caveat@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/caveat@5.2.5/latin-700-normal.ttf",
        },
        "style": "script",
    },
    "Raleway": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/raleway@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/raleway@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/raleway@5.2.5/latin-400-italic.ttf",
        },
        "style": "sans",
    },
    "Lora": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/lora@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/lora@5.2.5/latin-700-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/lora@5.2.5/latin-400-italic.ttf",
        },
        "style": "serif",
    },
    "DM Serif Display": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/dm-serif-display@5.2.5/latin-400-normal.ttf",
            "italic": "https://cdn.jsdelivr.net/fontsource/fonts/dm-serif-display@5.2.5/latin-400-italic.ttf",
        },
        "style": "serif",
    },
    "Space Grotesk": {
        "static": {
            "regular": "https://cdn.jsdelivr.net/fontsource/fonts/space-grotesk@5.2.5/latin-400-normal.ttf",
            "bold": "https://cdn.jsdelivr.net/fontsource/fonts/space-grotesk@5.2.5/latin-700-normal.ttf",
        },
        "style": "sans",
    },
}

LAYOUTS = {
    "hero_stack": {
        "name": "Hero Stack (premium)",
        "headline_y": 0.10,
        "sub_y": 0.90,
        "margin": 0.12,
    },
    "museum": {
        "name": "Museum Poster",
        "headline_y": 0.08,
        "sub_y": 0.92,
        "margin": 0.14,
    },
    "bottom_banner": {
        "name": "Bottom Banner",
        "headline_y": 0.78,
        "sub_y": 0.90,
        "margin": 0.10,
    },
    "top_banner": {
        "name": "Top Banner",
        "headline_y": 0.10,
        "sub_y": 0.18,
        "margin": 0.10,
    },
}


def list_editor_fonts():
    """Fonts available in the typography editor UI."""
    out = []
    for name, meta in FONT_CATALOG.items():
        out.append({
            "family": name,
            "style": meta.get("style") or "sans",
            "google": name.replace(" ", "+"),
        })
    # Always include system Arial as safe fallback label
    out.append({"family": "Arial", "style": "sans", "google": None})
    return out


def _download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "AethelgardPosterComposer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if len(data) < 1000:
        raise RuntimeError(f"Font download too small: {url}")
    with open(dest, "wb") as f:
        f.write(data)


def ensure_font_file(family: str, weight="regular"):
    """Return a local TTF path for family/weight, downloading if needed."""
    family = family or "Montserrat"
    weight = weight or "regular"
    if weight not in ("regular", "bold", "italic", "bold_italic"):
        weight = "regular"

    # System Arial
    if family.lower() == "arial":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        fonts = os.path.join(windir, "Fonts")
        mapping = {
            "regular": "arial.ttf",
            "bold": "arialbd.ttf",
            "italic": "ariali.ttf",
            "bold_italic": "arialbi.ttf",
        }
        path = os.path.join(fonts, mapping.get(weight, "arial.ttf"))
        if os.path.isfile(path):
            return path

    meta = FONT_CATALOG.get(family)
    if not meta:
        # fuzzy
        for k, v in FONT_CATALOG.items():
            if k.lower() == family.lower():
                meta = v
                family = k
                break
    if not meta:
        meta = FONT_CATALOG.get("Montserrat")
        family = "Montserrat"

    static = meta.get("static") or {}
    # Prefer exact weight, then degrade
    for key in (weight, "regular", "bold", "italic"):
        url = static.get(key)
        if not url:
            continue
        fname = f"{family.replace(' ', '')}-{key}.ttf"
        dest = os.path.join(FONTS_DIR, fname)
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            return dest
        try:
            _download(url, dest)
            return dest
        except Exception as e:
            print(f"Font download failed {family} {key}: {e}")
            continue

    return find_system_font_path(bold=(weight in ("bold", "bold_italic")))


def find_system_font_path(bold=True):
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts = os.path.join(windir, "Fonts")
    candidates = []
    if bold:
        candidates += [
            os.path.join(fonts, "arialbd.ttf"),
            os.path.join(fonts, "ARIALBD.TTF"),
            os.path.join(fonts, "Impact.ttf"),
            os.path.join(fonts, "segoeuib.ttf"),
            os.path.join(fonts, "georgiab.ttf"),
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
            return path
    return None


def find_font(bold=True, size=64, family=None, italic=False):
    weight = "regular"
    if bold and italic:
        weight = "bold_italic"
    elif bold:
        weight = "bold"
    elif italic:
        weight = "italic"
    path = ensure_font_file(family or "Montserrat", weight)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    path = find_system_font_path(bold=bold)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
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


def fit_cover(im, tw, th, bias="center"):
    """Cover-crop with optional vertical bias for more subject breathing room."""
    im = im.convert("RGB")
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    if bias == "upper":
        top = int((nh - th) * 0.15)
    elif bias == "lower":
        top = int((nh - th) * 0.75)
    else:
        top = (nh - th) // 2
    top = max(0, min(top, nh - th))
    return im.crop((left, top, left + tw, top + th))


def _text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def fit_font(draw, text, max_width, bold=True, start=120, min_size=28, family=None, italic=False):
    size = start
    while size >= min_size:
        font = find_font(bold=bold, size=size, family=family, italic=italic)
        w, _ = _text_size(draw, text, font)
        if w <= max_width:
            return font, size
        size -= 4
    return find_font(bold=bold, size=min_size, family=family, italic=italic), min_size


def _hex_to_rgb(value, default=(17, 17, 17)):
    try:
        s = str(value or "").strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return default
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def default_layers_for_layout(headline, subtext, layout="hero_stack"):
    """Premium museum-ish defaults: generous margins, strong hierarchy."""
    layout_spec = LAYOUTS.get(layout) or LAYOUTS["hero_stack"]
    layers = []
    hl = (headline or "").strip()
    sub = (subtext or "").strip()
    if hl:
        layers.append({
            "id": "headline",
            "text": hl.upper() if layout != "museum" else hl,
            "x": 0.5,
            "y": float(layout_spec["headline_y"]),
            "fontFamily": "Playfair Display" if layout == "museum" else "Archivo Black",
            "fontSize": 0.075,  # fraction of canvas height
            "color": "#111111",
            "bold": True,
            "italic": False,
            "align": "center",
            "letterSpacing": 0.04 if layout == "museum" else 0.02,
            "strokeColor": "#ffffff",
            "strokeWidth": 0,
            "uppercase": layout != "museum",
            "rotation": 0,
            "blendMode": "normal",
        })
    if sub:
        layers.append({
            "id": "subtext",
            "text": sub.upper() if layout in ("hero_stack", "bottom_banner", "top_banner") else sub,
            "x": 0.5,
            "y": float(layout_spec["sub_y"]),
            "fontFamily": "Montserrat",
            "fontSize": 0.028,
            "color": "#222222",
            "bold": False,
            "italic": False,
            "align": "center",
            "letterSpacing": 0.18,
            "strokeColor": "#ffffff",
            "strokeWidth": 0,
            "uppercase": True,
            "rotation": 0,
            "blendMode": "normal",
        })
    return layers


def _draw_text_onto(draw, text, font, x, y, fill, stroke_fill=None, stroke_w=0, spacing=0, font_px=32):
    """Draw plain or tracked text at top-left (x, y)."""
    if spacing <= 0.001:
        kwargs = {"font": font, "fill": fill}
        if stroke_fill and stroke_w:
            kwargs["stroke_width"] = stroke_w
            kwargs["stroke_fill"] = stroke_fill
        draw.text((x, y), text, **kwargs)
        return
    gaps = []
    widths = []
    for ch in text:
        w, _ = _text_size(draw, ch if ch != " " else " ", font)
        widths.append(w)
        gaps.append(int(font_px * spacing) if ch != " " else int(font_px * spacing * 0.35))
    cx = x
    for i, ch in enumerate(text):
        kwargs = {"font": font, "fill": fill}
        if stroke_fill and stroke_w:
            kwargs["stroke_width"] = stroke_w
            kwargs["stroke_fill"] = stroke_fill
        draw.text((cx, y), ch, **kwargs)
        cx += widths[i] + (gaps[i] if i < len(gaps) else 0)


def _measure_tracked(draw, text, font, spacing, font_px):
    if spacing <= 0.001:
        return _text_size(draw, text, font)
    widths = []
    gaps = []
    for ch in text:
        w, _ = _text_size(draw, ch if ch != " " else " ", font)
        widths.append(w)
        gaps.append(int(font_px * spacing) if ch != " " else int(font_px * spacing * 0.35))
    _, th = _text_size(draw, text.replace(" ", "x") or "x", font)
    total = sum(widths) + (sum(gaps[:-1]) if gaps else 0)
    return total, th


def _blend_overlay(base_rgba, overlay_rgba, mode="normal"):
    """Composite overlay onto base with Photoshop/Figma-style blend modes.

    Formula matches CSS mix-blend-mode: out = (1-a)*base + a*blend(base, src),
    where a is the overlay's alpha. Transparent overlay pixels leave the base unchanged.
    """
    from PIL import ImageChops

    mode = (mode or "normal").lower().replace("_", "-").replace(" ", "-")
    base_rgba = base_rgba.convert("RGBA")
    overlay_rgba = overlay_rgba.convert("RGBA")
    if mode in ("", "normal"):
        return Image.alpha_composite(base_rgba, overlay_rgba)

    br, bg, bb, ba = base_rgba.split()
    or_, og, ob, oa = overlay_rgba.split()
    base_rgb = Image.merge("RGB", (br, bg, bb))
    over_rgb = Image.merge("RGB", (or_, og, ob))

    # Where overlay is transparent its RGB is often 0,0,0 — replace with white (identity
    # for multiply) / black (identity for screen) so ImageChops doesn't crush the backdrop
    # in unused pixels. We still mask with oa at the end.
    if mode == "multiply":
        # Identity for multiply is white
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (255, 255, 255)), oa)
        blended = ImageChops.multiply(base_rgb, over_for_blend)
    elif mode == "screen":
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (0, 0, 0)), oa)
        blended = ImageChops.screen(base_rgb, over_for_blend)
    elif mode == "overlay":
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (128, 128, 128)), oa)
        blended = ImageChops.overlay(base_rgb, over_for_blend)
    elif mode in ("soft-light", "softlight"):
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (128, 128, 128)), oa)
        blended = ImageChops.soft_light(base_rgb, over_for_blend)
    elif mode in ("hard-light", "hardlight"):
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (128, 128, 128)), oa)
        blended = ImageChops.hard_light(base_rgb, over_for_blend)
    elif mode == "darken":
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (255, 255, 255)), oa)
        blended = ImageChops.darker(base_rgb, over_for_blend)
    elif mode == "lighten":
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (0, 0, 0)), oa)
        blended = ImageChops.lighter(base_rgb, over_for_blend)
    elif mode == "difference":
        over_for_blend = Image.composite(over_rgb, Image.new("RGB", over_rgb.size, (0, 0, 0)), oa)
        blended = ImageChops.difference(base_rgb, over_for_blend)
    else:
        return Image.alpha_composite(base_rgba, overlay_rgba)

    # Mix blended result back using overlay alpha (handles anti-aliased glyph edges)
    blended_rgba = Image.merge("RGBA", (*blended.split(), oa))
    # Manual lerp: keep base where oa=0, blended where oa=255
    return Image.composite(blended_rgba, base_rgba, oa)


def render_text_layer_rgba(layer, canvas_w, canvas_h):
    """Rasterize one text layer (rotation + optional horizontal scale) onto a transparent canvas."""
    text = str(layer.get("text") or "")
    if layer.get("uppercase"):
        text = text.upper()
    if not text.strip():
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    size_frac = float(layer.get("fontSize") or 0.05)
    font_px = int(size_frac) if size_frac > 1 else max(12, int(round(canvas_h * size_frac)))
    bold = bool(layer.get("bold"))
    italic = bool(layer.get("italic"))
    family = layer.get("fontFamily") or "Montserrat"
    font = find_font(bold=bold, size=font_px, family=family, italic=italic)
    spacing = float(layer.get("letterSpacing") or 0)
    fill = _hex_to_rgb(layer.get("color"), (17, 17, 17))
    fill_rgba = (fill[0], fill[1], fill[2], 255)
    stroke_fill = _hex_to_rgb(layer.get("strokeColor"), (255, 255, 255)) if layer.get("strokeWidth") else None
    stroke_rgba = (stroke_fill[0], stroke_fill[1], stroke_fill[2], 255) if stroke_fill else None
    stroke_w = int(layer.get("strokeWidth") or 0)
    align = (layer.get("align") or "center").lower()
    rotation = float(layer.get("rotation") or layer.get("rotate") or 0)
    scale_x = float(layer.get("scaleX") or layer.get("boxScaleX") or 1.0)
    scale_x = max(0.25, min(4.0, scale_x))

    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe)
    tw, th = _measure_tracked(pd, text, font, spacing, font_px)
    # Tall display fonts (Anton, etc.) need generous vertical pad or glyphs clip
    try:
        ascent, descent = font.getmetrics()
        th = max(th, ascent + descent)
    except Exception:
        th = max(th, int(font_px * 1.35))
    pad_x = max(stroke_w * 2, 8) + 4
    pad_y = max(stroke_w * 2, int(font_px * 0.28), 12)
    tile = Image.new("RGBA", (max(1, tw + pad_x * 2), max(1, th + pad_y * 2)), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    _draw_text_onto(td, text, font, pad_x, pad_y, fill_rgba, stroke_rgba, stroke_w, spacing, font_px)

    if abs(scale_x - 1.0) > 0.01:
        new_w = max(1, int(round(tile.width * scale_x)))
        tile = tile.resize((new_w, tile.height), Image.Resampling.BICUBIC if hasattr(Image, "Resampling") else Image.BICUBIC)

    if abs(rotation) > 0.01:
        tile = tile.rotate(-rotation, expand=True, resample=Image.BICUBIC)

    cx = float(layer.get("x", 0.5)) * canvas_w
    cy = float(layer.get("y", 0.5)) * canvas_h
    if align == "left":
        ox = int(cx)
    elif align == "right":
        ox = int(cx - tile.width)
    else:
        ox = int(cx - tile.width / 2)
    oy = int(cy - tile.height / 2)

    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    out.paste(tile, (ox, oy), tile)
    return out


def draw_text_layer(draw, layer, canvas_w, canvas_h):
    """Legacy helper (no rotation/blend). Prefer render_text_layer_rgba via compose_from_layers."""
    text = str(layer.get("text") or "")
    if layer.get("uppercase"):
        text = text.upper()
    if not text.strip():
        return
    size_frac = float(layer.get("fontSize") or 0.05)
    font_px = int(size_frac) if size_frac > 1 else max(12, int(round(canvas_h * size_frac)))
    font = find_font(
        bold=bool(layer.get("bold")),
        size=font_px,
        family=layer.get("fontFamily") or "Montserrat",
        italic=bool(layer.get("italic")),
    )
    spacing = float(layer.get("letterSpacing") or 0)
    fill = _hex_to_rgb(layer.get("color"), (17, 17, 17))
    stroke_fill = _hex_to_rgb(layer.get("strokeColor"), (255, 255, 255)) if layer.get("strokeWidth") else None
    stroke_w = int(layer.get("strokeWidth") or 0)
    tw, th = _measure_tracked(draw, text, font, spacing, font_px)
    cx = float(layer.get("x", 0.5)) * canvas_w
    cy = float(layer.get("y", 0.5)) * canvas_h
    align = (layer.get("align") or "center").lower()
    if align == "left":
        x = cx
    elif align == "right":
        x = cx - tw
    else:
        x = cx - tw / 2
    y = cy - th / 2
    _draw_text_onto(draw, text, font, x, y, fill, stroke_fill, stroke_w, spacing, font_px)


def compose_from_layers(
    base_image_path_or_bytes,
    layers=None,
    aspect="4:5",
    paper_tint=True,
    accent_circle=False,
    long_edge=2000,
    pad_subject=0.0,
):
    """Compose poster from base art + editable text layers. Returns PNG bytes."""
    if isinstance(base_image_path_or_bytes, (bytes, bytearray)):
        base = Image.open(BytesIO(base_image_path_or_bytes))
    else:
        base = Image.open(base_image_path_or_bytes)

    tw, th = aspect_size(aspect, long_edge=long_edge)
    canvas = Image.new("RGB", (tw, th), "#f7f2e8")

    pad = float(pad_subject or 0)
    if pad > 0:
        iw = int(tw * (1 - pad * 2))
        ih = int(th * (1 - pad * 2))
        subject = fit_cover(base, iw, ih)
        if paper_tint:
            wash = Image.new("RGB", (iw, ih), "#f3ead8")
            subject = Image.blend(subject, wash, 0.08)
        ox = (tw - iw) // 2
        oy = (th - ih) // 2
        canvas.paste(subject, (ox, oy))
    else:
        subject = fit_cover(base, tw, th)
        if paper_tint:
            wash = Image.new("RGB", (tw, th), "#f3ead8")
            subject = Image.blend(subject, wash, 0.10)
            subject = ImageEnhance.Color(subject).enhance(1.04)
        canvas.paste(subject, (0, 0))

    if accent_circle:
        overlay = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        cx, cy = tw // 2, int(th * 0.48)
        r = int(min(tw, th) * 0.26)
        od.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(240, 200, 60, 48))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    composed = canvas.convert("RGBA")
    for layer in (layers or []):
        layer_img = render_text_layer_rgba(layer, tw, th)
        composed = _blend_overlay(
            composed,
            layer_img,
            layer.get("blendMode") or layer.get("blend") or "normal",
        )

    buf = BytesIO()
    composed.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def compose_poster(
    base_image_path_or_bytes,
    headline,
    subtext="",
    aspect="4:5",
    layout="hero_stack",
    accent_circle=False,
    paper_tint=True,
    headline_color="#111111",
    sub_color="#222222",
    layers=None,
):
    """Backward-compatible entry: build default layers then compose."""
    if layers is None:
        layers = default_layers_for_layout(headline, subtext, layout=layout)
        for layer in layers:
            if layer.get("id") == "headline":
                layer["color"] = headline_color
            if layer.get("id") == "subtext":
                layer["color"] = sub_color
    # Never inset the subject on cream — that bakes fake mats into master.png
    # and shows up as white borders inside lifestyle frames. Museum "space"
    # comes from typography placement only (LAYOUTS margins / y positions).
    return compose_from_layers(
        base_image_path_or_bytes,
        layers=layers,
        aspect=aspect,
        paper_tint=paper_tint,
        accent_circle=accent_circle and layout == "hero_stack",
        long_edge=2000,
        pad_subject=0.0,
    )


def visual_prompt_for_poster(concept, style_spine=""):
    """Subject-only art — Perchance-like painted anime / clean graphic (not muddy SD sketch)."""
    concept = (concept or "iconic subject").strip()
    spine = (style_spine or "").strip()
    return (
        f"{concept}, painted anime style, cel-shaded graphic illustration, "
        f"bold clean vector-like outlines, razor-sharp edges, smooth gradients, "
        f"flat graphic colors, single centered hero subject, "
        f"simple yellow sun disc behind subject, cream paper background, "
        f"generous empty negative space around subject, "
        f"high contrast poster design, sticker logo clarity, "
        f"NO sketch lines, NO finicky scribbles, NO muddy texture, NO hatching, "
        f"NO grain, NO distressed noise, NO watercolor bleed, NO soft blurry edges, "
        f"{spine + ', ' if spine else ''}"
        "absolutely no text, no letters, no typography, no labels, no watermark, "
        "no signature, no frame, no mockup, no room interior"
    )
