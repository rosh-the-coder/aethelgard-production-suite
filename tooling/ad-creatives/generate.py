#!/usr/bin/env python3
"""Generate images from one prompt across Nano Banana, OpenRouter, and GPT Image.

Single code path over three providers so you can run the same prompt on any of them
and pick the best. Model IDs rotate over time (esp. OpenRouter / preview suffixes) —
update the MODELS registry below if a call starts 404'ing.

Keys are read from the environment (see ~/.config/ai-images/env):
    GEMINI_API_KEY      -> Google AI Studio (Nano Banana, direct)
    OPENROUTER_API_KEY  -> OpenRouter (multi-model gateway)
    OPENAI_API_KEY      -> OpenAI (GPT Image; org must be verified)

Usage:
    python generate.py "a misty forest at dawn, muted greens"
    python generate.py "..." --model nano-banana-2 --aspect 1:1 --n 3
    python generate.py "..." --compare                 # same prompt, every model
    python generate.py "..." --ref path/to/style.png   # image-to-image / style ref
    python generate.py --list
"""
import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from datetime import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))   # bundle root
DEFAULT_BUSINESS = "artwork"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def content_root(business):
    """Per-business content dir: brand/, references/, statics/ live here (not in the engine)."""
    return os.path.join(REPO, "businesses", business, "ad-creative")

# alias -> (provider, model_id). Update IDs here when they rotate.
MODELS = {
    # Direct Google AI Studio (cheapest, free testing quota, best on-image text)
    "nano-banana-pro": ("gemini", "gemini-3-pro-image"),      # hero creatives, up to 4K
    "nano-banana-2":   ("gemini", "gemini-3.1-flash-image"),  # fast/cheap volume variants
    # OpenRouter (one-key fallback path). As of 2026-06 only Gemini + GPT-5-image expose
    # image output here — Seedream/Flux are NOT on OpenRouter; use fal.ai/Replicate for those.
    "or-nano-banana-pro": ("openrouter", "google/gemini-3-pro-image"),
    "or-gpt5-image":      ("openrouter", "openai/gpt-5-image"),
    "or-gpt5-image-mini": ("openrouter", "openai/gpt-5-image-mini"),
    # OpenAI direct (GPT Image — strong alt style; fixed sizes only)
    "gpt-image-2":    ("openai", "gpt-image-2"),
    "gpt-image-mini": ("openai", "gpt-image-1-mini"),
    # Cloudflare Workers AI (free ~10k neurons/day via your Worker proxy)
    "cf-sdxl-lightning": ("cloudflare", "sdxl-lightning"),
    "cf-dreamshaper":    ("cloudflare", "dreamshaper"),
    "cf-sdxl":           ("cloudflare", "sdxl"),
    "cf-flux-schnell":   ("cloudflare", "flux-schnell"),
}

DEFAULT_MODEL = "cf-sdxl-lightning"
# Models run when --compare is passed (skips any whose key is missing).
COMPARE_SET = ["cf-sdxl-lightning", "nano-banana-pro", "nano-banana-2", "gpt-image-2", "or-gpt5-image"]

# OpenAI only accepts these named sizes; map our aspect ratios to the closest.
OPENAI_SIZE = {
    "1:1": "1024x1024",
    "4:5": "1024x1536", "2:3": "1024x1536", "9:16": "1024x1536",
    "3:2": "1536x1024", "16:9": "1536x1024",
}

ENV_FOR = {
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    # Cloudflare uses URL + shared secret (not a Cloudflare account token)
    "cloudflare": "CLOUDFLARE_WORKER_KEY",
}


