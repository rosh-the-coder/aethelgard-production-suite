# Codebase Map: Aethelgard Art Co. (RoshWillBeRich)

This file serves as a comprehensive developer guide and architectural manifest for the **Etsy Automated Art Production Pipeline**. Feed this file directly to any AI coding assistant (like Cursor or Claude) to align it instantly with the codebase.

**Shop brand:** Aethelgard Art Co. (shop not yet live — pipeline in active development/testing)

---

## 📂 Project Structure & File Map

```
f:/Apps/Etsy 2026/roshwillberich/
├── roshwillberich.md               # This file — architectural manifest
├── pipeline_guide.md               # Step-by-step operator walkthrough
│
├── .claude/skills/artwork-orchestrator/
│   └── scripts/artwork.py          # Post-generation chain: upscale → crop → index
│
└── tooling/
    ├── upload/
    │   ├── server.py               # HTTP server (port 8080) — REST APIs + dashboard
    │   ├── dashboard.html          # Web UI: research, generator, catalog, mockup studio
    │   ├── shop_analyzer.py        # Playwright competitor shop scraper
    │   ├── etsy_research.py        # Playwright keyword opportunity researcher
    │   ├── upload_to_etsy.py       # Playwright Etsy session login + draft uploader
    │   └── niche_presets.json      # Validated niche cards (prompts, tags, pricing)
    │
    ├── ad-creatives/
    │   ├── generate.py             # Multi-provider image generator (Gemini, OpenRouter, OpenAI)
    │   └── .venv/                  # Python virtual environment (Playwright, Pillow, etc.)
    │
    ├── mockups/
    │   ├── generate_mockups.py     # Pillow perspective compositing + zoom GIF engine
    │   ├── generate_pdf_links.py   # Branded customer download PDF compiler
    │   ├── templates.json          # Mockup layout registry (quad/quads coordinates)
    │   ├── mockup_helper.html      # Standalone calibration helper (legacy)
    │   └── templates/              # Base mockup images — empty frames preferred (PNG/JPG)
    │
    ├── upscale/
    │   ├── README_windows.md       # Real-ESRGAN usage docs
    │   ├── models/                 # .param model files (bundled)
    │   └── realesrgan-ncnn-vulkan.exe   # ⚠️ Must be downloaded separately (see Setup)
    │
    └── digital-product-research/
        └── artwork-runs/           # All generated runs and finalized listings live here
            └── <run_name>/
                ├── run.json        # Run index metadata
                ├── index.md        # Human-readable run summary
                └── <piece_slug>/
                    ├── meta.json   # Piece metadata (title, model, orientation, sizes)
                    ├── listing.json
                    ├── seo.md
                    ├── prompt.txt
                    ├── prints/     # 300 DPI JPEGs (4:5, 3:2, 11:14, etc.)
                    ├── mockups/    # Static composites + mockup_zoom.gif
                    └── download.pdf  # Customer-facing download sheet (optional)
```

---

## 🚀 End-to-End Pipeline

| Step | Tab | What happens |
|------|-----|--------------|
| 1. Research | Market Research | Keyword scores, competitor shop scrape, niche preset loading |
| 2. Generate | Print Generator | 3 AI candidates (Faithful / Signature / Wildcard) + SEO titles |
| 3. Finalize | Print Generator | Edge trim, Real-ESRGAN upscale, multi-aspect print export, mockups |
| 4. Review | Catalog & Uploads | Browse pieces, preview mockups/GIF, edit listing metadata |
| 5. Deliver | Catalog & Uploads | Compile branded PDF with Google Drive download link |
| 6. Upload | Catalog & Uploads | Push draft listing to Etsy via Playwright |

See `pipeline_guide.md` for the full operator walkthrough.

---

## ⚙️ Core Modules & Logic

### 1. Image Generation (`tooling/ad-creatives/generate.py`)

Multi-provider image engine with a single code path:

