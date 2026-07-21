# Aethelgard Art Co. Production Suite — Technical & Product Handover

**Primary codebase:** `f:\Apps\Etsy 2026\roshwillberich`  
**Brand / UI label:** Aethelgard Art Co. — Production Suite **v1.2**  
**Upstream base:** Alek’s Artwork Orchestrator Claude skill (`Aleks/artwork-orchestrator`)  
**Evidence date:** 18 Jul 2026  
**Git history:** None present in workspace (no `.git` at root or project folders)

---

# 1. Executive summary

**What it is:** A local, Windows-first internal production suite that turns an artwork concept into print-ready digital files, lifestyle mockups, SEO listing copy, and an Etsy **draft** listing—orchestrated through a browser dashboard on `http://127.0.0.1:8080`.

**Problem it solves:** Creating sellable Etsy digital wall-art listings normally requires niche research, AI prompting, image generation, upscaling, multi-size cropping, mockup compositing, titles/tags/descriptions, file packaging, and a long Seller Manager form. This system collapses that into a guided pipeline with human checkpoints.

**Who it is for:** A solo operator (you) building the Aethelgard Art Co. digital-print shop. It is an **internal tool**, not a multi-tenant SaaS product. Docs state the shop is **not yet live**.

**Manual workflow reduced:** Research → generate variants → finalize prints → mockups → edit SEO → compile download PDF → push draft to Etsy.

**Automated:** Candidate image generation (3 stylistic variants), Real-ESRGAN 4× upscale, 300 DPI multi-size crops, perspective mockups (+ optional zoom GIF), niche-aware SEO scaffolding, Gemini title suggestions, PDF download-sheet generation, Playwright form-fill for draft listings.

**Still human:** Niche/concept choice, winner selection, title/tag/description review, Google Drive link for PDF delivery, Etsy login, selector-failure rescue during upload, and **all live publishing** (tool never auto-publishes).

**Completion level:** End-to-end **pipeline validated in testing** (research → generate → finalize → catalog). Draft upload automation exists but is fragile. **0 pieces** in `artwork-runs` currently have `uploaded_at`. Shop launch not evidenced.

---

# 2. Original problem and opportunity

**Before automation, a digital Etsy print listing typically required:**

1. Niche / keyword research (manual search, competitor browsing, optional paid tools like EverBee)
2. Concept + prompt writing for an image model
3. Generating multiple candidates and picking winners
4. Upscaling to print resolution
5. Cropping to common frame ratios at 300 DPI
6. Creating lifestyle mockups (often Canva / Photoshop)
7. Writing title (≤140 chars), ≤13 tags, long description
8. Packaging downloads (ZIP or Drive link under Etsy’s file-size limits)
9. Filling Etsy’s create-listing form (who/what/when, digital type, category, photos, files, price, qty, tags)
10. Saving draft, reviewing, then paying to publish

**Pain points:** Repetition across listings; inconsistent file naming and aspect ratios; SEO quality drift; mockup labor; upload form tedium; risk of shipping low-res or mockup-contaminated “print” files.

**Why an internal tool mattered:** You are validating niches (Japandi plaster, dark academia, botanical specimen) and need a repeatable factory before the shop goes live—not a generic AI image toy, but a production chain with review gates.

**Provenance:** Core generate → upscale → crop → SEO file layout comes from Alek’s Artwork Orchestrator skill/package in `Aleks/`. Your fork embeds that engine in a dashboard, Windows setup, richer mockups, research scrapers, and Playwright draft upload.

---

# 3. Product scope

| Capability | Status |
|---|---|
| Product / niche research (keywords, shop, listing capture) | **Partially implemented** (live scrape + mock/estimate fallbacks; listing analyzer Phase 1) |
| Idea generation | **Partially implemented** (niche presets + operator concept; not a free-form idea engine) |
| Design generation | **Implemented** (prompt-driven image gen) |
| Prompt generation | **Partially implemented** (presets + Faithful/Signature/Wildcard wrappers; agent/skill art-direction docs) |
| Image generation | **Implemented** (Gemini / OpenRouter / OpenAI via `generate.py`) |
| Image editing / processing | **Implemented** (trim margin, quality scan, optional signature sanitize) |
| Background removal | **Not implemented** |
| Upscaling | **Implemented** (Real-ESRGAN ncnn-vulkan 4×) |
| Resizing / print crops | **Implemented** (300 DPI size table) |
| Mockup generation | **Implemented** (perspective warp + lighting; GIF optional) |
| File naming | **Implemented** (run/piece slugs, `mockup_{template}.jpg`, print size names) |
| File packaging | **Partially implemented** (print folders + Drive-link PDF; no ZIP packager found) |
| Listing-title generation | **Implemented** (Gemini Flash suggestions + fallbacks) |
| Description generation | **Partially implemented** (niche templates on finalize; human edit in catalog) |
| Tag / keyword generation | **Partially implemented** (niche `starter_tags`; human edit) |
| Pricing assistance | **Partially implemented** (niche suggested prices + defaults; no dynamic pricing model) |
| Etsy authentication | **Implemented** (real Chrome + CDP → Playwright `storage_state`; **not** Etsy Open API OAuth) |
| Etsy listing creation | **Partially implemented** (Playwright UI automation → draft) |
| Image upload (listing photos) | **Partially implemented** (mockup JPGs via file input; manual fallback) |
| Digital file upload | **Partially implemented** (PDF preferred, else ≤5 print JPGs; manual fallback) |
| Draft creation | **Implemented** (intent + selectors; success not always guaranteed) |
| Publishing | **Not implemented** (draft only by design) |
| Scheduling | **Not implemented** |
| Database / history | **Partially implemented** (filesystem JSON + `listing_snapshots.json`; no SQL DB) |
| Batch processing | **Partially implemented** (multi-keeper finalize; sequential gen; no job queue) |
| Human review | **Implemented** (candidate pick, catalog edit, upload watch/intervene) |
| Error handling | **Partially implemented** (fallbacks, beeps, ENTER waits; upload API only confirms process launch) |
| Analytics / status tracking | **Partially implemented** (catalog tree, auth file presence, mockup job poll; weak upload completion feedback) |