def load_env_file():
    env_path = os.path.expanduser("~/.config/ai-images/env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    os.environ[k] = v
    # google-genai prefers GOOGLE_API_KEY over GEMINI_API_KEY when both exist.
    # Drop empty GOOGLE keys and align a present GEMINI key so Studio keys work.
    google = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    gemini = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not google:
        os.environ.pop("GOOGLE_API_KEY", None)
    if gemini:
        os.environ["GEMINI_API_KEY"] = gemini
        if not google or google != gemini:
            os.environ["GOOGLE_API_KEY"] = gemini

load_env_file()


def require_key(provider):
    env = ENV_FOR[provider]
    key = os.environ.get(env)
    if not key:
        sys.exit(f"ERROR: {env} not set. Add it to ~/.config/ai-images/env.")
    if provider == "cloudflare":
        url = (os.environ.get("CLOUDFLARE_WORKER_URL") or "").strip()
        if not url:
            sys.exit("ERROR: CLOUDFLARE_WORKER_URL not set. Add your workers.dev URL to ~/.config/ai-images/env.")
    return key



# --- brand + reference layers (config-driven, not hardcoded) ------------------

def load_brand(business):
    with open(os.path.join(content_root(business), "brand", "brand.json")) as f:
        return json.load(f)


def brand_prompt(prompt, brand, has_refs):
    """Append the always-on brand directive: real palette/fonts/voice + a logo safe-zone
    and an explicit 'draw no logo/wordmark' rule (the real mark is composited later)."""
    c = brand["colors"]
    lines = [
        prompt.strip(), "",
        f"BRAND — {brand['name']} (apply strictly):",
        f"- Colors: use only Brand Blue {c['primary']} (primary accent), Purple {c['secondary']} "
        f"(secondary), Orange {c['accent']} (rare highlight), on a clean neutral base "
        f"(white / {c['neutral_muted']}, near-black {c['ink']}). No pastel mint or off-brand colors.",
        f"- Typography: headlines in a bold geometric grotesk like {brand['fonts']['display']}; "
        f"UI/body like {brand['fonts']['body']}. Modern, premium SaaS.",
        f"- Voice: {brand['voice']}",
        f"- DO NOT draw any logo, app icon, brand name, '{brand['name']}' wordmark, or placeholder "
        f"text such as the word 'LOGO' anywhere — a real branded footer is composited afterward. "
        f"Reserve a clean, simple horizontal strip across the BOTTOM ~12% of the image (no headline, "
        f"product, CTA, or busy detail in it). You MAY render the headline/marketing copy above that strip.",
    ]
    if has_refs:
        lines.append(
            "- The provided reference image(s) show the REAL app UI — match that "
            "interface (layout, components, colors) for any app/dashboard/screenshot in the scene."
        )
    return "\n".join(lines)


def resolve_refs(explicit, feature, business, feature_max=3):
    biz = content_root(business)
    refs = list(explicit or [])
    if feature:
        with open(os.path.join(biz, "references", "manifest.json")) as f:
            feats = json.load(f)["features"]
        if feature not in feats:
            sys.exit(f"ERROR: --ref-feature '{feature}' unknown. Options: {', '.join(feats)}")
        refs += feats[feature]["images"][:feature_max]  # top few; library can be larger
    resolved = []
    for r in refs:
        # Precedence: absolute -> as-is; references/ or brand/ -> business content
        # root; everything else (swipe-file ../.. or businesses/... paths) -> repo root.
        if os.path.isabs(r):
            p = r
        elif r.startswith("references/") or r.startswith("brand/"):
            p = os.path.join(biz, r)
        else:
            p = os.path.join(REPO, r)
        if not os.path.exists(p):
            sys.exit(f"ERROR: reference image not found: {p}")
        resolved.append(p)
    return resolved


def _data_uri(path):
    mt = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mt};base64,{base64.b64encode(f.read()).decode()}"


# --- providers: each returns a list of PNG byte-strings -----------------------

def gen_gemini(prompt, model_id, aspect, n, refs):
    require_key("gemini")
    from google import genai
    from google.genai import types
    from PIL import Image

    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
    ref_imgs = [Image.open(p) for p in refs]
    out = []
    for _ in range(n):
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect),
        )
        try:
            resp = client.models.generate_content(model=model_id, contents=[prompt, *ref_imgs], config=cfg)
        except Exception:
            # Older SDKs may not accept image_config — retry with aspect in the prompt.
            resp = client.models.generate_content(
                model=model_id, contents=[f"{prompt}\n\nAspect ratio: {aspect}.", *ref_imgs]
            )
        out.append(_extract_gemini(resp))
    return out