| Alias | Provider | Model |
|-------|----------|-------|
| `nano-banana-pro` | Gemini (direct) | `gemini-3-pro-image` |
| `nano-banana-2` | Gemini (direct) | `gemini-3.1-flash-image` |
| `or-nano-banana-pro` | OpenRouter | `google/gemini-3-pro-image` |
| `or-gpt5-image` | OpenRouter | `openai/gpt-5-image` |
| `gpt-image-2` | OpenAI (direct) | `gpt-image-2` |

**API keys** are read from `~/.config/ai-images/env`:
```
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...   # optional
OPENAI_API_KEY=...       # optional
```

The dashboard generates 3 stylistic variants per concept and queries Gemini for SEO-optimized listing titles.

### 2. Artwork Finalization (`.claude/skills/artwork-orchestrator/scripts/artwork.py`)

Deterministic post-generation chain (no network):
- Shells out to **Real-ESRGAN ncnn-vulkan** for 4× upscale
- Crops down to print sizes at **300 DPI** (only ever downscales from upscaled master)
- Assembles titled piece folders and builds `run.json` / `index.md`

### 3. Mockup Studio (Perspective Warp & Quad Mapping)

**Warping mathematics:** Pillow maps 2D rectangular prints onto 3D angled mockup frames using homographic projection (8-coefficient perspective transform from 4 source corners → 4 target corners).