---

# 4. End-to-end user journey

```
Open dashboard (:8080)
  → [optional] Market Research
  → Print Generator (concept → 3 candidates → pick + title)
  → Finalize (upscale → prints → mockups)
  → Catalog (edit SEO → optional PDF)
  → Etsy login (once)
  → Upload Draft (Playwright headed + human rescue)
  → Human reviews draft in Etsy Shop Manager → publish manually
```

### Step A — Open app

| | |
|---|---|
| **User** | Runs `tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\server.py`; opens `http://127.0.0.1:8080` |
| **System** | `ThreadingHTTPServer` serves `dashboard.html` |
| **Failure** | Missing venv / Playwright browsers / keys |

### Step B — Research (optional)

| Path | User | System | Output | Human gate |
|---|---|---|---|---|
| Niche preset | Click “Load Preset Prompt” | Fills concept + style; jumps to Generator | Prompt spine | Choose niche |
| Keyword search | Enter query | `etsy_research.py` Playwright scrape | Opportunity cards | Treat scores as estimates if blocked |
| Shop analyzer | Enter shop name | `shop_analyzer.py` or bookmarklet capture | KPIs / listings | Prefer bookmarklet if DataDome |
| Listing analyzer | Bookmarklet on listing page | `listing_capture.py` estimates | Snapshot JSON | Phase 1 estimates only |

### Step C — Generate candidates

| | |
|---|---|
| **User** | Concept, style spine, aspect, model → Generate |
| **System** | Gemini title suggestions; runs Faithful / Signature / Wildcard via `generate.py` into `artwork-runs/<slug>/_candidates/` |
| **Output** | 3 PNGs + suggested titles |
| **Human** | Select keeper(s); apply title pill; set trim (e.g. 3%) |

### Step D — Finalize

| | |
|---|---|
| **User** | Finalize Selected Winner |
| **System** | Copy source → `master.png`; write `meta.json`; `artwork.py finalize` (4× upscale, crops, SEO files); `generate_mockups.py` |
| **Saved** | Piece folder: prints, mockups, `listing.json`, `seo.md` |
| **Failure** | Per-keeper error returned; incomplete pieces possible |

### Step E — Catalog review

| | |
|---|---|
| **User** | Browse tree; preview mockups/GIF; edit title/tags/desc/price/qty; save |
| **System** | `POST /api/save` updates `meta.json` + `listing.json` + `seo.md` |

### Step F — PDF delivery (optional)

| | |
|---|---|
| **User** | Compile PDF + paste Google Drive folder URL |
| **System** | `generate_pdf_links.py` (Playwright HTML→PDF) |
| **Why** | Bypass large digital-file limits by shipping a small branded PDF that links to Drive |
| **Evidence** | **0 PDFs** currently under `artwork-runs` |

### Step G — Auth + draft upload

| | |
|---|---|
| **User** | Etsy Authentication → sign in real Chrome → ENTER; then Upload Draft |
| **System** | Saves `auth_state.json`; launches headed Playwright; fills create-listing form; tries “Save as draft” |
| **Human** | Any failed selector → beep + ENTER after manual fix; **publish is outside the tool** |
| **Evidence** | `auth_state.json` exists (~15KB); **0** `uploaded_at` fields in current runs |

**Branching:** Skip research; regenerate mockups; Mockup Studio calibrate templates; multi-frame gallery placements; upload without PDF (falls back to ≤5 print JPGs).

---

# 5. Technical architecture

| Layer | Choice |
|---|---|
| Frontend | Single-page `dashboard.html` (~4.5k lines) + vanilla JS |
| Backend | Python `http.server.ThreadingHTTPServer` (`server.py`, ~1.3k lines) |
| Runtime | Python 3.10+ venv at `tooling/ad-creatives/.venv` |
| Styling | Inline CSS design tokens in dashboard |
| Database | **None** — filesystem JSON + folders |
| Auth (Etsy) | Browser session cookies via Playwright `storage_state` |
| Auth (app) | Localhost only; no user accounts |
| Storage | Local disk under `artwork-runs/` |
| External APIs | Google Generative Language (Gemini image + Flash titles); optional OpenRouter/OpenAI |
| AI models | See §8 |
| Background jobs | In-process mockup job dict + lock; upload/login in new console windows |
| Queues / schedulers | **None** |
| File pipeline | generate → sanitize/trim → Real-ESRGAN → Pillow crops → mockup warp → optional PDF |
| Deployment | Local only; no Docker/cloud config found |
| Logging | stdout / console prints |
| Monitoring | **None** |
| Testing | No project test suite found (only vendored package tests) |