def _extract_gemini(resp):
    parts = resp.candidates[0].content.parts
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            data = inline.data
            return data if isinstance(data, (bytes, bytearray)) else base64.b64decode(data)
    said = " ".join(getattr(p, "text", "") or "" for p in parts).strip()
    raise RuntimeError(f"Gemini returned no image. Model said: {said[:500]!r}")


def gen_openrouter(prompt, model_id, aspect, n, refs):
    key = require_key("openrouter")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "Artwork Orchestrator",
    }
    if refs:
        content = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": _data_uri(p)}} for p in refs]
    else:
        content = prompt
    out = []
    for _ in range(n):
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": aspect},
        }
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        out.append(_extract_openrouter(r.json()))
    return out


def _extract_openrouter(data):
    msg = data["choices"][0]["message"]
    images = msg.get("images") or []
    if not images:
        raise RuntimeError(f"OpenRouter returned no image. Content: {str(msg.get('content'))[:500]!r}")
    url = images[0]["image_url"]["url"]
    b64 = url.split(",", 1)[1] if url.startswith("data:") else url
    return base64.b64decode(b64)


def gen_openai(prompt, model_id, aspect, n, refs):
    require_key("openai")
    from openai import OpenAI

    client = OpenAI()  # reads OPENAI_API_KEY
    size = OPENAI_SIZE.get(aspect, "1024x1536")
    if refs:
        files = [open(p, "rb") for p in refs]
        try:
            result = client.images.edit(model=model_id, image=files, prompt=prompt, size=size, n=n)
        finally:
            for f in files:
                f.close()
    else:
        result = client.images.generate(model=model_id, prompt=prompt, size=size, quality="high", n=n)
    return [base64.b64decode(d.b64_json) for d in result.data]


def gen_cloudflare(prompt, model_id, aspect, n, refs):
    """Call your Cloudflare Worker proxy (Workers AI). Returns PNG bytes cropped to aspect."""
    require_key("cloudflare")
    if refs:
        print("~ cloudflare provider ignores --ref (text-to-image only)", file=sys.stderr)
    url = os.environ["CLOUDFLARE_WORKER_URL"].rstrip("/")
    if url and not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    key = os.environ["CLOUDFLARE_WORKER_KEY"]
    # Wall-art constraints: no frames, and aggressively ban text (SDXL loves fake labels)
    full_prompt = (
        f"{prompt.strip()}. full-bleed fine art print filling the entire image edge to edge, "
        "pure visual artwork only, absolutely no text, no letters, no words, no typography, "
        "no labels, no captions, no diagrams, no charts, no watermarks, no signatures, "
        "NOT a photo of a framed print, no picture frame, no mat, no border, no wall, "
        "no room, no mockup, high detail"
    )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    out = []
    for _ in range(n):
        last_err = None
        for attempt in range(2):  # retry once on blank/black frames
            payload = {
                "prompt": full_prompt,
                "model": model_id,
                "aspect": aspect,
                "negative_prompt": (
                    "text, letters, words, typography, title, caption, label, labels, "
                    "handwriting, calligraphy, watermark, signature, logo, "
                    "diagram, chart, anatomy chart, scientific labels, latin text, "
                    "frame, picture frame, mat, border, mockup, room, wall, furniture, "
                    "blurry, low quality, blank, black image, empty"
                ),
            }
            r = requests.post(url + "/", headers=headers, json=payload, timeout=180)
            ctype = (r.headers.get("Content-Type") or "").lower()
            if r.status_code != 200:
                detail = r.text[:500]
                try:
                    detail = r.json().get("details") or r.json().get("error") or detail
                except Exception:
                    pass
                raise RuntimeError(f"Cloudflare Worker HTTP {r.status_code}: {detail}")
            if "application/json" in ctype:
                data = r.json()
                raise RuntimeError(f"Cloudflare Worker returned JSON error: {data}")
            img = r.content
            if not img or len(img) < 100:
                last_err = RuntimeError("Cloudflare Worker returned empty/tiny image body")
                continue
            try:
                out.append(normalize_image_bytes(img, aspect))
                last_err = None
                break
            except RuntimeError as e:
                last_err = e
                if "blank" in str(e).lower() or "black" in str(e).lower():
                    print(f"~ retrying after blank/black frame ({e})", file=sys.stderr)
                    continue
                raise
        if last_err:
            raise last_err
    return out