**Coordinate system (critical):**
- During editing, handles store **normalized coordinates** (`0.0`–`1.0` relative to the displayed image's width/height).
- All overlay geometry (SVG polygon, handles, drag math) is anchored to the **image element's bounding box**, not the outer container. The board shrink-wraps to the image so handles never drift outside the frame.
- On save, normalized values are converted to **natural pixel coordinates**: `round(pt.x * naturalWidth)`, `round(pt.y * naturalHeight)`.

**Zoom:**
- Canvas Zoom (`50%`–`300%`) scales the **image pixel width** directly (`studioBaseWidth * zoom`), keeping handles, SVG overlay, and drag math in sync.
- Hover magnifier: `3.5×` circular lens follows the cursor during drags for precision calibration.

**Multi-slot frames (gallery walls / bundles):**
- Single frame: `"quad": [[x,y], [x,y], [x,y], [x,y]]`
- Multi-frame: `"quads": [ [[x,y]...], [[x,y]...], ... ]`
- In Mockup Studio, use **+ Add Region** to define each frame slot independently.
- `generate_mockups.py` composites a different print into each quad slot (up to the number of prints in the piece folder).

**Template sourcing guidance:**
- Use **empty/blank frame** lifestyle photos (white mat or empty frame opening) — not pre-filled art.
- For bundle listings (sets of 5–10+ prints), source wide gallery-wall mockups with multiple empty frames in one scene.
- Save as high-res PNG/JPG (≥2000px wide), calibrate each frame region in Mockup Studio, tag with matching aesthetic (boho, japandi, dark_academia, etc.).
- Store calibrated templates in `tooling/mockups/templates/`; registry in `templates.json`.

### 4. Pillow Compositing Engine (`generate_mockups.py`)

- Filters `templates.json` by orientation (portrait/landscape), aspect ratio, and style tags.
- Projects prints onto target quads via `Image.Transform.PERSPECTIVE`.
- Blends with `ImageChops.multiply` to preserve mockup lighting, textures, and shadows.
- Auto-generates `mockup_zoom.gif` — 25-frame sinusoidal Ken Burns dolly sweep.

### 5. Etsy Research & Upload

- **`etsy_research.py`** — keyword opportunity scores (volume, competition, top listings).
- **`shop_analyzer.py`** — competitor shop KPIs; degrades to niche averages if blocked.
- **`upload_to_etsy.py`** — session cookie auth, draft listing creation (images, SEO, tags, price).

---

## 📡 REST API Specifications (`server.py`)

All APIs served at `http://127.0.0.1:8080`.

### GET endpoints

| Endpoint | Action |
|----------|--------|
| `GET /` | Dashboard UI (`dashboard.html`) |
| `GET /mockup_helper` | Legacy standalone calibration page |
| `GET /api/runs` | Scan `artwork-runs/` catalog tree |
| `GET /api/niche_presets` | Load validated niche preset cards |
| `GET /api/research?q={keyword}` | Etsy keyword opportunity research |
| `GET /api/analyze_shop?name={shop}` | Competitor shop scrape |

### POST endpoints

| Endpoint | Payload | Action |
|----------|---------|--------|
| `POST /api/generate_candidates` | `{ concept, prompt, aspect, model }` | Generate 3 AI candidates + SEO titles |
| `POST /api/finalize_selected` | `{ run_dir, keepers, trim_margin }` | Upscale, crop, export prints, run mockups |
| `POST /api/save_mockup_template` | `{ name, orientation, aspect, box, tags, image_data, quad/quads }` | Save template PNG + registry entry |
| `POST /api/generate_mockups` | `{ piece_dir }` | Regenerate static mockups + zoom GIF |
| `POST /api/generate_pdf` | `{ piece_dir, drive_url }` | Compile customer download PDF |
| `POST /api/upload` | `{ piece_dir }` | Push Etsy draft listing |
| `POST /api/login` | — | Open Etsy auth browser window |
| `POST /api/save` | listing metadata | Save piece listing edits |
| `POST /api/open_folder` | `{ path }` | Open piece folder in Explorer |

---

## 🛠️ Setup & Commands

### Prerequisites

1. **Python venv** (already at `tooling/ad-creatives/.venv/`)
2. **Gemini API key** — create at [Google AI Studio](https://aistudio.google.com/apikey), save to `~/.config/ai-images/env`:
   ```
   GEMINI_API_KEY=your_key_here
   ```
3. **Real-ESRGAN upscaler** — download `realesrgan-ncnn-vulkan.exe` from [Real-ESRGAN releases](https://github.com/xinntao/Real-ESRGAN/releases) and place in `tooling/upscale/`. Model `.param` files are already bundled in `tooling/upscale/models/`.

### Run the dashboard

```powershell
tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\server.py
```

Open **http://127.0.0.1:8080**

### Etsy authentication (first time)

```powershell
tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\upload_to_etsy.py --login
```

### Manual draft upload

```powershell
tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\upload_to_etsy.py --upload "path\to\piece_folder"
```

### Standalone image generation

```powershell
tooling\ad-creatives\.venv\Scripts\python.exe tooling\ad-creatives\generate.py "moody barn owl oil painting" --model nano-banana-pro --aspect 4:5
```

---

## 📋 Validated Niches (`niche_presets.json`)

| ID | Niche | Price | Format |
|----|-------|-------|--------|
| `japandi_plaster` | Japandi Plaster & Clay Abstract | $9.99 | Set of 3 prints |
| `dark_academia` | Moody Dark Academia & Gothic Oil | $14.99 | Gallery wall bundle (6–9) |
| `vintage_botanical` | Vintage Botanical Specimen Charts | — | Individual prints |

Default listing price in dashboard settings: **$5.99** (override per niche).

---

## ⚠️ Known Issues & Work In Progress

- **Shop not yet live** — pipeline being validated end-to-end before launch.
- **Mockup template library is thin** — only a few calibrated templates; more empty-frame gallery-wall mockups needed for bundle listings.
- **Market research scrapers** may be blocked by Etsy DataDome; falls back to estimated averages.
- **Upscaler binary** must be manually downloaded (not committed to repo).
- Only **GEMINI_API_KEY** required to start; OpenRouter/OpenAI keys are optional alternates.

---

## 🔗 Related Files

- `pipeline_guide.md` — operator step-by-step for first listing
- `tooling/upscale/README_windows.md` — Real-ESRGAN CLI reference
- `tooling/mockups/templates.json` — live mockup registry (edit via Mockup Studio, not by hand)