**Architecture diagram (actual):**

```
Browser UI (dashboard.html)
    → Local REST API (server.py :8080)
        → Subprocess: etsy_research / shop_analyzer
        → Subprocess: generate.py (Gemini/OpenRouter/OpenAI)
        → Gemini REST: title suggestions
        → Subprocess: artwork.py finalize
              → realesrgan-ncnn-vulkan.exe
              → Pillow print crops + meta/listing/seo files
        → Subprocess / async job: generate_mockups.py (+ detect_frames)
        → Subprocess: generate_pdf_links.py (Playwright PDF)
        → New console: upload_to_etsy.py (Playwright headed)
              → Etsy Seller UI (NOT Open API)
        → Filesystem: artwork-runs/, templates.json, auth_state.json, listing_snapshots.json
```

---

# 6. Repository structure

```
Etsy 2026/
├── Aleks/                          # Upstream skill + Alek content (reference)
│   └── artwork-orchestrator/       # Original Claude skill package
└── roshwillberich/                 # YOUR production fork + ops UI
    ├── README.md                   # Upstream-style skill README (inherited framing)
    ├── roshwillberich.md           # Architectural manifest (AI/operator map)
    ├── pipeline_guide.md           # Operator walkthrough
    ├── setup.ps1 / setup.sh        # Venv, deps, upscaler, keys scaffold
    ├── requirements.txt            # google-genai, openai, requests, Pillow
    ├── .claude/skills/artwork-orchestrator/
    │   └── scripts/artwork.py      # Finalize: upscale → crop → index
    └── tooling/
        ├── upload/                 # Dashboard + research + Etsy Playwright
        ├── ad-creatives/generate.py
        ├── mockups/                # Compositor, PDF, templates, detect_frames
        ├── upscale/                # Real-ESRGAN models (+ binary downloaded)
        └── digital-product-research/artwork-runs/
```

| Important file | Role |
|---|---|
| `server.py` | REST orchestration hub |
| `dashboard.html` | All operator UX |
| `upload_to_etsy.py` | Login + draft fill |
| `etsy_research.py` / `shop_analyzer.py` / `listing_capture.py` | Research + estimates |
| `niche_presets.json` | Validated niches, tags, prices |
| `generate.py` | Multi-provider image CLI |
| `artwork.py` | Deterministic print finalize |
| `generate_mockups.py` | Perspective mockups + GIF |
| `generate_pdf_links.py` | Drive-link PDF |
| `templates.json` | Mockup registry (21 entries; ~6 calibrated) |

---

# 7. Data model

No relational DB. Entities are folders + JSON.

### Run

- **Location:** `artwork-runs/<run_slug>/`
- **Files:** optional `_candidates/`, `run.json`, `index.md`, piece folders
- **Fields (`run.json`):** `run_dir`, `generated_at`, `upscaler`, `piece_count`, `pieces[]`

### Piece / Design

- **Location:** `artwork-runs/<run>/<piece_slug>/`
- **Required for upload:** `meta.json`, `listing.json`
- **Assets:** `master.png`, `prints/` or `*-prints/`, `mockup_*.jpg`, optional GIF/PDF

### `meta.json` (representative fictional example)

```json
{
  "run_dir": "tooling/digital-product-research/artwork-runs/example_japandi_arches",
  "title": "Warm Plaster Arch Printable Wall Art",
  "slug": "warm-plaster-arch-printable-wall-art-faithful",
  "source_image": ".../master.png",
  "orientation": "portrait",
  "sizes": ["4x6", "5x7", "8x10", "11x14"],
  "model": "nano-banana-pro",
  "prompt": "painted abstract plaster texture art with organic arches...",
  "upscale": 4,
  "price": "5.99",
  "quantity": "999",
  "trim_margin": 0.03,
  "quality_warnings": [],
  "seo": {
    "title": "Warm Plaster Arch Printable Wall Art, Japandi Digital Print",
    "tags": ["japandi plaster art", "textured canvas print"],
    "description": "Welcome to Aethelgard Art Co.! ..."
  },
  "finalized_at": "2026-07-12T18:00:00Z",
  "uploaded_at": null,
  "mockup_prefs": { "disabled_mockups": [], "include_zoom_gif": true }
}
```

### `listing.json`

```json
{
  "title": "Warm Plaster Arch Printable Wall Art, Japandi Digital Print",
  "tags": ["japandi plaster art", "wabi sabi print"],
  "description": "High-resolution 300 DPI digital print..."
}
```

### Auth state

- **File:** `tooling/upload/auth_state.json` (Playwright cookies + origins)
- **Status signal:** file exists ⇒ UI shows authenticated (cookie validity not checked)

### Niche preset

- Fields: `id`, `name`, `summary`, `opportunity`, `suggested_price`, `typical_format`, `prompt_preset`, `starter_tags[]`

