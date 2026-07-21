#!/usr/bin/env python3
"""Generate photorealistic empty-frame mockup templates via Gemini image gen."""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TEMPLATES_DIR = os.path.join(HERE, "templates")
TEMPLATES_JSON = os.path.join(HERE, "templates.json")
PYTHON = os.path.join(ROOT, "tooling", "ad-creatives", ".venv", "Scripts", "python.exe")
GENERATE = os.path.join(ROOT, "tooling", "ad-creatives", "generate.py")

SPINE = (
    "Professional Etsy listing product mockup photograph, photorealistic interior styling, "
    "soft natural lighting, high resolution. The picture frame opening must be completely "
    "EMPTY — plain white or cream mat board only, NO artwork, NO painting, NO print inside. "
    "No text, no watermark, no signature, no people."
)

TEMPLATES = [
    {
        "name": "dark_academia_ornate_portrait_4x5",
        "aspect": "4:5",
        "orientation": "portrait",
        "tags": ["dark_academia", "neutral", "botanical"],
        "prompt": (
            f"{SPINE} Single ornate antique dark-wood portrait frame on a mahogany desk in a "
            "moody Victorian dark academia study, leather books, brass candlestick, warm candlelight."
        ),
    },
    {
        "name": "japandi_shelf_portrait_4x5",
        "aspect": "4:5",
        "orientation": "portrait",
        "tags": ["japandi", "minimalist", "neutral"],
        "prompt": (
            f"{SPINE} Single light-oak frame with white mat on a minimalist japandi floating shelf, "
            "warm beige plaster wall, small ceramic vase, wabi-sabi styling."
        ),
    },
    {
        "name": "boho_bedroom_portrait_4x5",
        "aspect": "4:5",
        "orientation": "portrait",
        "tags": ["boho", "neutral", "minimalist"],
        "prompt": (
            f"{SPINE} Single natural wood frame leaning on a rustic wooden bedside table, "
            "macrame wall hanging, pampas grass, neutral boho bedroom, warm morning light."
        ),
    },
    {
        "name": "modern_landscape_desk_3x2",
        "aspect": "3:2",
        "orientation": "landscape",
        "tags": ["modern", "minimalist", "scandinavian", "japandi"],
        "prompt": (
            f"{SPINE} Single thin black aluminum landscape frame on a clean white desk, "
            "scandinavian home office, monstera plant, bright daylight, minimal decor."
        ),
    },
    {
        "name": "gallery_living_trio_4x5",
        "aspect": "1:1",
        "orientation": "portrait",
        "tags": ["boho", "minimalist", "japandi", "neutral"],
        "multi": 3,
        "prompt": (
            f"{SPINE} Living room wall with THREE identical portrait frames in a horizontal row "
            "above a modern oak sideboard, monstera plant, scandinavian interior, each frame empty."
        ),
    },
    {
        "name": "gallery_wall_five_portrait",
        "aspect": "1:1",
        "orientation": "portrait",
        "tags": ["dark_academia", "neutral", "boho"],
        "multi": 5,
        "prompt": (
            f"{SPINE} Gallery wall with FIVE empty portrait frames in a row on a charcoal wall "
            "above a vintage velvet sofa, dark academia library living room, moody atmospheric light."
        ),
    },
]


def default_quad(w, h, slot=0, total=1):
    """Starter quad — calibrate in Mockup Studio after generation."""
    if total == 1:
        return [
            [int(w * 0.35), int(h * 0.28)],
            [int(w * 0.65), int(h * 0.26)],
            [int(w * 0.63), int(h * 0.72)],
            [int(w * 0.33), int(h * 0.74)],
        ]
    pad = 0.08
    gap = 0.03
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


def generate_image(prompt, aspect, label):
    tmp = os.path.join(HERE, "_gen_tmp")
    os.makedirs(tmp, exist_ok=True)
    cmd = [
        PYTHON, GENERATE, prompt,
        "--model", "nano-banana-2",
        "--aspect", aspect,
        "--n", "1",
        "--label", label,
        "--out", tmp,
    ]
    print(f"  Generating {label}...")
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr or res.stdout)
        return None
    pngs = sorted(
        [os.path.join(tmp, f) for f in os.listdir(tmp) if f.lower().endswith(".png")],
        key=os.path.getmtime,
    )
    return pngs[-1] if pngs else None


def build_registry_entry(name, img_path, spec):
    from PIL import Image

    dest = os.path.join(TEMPLATES_DIR, f"{name}.png")
    shutil.copy2(img_path, dest)
    w, h = Image.open(dest).size

    entry = {
        "name": name,
        "image": f"templates/{name}.png",
        "orientation": spec["orientation"],
        "aspect": spec.get("aspect", "4:5").replace("1:1", "4:5"),
        "tags": spec["tags"],
        "needs_calibration": True,
    }

    multi = spec.get("multi", 1)
    if multi > 1:
        quads = [default_quad(w, h, i, multi) for i in range(multi)]
        entry["quads"] = quads
        entry["box"] = quad_box(quads[0])
    else:
        quad = default_quad(w, h)
        entry["quad"] = quad
        entry["box"] = quad_box(quad)

    return entry


def remove_blank_templates():
    blank_names = [
        "blank_single_portrait_4x5",
        "blank_gallery_trio",
        "blank_gallery_five",
        "blank_gallery_nine",
        "blank_gallery_quad",
    ]
    for name in blank_names:
        path = os.path.join(TEMPLATES_DIR, f"{name}.png")
        if os.path.exists(path):
            os.remove(path)
            print(f"  Removed {name}.png")


def main():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    print("Removing diagram-style blank templates...")
    remove_blank_templates()

    # Keep existing realistic templates
    keep = {"modern_landscape_3x2", "boho_portrait_4x5", "gallery_trio_3frames"}
    existing = []
    if os.path.exists(TEMPLATES_JSON):
        with open(TEMPLATES_JSON, "r", encoding="utf-8") as f:
            existing = [t for t in json.load(f) if t.get("name") in keep]

    new_entries = []
    for spec in TEMPLATES:
        if spec["name"] in keep:
            continue
        src = generate_image(spec["prompt"], spec["aspect"], spec["name"])
        if not src:
            print(f"  FAILED: {spec['name']}")
            continue
        entry = build_registry_entry(spec["name"], src, spec)
        new_entries.append(entry)
        print(f"  Saved {spec['name']}.png ({entry['image']})")

    tmp = os.path.join(HERE, "_gen_tmp")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)

    merged = existing + new_entries
    with open(TEMPLATES_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    print(f"\nDone. {len(merged)} templates in registry ({len(new_entries)} new).")
    print("Open each new template in Mockup Studio to calibrate quad corners.")
    print("For 2K+ templates use Higgsfield — see tooling/mockups/higgsfield_mockup_prompts.md")


if __name__ == "__main__":
    main()
