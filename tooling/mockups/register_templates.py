#!/usr/bin/env python3
"""Rebuild templates.json from PNG files in templates/ (starter quads for calibration)."""
import json
import os
import re

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(HERE, "templates")
OUT = os.path.join(HERE, "templates.json")


def default_quad(w, h, slot=0, total=1):
    if total == 1:
        return [
            [int(w * 0.35), int(h * 0.28)],
            [int(w * 0.65), int(h * 0.26)],
            [int(w * 0.63), int(h * 0.72)],
            [int(w * 0.33), int(h * 0.74)],
        ]
    pad, gap = 0.08, 0.03
    usable = 1.0 - pad * 2 - gap * (total - 1)
    fw = usable / total
    x0 = pad + slot * (fw + gap)
    x1 = x0 + fw
    y0, y1 = 0.18, 0.82
    return [
        [int(w * x0), int(h * y0)],
        [int(w * x1), int(h * y0)],
        [int(w * x1), int(h * y1)],
        [int(w * x0), int(h * y1)],
    ]


def quad_box(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return [min(xs), min(ys), max(xs), max(ys)]


def frame_count(name: str) -> int:
    m = re.search(r"(\d+)frames", name)
    if m:
        return int(m.group(1))
    if "triple" in name or "trio" in name:
        return 3
    if "gallery_five" in name or "_five_" in name:
        return 5
    return 1


def tags_for(name: str) -> list:
    if name.startswith("japandi") or name.startswith("boho"):
        return ["japandi", "minimalist", "neutral"]
    if name.startswith("dark_academia"):
        return ["dark_academia", "neutral", "botanical"]
    if name.startswith("botanical"):
        return ["botanical", "neutral", "vintage_botanical_chart"]
    return ["neutral"]


def main():
    templates = []
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if not fname.lower().endswith(".png"):
            continue
        name = fname[:-4]
        path = os.path.join(TEMPLATES_DIR, fname)
        with Image.open(path) as im:
            w, h = im.size
        orient = "landscape" if w >= h else "portrait"
        aspect = "3:2" if w >= h else "4:5"
        n = frame_count(name)
        entry = {
            "name": name,
            "image": f"templates/{fname}",
            "orientation": orient,
            "aspect": aspect,
            "tags": tags_for(name),
            "needs_calibration": True,
            "source": "higgsfield",
        }
        if "bundle" in name:
            entry["layout"] = "bundle_marketing"
            entry["note"] = (
                "Bundle hero — calibrate in Mockup Studio only if compositing; "
                "otherwise use for listing carousel."
            )
        elif n > 1:
            quads = [default_quad(w, h, i, n) for i in range(n)]
            entry["quads"] = quads
            entry["box"] = quad_box(quads[0])
        else:
            quad = default_quad(w, h)
            entry["quad"] = quad
            entry["box"] = quad_box(quad)
        templates.append(entry)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2)
    print(f"Wrote {len(templates)} templates to {OUT}")
    for t in templates:
        fc = len(t.get("quads", [])) or (1 if t.get("quad") else 0)
        label = "bundle" if t.get("layout") == "bundle_marketing" else f"{fc} frame(s)"
        print(f"  {t['name']} — {label}")


if __name__ == "__main__":
    main()