### Mockup template

- Fields: `name`, `image`, `orientation`, `aspect`, `tags`, `quad`/`quads`/`box`, `layout`, `needs_calibration`, `source`

### Listing snapshot

- Appended via capture import to `listing_snapshots.json` (Phase 1 analyzer history)

**Observed inventory:** 7 runs, **11** pieces with `meta.json`, **36** mockup JPGs, **0** PDFs, **0** uploaded markers.

---

# 8. AI features

| Use | Provider / model | Status |
|---|---|---|
| Image generation | Gemini `gemini-3-pro-image` / `gemini-3.1-flash-image`; OpenRouter Gemini/GPT-image; OpenAI `gpt-image-2` / `gpt-image-1-mini` | **Implemented** |
| Style variants | Faithful / Signature (+ optional style refs) / Wildcard prompt wrappers | **Implemented** |
| SEO title suggestions | `gemini-1.5-flash` via Generative Language REST | **Implemented** (8s timeout; hardcoded fallbacks) |
| Description / tags | Niche templates + human edit (not a dedicated LLM description agent in finalize) | **Partial** |
| Research “AI” | Heuristic / mock opportunity scores when blocked | **Mocked fallback** |
| Higgsfield routing in `generate.py` | Optional import; **`higgsfield.py` absent** → inactive | **Abandoned / unused** |
| Code generation during build | Cursor-assisted development (process, not runtime) | Development practice |

**Title prompt structure (evidence):** Etsy SEO expert; 3 titles; &lt;130 chars; no numbering; inject concept + deduced style; high-converting keyword examples.

**Image settings:** Default aspect `4:5`; default model alias `nano-banana-pro`; Gemini retry if `image_config` unsupported (aspect appended to prompt). No exponential backoff.

**Human review:** Always—candidate pick, title application, catalog edit before upload.

**Cost:** Operator’s API usage only; keys in `~/.config/ai-images/env` (not in repo).

---

# 9. Image and asset pipeline

1. **Prompt** → `generate.py` → PNG candidates
2. **Human pick** → copy to piece `master.png`
3. **Optional trim** (`trim_margin` %) + quality scan / corner signature sanitize
4. **Real-ESRGAN** `realesrgan-x4plus` **4×**
5. **Center-crop + Lanczos** to print sizes @ **300 DPI**, JPEG quality **100**
6. **Portrait sizes:** 4×6, 5×7, 8×10, 11×14 px tables in `artwork.py`
7. **Landscape sizes:** 12×9, 20×16, 24×18, 36×24, A2
8. **Mockups:** Pillow perspective (8-coeff), multiply/soft-light/screen lighting, ~2048px listing width, JPEG 95; optional Ken Burns GIF
9. **Digital delivery:** Prefer branded PDF with Drive link; else ≤5 print JPGs on upload
10. **Libraries:** Pillow, OpenCV (`detect_frames`), Playwright (PDF + Etsy), Real-ESRGAN ncnn-vulkan

**Not found:** Dedicated background removal, colour-profile management beyond JPEG DPI metadata, ZIP packaging, automated duplicate-content hash checks.

---

# 10. Etsy integration

**Critical fact:** There is **no Etsy Open API / OAuth application integration** in project source. Integration is **Playwright browser automation** against Seller Manager UI.

| Topic | Reality |
|---|---|
| API version | N/A (UI automation) |
| Auth | Real Chrome + remote debugging → export cookies to `auth_state.json` |
| Scopes | N/A |
| Token refresh | Re-login when redirected to sign-in |
| Shop ID | Implicit via logged-in session (`/your/shops/me/...`) |
| Draft creation | Navigate create listing; fill fields; click Save as draft |
| Publishing | **Not automated** |
| Images | Mockup JPGs to first `input[type=file]` |
| Digital files | PDF or print JPGs to last file input when ≥2 inputs |
| Rate limits | Soft-handled via delays; IP/DataDome blocks documented |
| Human confirmation | Built-in fallbacks for every fragile step |
| Status | **Partially working / fragile**; selectors can drift; dashboard “success” = process launched |

Hardcoded listing attributes when automation succeeds: Who made = “I did”; What = “A finished product”; When = “Made to order”; type = Digital; category search = “Digital Prints”.

---

# 11. Metadata and SEO generation

| Field | How produced | Limits / rules |
|---|---|---|
| Title | Gemini suggestions + human pick/edit; finalize appends SEO suffix if not overridden | Prompt asks &lt;130 chars; skill docs cite ≤140 |
| Description | Niche-matched welcome + size list on finalize; catalog editable | Mentions 300 DPI, ratios, digital nature |
| Tags | Niche `starter_tags` (13) or defaults; editable | Skill: ≤13 tags, ≤20 chars (enforcement mostly by convention) |
| Category | Upload hardcodes Digital Prints search | Manual if selector fails |
| Price | Default `5.99` on finalize; niches suggest 5.99 / 9.99 / 14.99; upload fallback `4.99` if missing | Operator-set |
| Quantity | Default `999` | Operator-set |
| Attributes / materials / occasion / variations | **Not systematically generated** | Manual on Etsy if needed |
| Personalisation | **Not implemented** | |