def normalize_image_bytes(img_bytes, aspect="4:5"):
    """Decode any image, reject blank/black frames, center-crop to aspect, return PNG bytes."""
    from io import BytesIO
    from PIL import Image, ImageStat

    try:
        im = Image.open(BytesIO(img_bytes))
        im = im.convert("RGB")
    except Exception as e:
        raise RuntimeError(f"Could not decode generated image: {e}") from e

    # Reject near-black / empty generations (common CF failure mode)
    gray = im.convert("L")
    stats = ImageStat.Stat(gray)
    if stats.mean[0] < 8 or stats.extrema[0][1] < 12:
        raise RuntimeError("Generated image is nearly blank/black — retry generation")

    try:
        aw, ah = [int(x) for x in str(aspect).split(":", 1)]
        target = aw / float(ah)
    except Exception:
        target = 4 / 5.0

    w, h = im.size
    if w < 64 or h < 64:
        raise RuntimeError(f"Generated image too small ({w}x{h})")

    current = w / float(h)
    if abs(current - target) > 0.03:
        if current > target:
            new_w = max(1, int(round(h * target)))
            left = max(0, (w - new_w) // 2)
            im = im.crop((left, 0, left + new_w, h))
        else:
            new_h = max(1, int(round(w / target)))
            top = max(0, (h - new_h) // 2)
            im = im.crop((0, top, w, top + new_h))

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


_DIRECT = {
    "gemini": gen_gemini,
    "openrouter": gen_openrouter,
    "openai": gen_openai,
    "cloudflare": gen_cloudflare,
}

# --- Higgsfield-first routing: we already pay for those credits, so mapped models
# generate there while the balance stays above the reserve floor; any failure or
# unmapped model falls through to the direct (metered) API. See higgsfield.py.
try:
    import higgsfield as _hf
except ImportError:
    _hf = None


def _routed(direct_fn):
    def wrapped(prompt, model_id, aspect, n, refs):
        if _hf is not None:
            hf_model = _hf.route(model_id)
            if hf_model:
                try:
                    return _hf.generate(prompt, hf_model, aspect, n, refs)
                except Exception as e:  # noqa: BLE001 — any HF failure means: pay the API
                    print(f"~ higgsfield {hf_model} failed ({str(e)[:160]}); "
                          f"falling back to direct API", file=sys.stderr)
        return direct_fn(prompt, model_id, aspect, n, refs)
    return wrapped


DISPATCH = {prov: _routed(fn) for prov, fn in _DIRECT.items()}


# --- io ----------------------------------------------------------------------

def save(img_bytes, label, outdir):
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:48] or "img"
    # Cloudflare may return JPEG; keep extension accurate for tooling
    ext = "png"
    if img_bytes[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    path = os.path.join(outdir, f"{ts}_{slug}.{ext}")
    with open(path, "wb") as f:
        f.write(img_bytes)
    return path


def run_model(alias, prompt, aspect, n, outdir, label=None, refs=None):
    provider, model_id = MODELS[alias]
    imgs = DISPATCH[provider](prompt, model_id, aspect, n, refs or [])
    base = f"{label}-{alias}" if label else alias
    return [save(img, f"{base}-{i}", outdir) for i, img in enumerate(imgs)]


def main():
    ap = argparse.ArgumentParser(description="Generate ad creatives across Nano Banana / OpenRouter / GPT Image.")
    ap.add_argument("prompt", nargs="?", help="Prompt text (or use --prompt-file).")
    ap.add_argument("--prompt-file", help="Read the prompt from a text file.")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model alias (default: {DEFAULT_MODEL}). See --list.")
    ap.add_argument("--aspect", default="4:5", help="Aspect ratio, e.g. 4:5 (Meta feed), 1:1, 9:16 (default: 4:5).")
    ap.add_argument("--n", type=int, default=1, help="Images per model (default: 1).")
    ap.add_argument("--business", default=DEFAULT_BUSINESS,
                    help=f"Business whose ad-creative content to use (default: {DEFAULT_BUSINESS}).")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: <business>/ad-creative/statics/out).")
    ap.add_argument("--label", help="Filename prefix for outputs (e.g. a concept name).")
    ap.add_argument("--brand", action="store_true",
                    help="Apply a brand layer (palette/fonts/voice + logo safe-zone). Requires a brand config; not used by Artwork Orchestrator.")
    ap.add_argument("--ref", action="append", default=[], metavar="PATH",
                    help="Reference image for image-to-image grounding (repeatable).")
    ap.add_argument("--ref-feature", metavar="NAME",
                    help="Pull a feature's reference screenshots from references/manifest.json.")
    ap.add_argument("--ref-max", type=int, default=3, metavar="N",
                    help="Max screenshots to pull for --ref-feature (default: 3).")
    ap.add_argument("--compare", action="store_true", help="Run the prompt across every COMPARE_SET model.")
    ap.add_argument("--no-higgsfield", action="store_true",
                    help="Skip Higgsfield routing for this run (direct APIs only).")
    ap.add_argument("--list", action="store_true", help="List available model aliases and exit.")
    args = ap.parse_args()

    if args.no_higgsfield and _hf is not None:
        _hf.ROUTE_MODE = "off"

    if args.list:
        print("Available models (alias -> provider / id [higgsfield route]):")
        for alias, (prov, mid) in MODELS.items():
            hf_name = _hf.EQUIV.get(mid) if _hf else None
            print(f"  {alias:20s} {prov:11s} {mid}" + (f"  [hf: {hf_name}]" if hf_name else ""))
        if _hf is not None:
            try:
                ent = _hf.credits()
                gate = "HIGGSFIELD first" if _hf.ROUTE_MODE != "off" and (
                    _hf.ROUTE_MODE == "force" or ent["credits"] >= _hf.RESERVE) else "direct APIs"
                print(f"\nHiggsfield: {ent['credits']} credits ({ent.get('plan')}), "
                      f"reserve {_hf.RESERVE}, mode {_hf.ROUTE_MODE} -> {gate}")
            except _hf.HFError as e:
                print(f"\nHiggsfield: unavailable ({e}) -> direct APIs")
        return

    prompt = args.prompt
    if args.prompt_file:
        with open(args.prompt_file) as f:
            prompt = f.read().strip()
    if not prompt:
        ap.error("provide a prompt (positional) or --prompt-file")

    outdir = args.out or os.path.join(content_root(args.business), "statics", "out")

    refs = resolve_refs(args.ref, args.ref_feature, args.business, args.ref_max)
    if args.brand:
        prompt = brand_prompt(prompt, load_brand(args.business), bool(refs))

    aliases = COMPARE_SET if args.compare else [args.model]
    any_ok = False
    last_error = None
    for alias in aliases:
        if alias not in MODELS:
            print(f"! unknown model alias: {alias} (see --list)", file=sys.stderr)
            continue
        provider = MODELS[alias][0]
        env_name = ENV_FOR[provider]
        if not os.environ.get(env_name):
            print(f"~ skipping {alias}: {env_name} not set", file=sys.stderr)
            continue
        if provider == "cloudflare" and not os.environ.get("CLOUDFLARE_WORKER_URL"):
            print(f"~ skipping {alias}: CLOUDFLARE_WORKER_URL not set", file=sys.stderr)
            continue
        try:
            paths = run_model(alias, prompt, args.aspect, args.n, outdir, args.label, refs)
            for path in paths:
                print(f"[ok] {alias:20s} -> {path}")
                any_ok = True
        except Exception as e:
            last_error = e
            print(f"[failed] {alias:20s} failed: {e}", file=sys.stderr)

    if not any_ok:
        msg = f"No images generated. Last error: {last_error}" if last_error else "No images generated (missing keys or unknown model)."
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