**Duplicate-content prevention:** Not automated beyond human review and niche keyword strategies in presets.

---

# 12. Automation and orchestration

| Mechanism | Detail |
|---|---|
| Control plane | Synchronous HTTP handlers + subprocesses |
| Mockup jobs | In-memory `MOCKUP_JOBS` with poll endpoint; pruned ~30 |
| Capture buffers | Process globals (lost on restart) |
| Parallelism | `ThreadingHTTPServer`; image variants generated **sequentially** |
| Retries | Limited (Gemini aspect fallback; upload manual loops) |
| Idempotency | Run dirs get `_N` suffixes; piece slugs uniquified |
| Resume | Re-run finalize/mockups/upload on piece folder; no durable workflow engine |
| Cancellation | Not first-class |
| Publish prevention | Draft-only automation |

**State table (operator-centric):**

| State | Meaning |
|---|---|
| Concept only | Research / generator form |
| Candidates ready | `_candidates/` populated |
| Finalized | Piece folder + prints + meta |
| Mockups ready | `mockup_*.jpg` present |
| SEO edited | Catalog save |
| PDF ready | `Download_Links_*.pdf` (optional) |
| Auth OK | `auth_state.json` exists |
| Draft attempted | Playwright run; `uploaded_at` if script completes |
| Live | Manual publish outside tool |

---

# 13. Interface and UX

**Screens (nav):** Market Research · Print Generator · Catalog & Uploads · Mockup Studio · Presets & Settings

**Patterns:** Gold selection highlight on candidates; toast notifications; lightbox; gallery composer modal; mockup job progress; auth status in navbar; headed browser for upload so operator can intervene.

**Design decisions visible in code:** Single local “Production Suite” composition; niche cards as research shortcuts; Faithful/Signature/Wildcard as creative A/B; Mockup Studio with normalized quad handles + magnifier; PDF+Drive as pragmatic digital delivery; draft-only language to avoid accidental fees/publish.

**Accessibility / responsive:** Desktop-operator oriented; not a polished multi-device product UI. Settings shop name is readonly (“Aethelgard Art Co.”).

---

# 14. Security and reliability

| Area | Practice / risk |
|---|---|
| API keys | Local `~/.config/ai-images/env`; gitignored patterns for `.env` |
| Etsy session | Cookies in `auth_state.json` + Chrome profile dirs — **sensitive; do not commit/share** |
| Access control | Localhost only; no multi-user ACL |
| Input validation | Path existence checks; limited schema validation |
| Accidental publish | Draft-only design |
| Upload feedback gap | API returns success when console **starts**, not when draft saves |
| Research integrity | Mock data when blocked — must not be treated as live analytics |
| Backup | Filesystem folders only |
| Tech debt | Selector fragility; thin calibrated mockup library; no tests; no git; settings not fully persisted |

---

# 15. My contribution

You did **not** invent the entire image finalize skill from scratch. You **adopted Alek’s Artwork Orchestrator**, then **owned the productization** into a shop-specific production system:

- Chose niches, brand (Aethelgard Art Co.), pricing defaults, and pipeline order
- Defined human-in-the-loop gates (pick winners, review SEO, draft-only upload)
- Drove Cursor-assisted implementation of dashboard, server APIs, mockup studio, scrapers, PDF workaround, Playwright upload
- Prompt-engineered niche presets and SEO title instructions
- Integrated multiple APIs/tools (Gemini, Real-ESRGAN, Playwright, Pillow/OpenCV)
- Debugged Windows paths, anti-bot research blocks, and Etsy UI automation failure modes
- Validated with real runs (owl pipeline tests, japandi/plaster pieces, mockup outputs)

**Accurate framing:** Founder-operator / applied AI builder using AI-assisted coding to ship an internal automation product—not “I only prompted,” and not “senior platform engineer who designed a multi-tenant Etsy SaaS.”

---

# 16. Development process

*(Reconstructed from docs, code comments, folder dates, and Aleks package—**no git history**.)*

1. **Upstream:** Alek Artwork Orchestrator skill — concept → generate → upscale → crop → SEO files (Claude Code skill).
2. **Fork / Windows port:** `setup.ps1`, Playwright install, path/`utf-8-sig` env loading.
3. **Ops UI:** Local dashboard + `server.py` REST (v1.2).
4. **Mockup expansion:** From thin Aleks stub to perspective lighting engine + Studio + Higgsfield template library.
5. **Research layer:** Keyword/shop scrapers → blocked by DataDome → bookmarklets + mock estimates (“EverBee-style Phase 1”).
6. **Upload:** Playwright draft automation with manual rescue; Chrome CDP login to reduce bot flags.
7. **Delivery workaround:** Drive-link PDF for digital files.
8. **Current:** Pipeline in active testing; shop not live; upload end-to-end not evidenced by `uploaded_at` in runs.

---

# 17. Challenges and solutions

| Problem | Root cause | Solution / workaround | Trade-off |
|---|---|---|---|
| Etsy blocks scrapers | DataDome / bot detection | Bookmarklets from logged-in browser; mock research fallback | Estimates ≠ truth |
| Playwright login flagged | Automation fingerprint | Real Chrome + CDP cookie export | Manual login step |
| Etsy UI selectors drift | Seller Manager DOM changes | `fill/click_with_fallback` + ENTER | Not unattended |
| Large print packs vs Etsy limits | File size constraints | PDF → Google Drive link | Extra Drive ops; PDF gen unused in current runs |
| AI images include borders/signatures | Model artifacts | Trim margin + `image_sanitize` | Extra QC knobs |
| AI draws mockup frames in print | Prompt wording | No-text / no-frame spine in skill | Prompt discipline required |
| Official Etsy API complexity | App review / OAuth | UI automation instead | Fragility vs API stability |
| Long mockup compositing | Multi-template warp | Async job + poll | In-memory jobs die on restart |
| Thin template set | Calibration labor | Studio + auto-detect; many `needs_calibration` | Only ~6/21 calibrated |

---

# 18. Outputs and impact

**Verified from disk (18 Jul 2026):**

| Metric | Value |
|---|---|
| Artwork runs | **7** |
| Finalized pieces (`meta.json`) | **11** |
| Mockup JPGs | **36** |
| Mockup templates registered | **21** (~**6** calibrated) |
| Download PDFs in runs | **0** |
| Pieces with `uploaded_at` | **0** |
| Niche presets | **3** |
| Dashboard version | **v1.2** |
| Workflow stages in guide | **6** (research → generate → finalize → review → PDF → draft upload) |

**Placeholders (not inventable from repo):**

- [X minutes saved per listing]
- [X% reduction in manual work]
- [X successful Etsy draft uploads]
- [X cost per listing in API spend]

Do not claim live GMV or published listing counts until Shop Manager evidence exists.

---

# 19. Current state and roadmap

| Area | State |
|---|---|
| Local dashboard + generate + finalize + mockups | **Stable enough for testing** |
| Niche presets + catalog editing | **Working** |
| Playwright draft upload | **Functional but fragile** |
| Keyword/shop research live data | **Fragile / often estimated** |
| Listing analyzer | **Phase 1 partial** |
| PDF Drive delivery | **Implemented, unused in current runs** |
| Etsy Open API | **Not connected** |
| Auto-publish / scheduling / multi-user | **Not built** |
| Higgsfield module hook | **Dead code path** |
| Shop live launch | **Not yet** |

**Recommended next priorities:** (1) harden upload selectors + completion webhook to dashboard, (2) calibrate more empty-frame templates, (3) exercise PDF→draft path end-to-end, (4) add git + secrets hygiene for `auth_state.json`, (5) consider official Etsy API if scaling beyond personal use, (6) replace mock research with transparent “estimate mode” UI labeling.

---

# 20. CV-ready content

### A. Primary title

**Aethelgard Art Co. — AI-Assisted Etsy Digital Art Production Suite**

### B. Alternative titles

- **Applied AI:** End-to-End Generative Art Pipeline with Human-in-the-Loop Listing Automation
- **Design Engineer:** Production Dashboard for AI Print Generation, Mockup Compositing & Listing Prep
- **Product Designer:** Internal Operator Tool for Niche Research → Asset Factory → Draft Publishing
- **Full-stack / Frontend:** Local Python API + Single-Page Production Console for Etsy Digital Goods

### C. Two-sentence description

Built a local AI production suite that turns a wall-art concept into 300 DPI multi-size prints, lifestyle mockups, SEO copy, and an Etsy draft listing. Combined multi-provider image generation, Real-ESRGAN upscaling, perspective mockup compositing, and Playwright seller-form automation with explicit human review gates.

### D. Eight ATS-friendly bullets

- Designed and shipped an end-to-end internal tool covering niche research, AI image generation, print finalization, mockups, SEO editing, and Etsy draft upload.
- Orchestrated a multi-step asset pipeline: Gemini/OpenAI image generation → 4× Real-ESRGAN upscale → 300 DPI aspect crops → perspective mockups.
- Built a localhost Python REST server and single-page dashboard to operate the full production workflow.
- Implemented Playwright-based Etsy seller automation for session auth and draft listing creation with manual fallback handling.
- Created Mockup Studio with calibrated frame quads, OpenCV detection assist, and lighting-aware compositing.
- Added SEO assistance via Gemini title suggestions plus niche preset tags, descriptions, and pricing defaults.
- Worked around Etsy digital file limits using a branded PDF that links to Google Drive downloads.
- Handled anti-bot research constraints with bookmarklet capture and transparent estimate fallbacks instead of fake “accurate” scrapers.

### E. Four-bullet version

- Built an AI-assisted Etsy digital-print factory (research → generate → finalize → mockups → draft upload).
- Integrated Gemini/OpenAI image APIs, Real-ESRGAN, Pillow/OpenCV mockups, and Playwright seller automation.
- Designed human-in-the-loop review so listings stay draft-only until manual publish.
- Productized an upstream Claude skill into a Windows operator dashboard for Aethelgard Art Co.

### F. Technical skills

Python, REST APIs, HTML/CSS/JS, Playwright, Pillow, OpenCV, filesystem data modeling, local tooling, Windows PowerShell setup

### G. AI / automation skills

Prompt engineering, multi-provider image generation, SEO generation, human-in-the-loop workflows, browser automation, pipeline orchestration

### H. Product-design skills

Operator UX, workflow mapping, niche strategy, review/approval gates, internal-tool IA, pragmatic delivery workarounds

### I. APIs and tools

Google AI Studio / Gemini, OpenAI Images, OpenRouter, Real-ESRGAN, Playwright, Etsy Seller Manager (UI), Cursor

### J. Impact line

Automated **[6]** documented production stages for digital Etsy prints; validated on **11** finalized pieces and **36** mockups in testing; shop launch and draft-upload success rate: **[measure after first live drafts]**.

### K. ATS keywords

AI automation, generative AI, Playwright, Python, REST API, dashboard, image processing, Real-ESRGAN, Etsy, SEO, human-in-the-loop, digital products, mockups, internal tools, workflow orchestration

---

# 21. Portfolio case study

**Overview**  
Aethelgard Art Co. Production Suite is a local internal system that manufactures digital wall-art listings for Etsy—from niche prompt to draft listing—without auto-publishing.

**Problem**  
Digital print sellers repeat the same research, generation, print-prep, mockup, SEO, and upload steps; inconsistency and time cost block scale.

**Opportunity**  
AI image models + deterministic print finishing + operator UI can compress listing creation while keeping quality control.

**My role**  
Creator and product owner: requirements, workflow design, stack choices, Cursor-assisted build, validation, iteration. Extended Alek’s Artwork Orchestrator into a full ops suite.

**Users**  
Solo shop operator (pre-launch).

**Constraints**  
Local Windows machine; API costs; Etsy anti-bot; no official API integration; draft-only safety; thin mockup library.

**Workflow mapping**  
Research → Generate (3 variants) → Human pick → Finalize prints → Mockups → Edit SEO → Optional Drive PDF → Playwright draft → Manual publish.

**Product design**  
Tabbed production console; niche cards; explicit review before finalize/upload; headed automation for trust.

**Architecture**  
SPA + Python localhost API + subprocess workers + filesystem catalog.

**AI implementation**  
Multi-provider images; Flash titles; niche-templated copy; human always final.

**Etsy integration**  
Session cookies + Seller UI automation (not Open API).

**Iteration**  
Scraper → bookmarklet/estimates; skill CLI → dashboard; thin mockups → studio + lighting engine; direct files → Drive PDF path.

**Outcome**  
Working test pipeline with multiple finalized pieces/mockups; shop not live; upload path built but not yet evidenced by saved upload timestamps.

**Lessons**  
Anti-bot reality forces hybrid automation; draft-only is a product feature; filesystem JSON is enough until scale; selectors need continuous maintenance.

**Next steps**  
Harden upload selectors + completion webhook to dashboard; calibrate more empty-frame templates; first verified draft uploads; then launch niche SKUs.

*(Avoid sharing prompts that are commercially sensitive, `auth_state.json`, or private Drive links in public portfolios.)*

---

# 22. Interview preparation

**30-second pitch**  
“I built a local production suite for my Etsy digital-art shop that takes a concept through AI image generation, print-ready upscaling and cropping, mockup compositing, SEO drafting, and Playwright-assisted draft upload—with me still approving creative and never auto-publishing.”

**90-second explanation**  
“Listing digital prints is a factory problem: research, generate, finish files, mockups, metadata, upload. I started from an open Artwork Orchestrator skill for generate→upscale→crop, then built a Windows dashboard and Python API around it. The UI runs research tools, generates Faithful/Signature/Wildcard candidates, finalizes 300 DPI sizes, composites mockups, and pushes an Etsy draft via headed Playwright using a real Chrome login session. Research uses scrapers with honest estimate fallbacks when Etsy blocks bots. The shop isn’t live yet; I’ve validated the asset pipeline on multiple test pieces.”

**Five-minute technical walkthrough**  
1. Dashboard architecture (`server.py` routes)  
2. `generate_run_candidates` + model aliases  
3. `artwork.py` finalize + Real-ESRGAN  
4. Mockup perspective math + Studio calibration  
5. SEO/title Gemini path + niche presets  
6. Why Playwright UI vs Open API  
7. Draft-only + manual fallback design  
8. Known fragility and next rebuild choices

**Why build it?**  
To remove repetitive production work before launching Aethelgard Art Co., and to learn applied AI systems by shipping a real workflow—not demos.

**Did Cursor build this for you?**  
“Cursor accelerated implementation, but I defined the workflow, niches, acceptance criteria, integrations, and failure handling. I still had to validate outputs, debug Etsy/browser issues, and decide what stays human.”

**How much code do you understand?**  
“I can walk the request path from each dashboard action through subprocesses to files on disk, explain the finalize and mockup math at a practical level, and debug upload/auth failures. I didn’t invent Real-ESRGAN or Etsy’s backend—I integrated and productized them.”

**Personal technical decisions?**  
Local Python server vs heavier framework; filesystem catalog vs DB; Playwright UI vs Open API; draft-only; Drive PDF workaround; Faithful/Signature/Wildcard; bookmarklets after scraper blocks; Windows-first setup.

**Hardest integration?**  
Etsy: anti-bot research blocks and fragile Seller Manager automation, solved with CDP login, headed runs, and human rescue loops.

**Production rebuild changes?**  
Official Etsy API if eligible; durable job queue; real upload completion events; stricter estimate labeling; tests for finalize/upload; secret store; calibrated mockup library as a first-class asset pack.

**How validate AI outputs?**  
Visual candidate review; trim/QC warnings; catalog inspection of prints/mockups; SEO edit before upload; draft review in Shop Manager before paid publish.

**Business value?**  
Compresses listing production time and standardizes print/SEO quality so a solo seller can launch and iterate niches faster—with lower risk of bad files or accidental publish. Exact ROI: **[measure after live listings]**.

---

# 23. Reconstruction context for another AI

```yaml
product_name: Aethelgard Art Co. Production Suite (roshwillberich)
one_line: Local Windows dashboard that turns wall-art concepts into 300DPI prints, mockups, SEO, and Etsy draft listings.
problem: Manual Etsy digital-print production is slow, repetitive, and inconsistent (research→generate→print prep→mockups→SEO→upload).
target_user: Solo pre-launch shop operator (Aethelgard Art Co.); internal tool, not SaaS.
core_workflow: Research(optional) → Generate 3 variants → Human select/title → Finalize(upscale+crops) → Mockups → Edit SEO → Optional Drive PDF → Playwright draft upload → Human publish.
features:
  implemented: [dashboard_v1.2, niche_presets, multi_provider_image_gen, realesrgan_4x, print_crops_300dpi, mockup_compositor, mockup_studio, gemini_title_suggestions, catalog_edit, chrome_cdp_login, playwright_draft_upload]
  partial: [keyword_research_live, shop_scrape, listing_analyzer_phase1, pdf_delivery_unused_in_runs, upload_selector_automation]
  mocked: [research_opportunity_scores_when_blocked, sales_revenue_estimates]
  not_implemented: [etsy_open_api, auto_publish, scheduling, background_removal, zip_packager, multi_user_auth, cloud_deploy]
architecture: Browser SPA → Python ThreadingHTTPServer :8080 → subprocess workers → filesystem JSON catalog
stack: [Python3, Pillow, OpenCV, Playwright, Real-ESRGAN-ncnn-vulkan, vanilla HTML/JS, Gemini, optional OpenAI/OpenRouter]
apis:
  used: [Google Generative Language Gemini image+flash, OpenAI Images optional, OpenRouter optional]
  etsy: "Playwright Seller UI automation ONLY — no official Etsy API/OAuth in project code"
ai_models:
  image_aliases: [nano-banana-pro, nano-banana-2, or-nano-banana-pro, or-gpt5-image, gpt-image-2, ...]
  titles: gemini-1.5-flash
data_entities: [Run, Piece/meta.json, listing.json, niche_preset, mockup_template, auth_state.json, listing_snapshot]
key_paths:
  root: f:/Apps/Etsy 2026/roshwillberich
  server: tooling/upload/server.py
  ui: tooling/upload/dashboard.html
  upload: tooling/upload/upload_to_etsy.py
  generate: tooling/ad-creatives/generate.py
  finalize: .claude/skills/artwork-orchestrator/scripts/artwork.py
  mockups: tooling/mockups/generate_mockups.py
  runs: tooling/digital-product-research/artwork-runs/
  upstream: f:/Apps/Etsy 2026/Aleks/artwork-orchestrator/
implementation_status: "Pipeline testable end-to-end for assets; shop not live; 11 pieces/36 mockups on disk; 0 uploaded_at; 0 PDFs in runs; auth_state.json present"
my_responsibilities: [workflow_owner, niche_strategy, product_UX, Cursor-assisted_build, integrations, validation, human_gates]
challenges: [DataDome_blocks, selector_fragility, file_size_limits, AI_artifacts, no_git_history]
outputs_verified: {runs: 7, pieces: 11, mockups: 36, templates: 21, calibrated_templates_approx: 6, pdfs: 0, uploaded_markers: 0}
metrics_placeholders: ["minutes_saved_per_listing", "draft_upload_success_rate", "api_cost_per_listing"]
technical_debt: [fragile_etsy_selectors, upload_success_means_process_started, in_memory_jobs, thin_calibrated_templates, estimate_research_misuse_risk, secrets_in_auth_state, no_tests, no_git]
roadmap: [harden_upload_completion, calibrate_templates, verify_first_drafts, consider_etsy_open_api, git+secrets_hygiene, clearer_estimate_UI]
cv_keywords: [AI automation, generative AI, Playwright, Python, REST, dashboard, Real-ESRGAN, Etsy, SEO, human-in-the-loop, internal tools]
do_not_claim: [live_shop_GMV, official_etsy_api_integration, auto_publishing, accurate_everbee_sales, background_removal]
security_note: Never commit or paste auth_state.json cookies, API keys, or Chrome profile data.
```

---

**Bottom line for CV/portfolio honesty:** This is a substantial **internal AI production system** with a real operator UI and asset pipeline, built by extending an upstream skill and integrating generation, print finishing, mockups, and draft upload. It is **pre-launch**, **local**, and **draft-only**; treat research numbers as estimates when scrapers are blocked, and do not claim Etsy Open API or verified live upload volume until those appear in evidence.
