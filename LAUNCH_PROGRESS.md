# Aethelgard Art Co. — Launch Progress & Operator Roadmap

**Repo:** https://github.com/rosh-the-coder/aethelgard-production-suite  
**Updated:** 25 Jul 2026  
**Brand:** Aethelgard Art Co.  
**End goal:** Near-unattended listing creation (draft → publish path proven, then automate Drive + harden upload; auto-publish only after drafts are trustworthy).

---

## Current progress (what is built)

| Area | Status | Notes |
|---|---|---|
| Local Production Suite (`dashboard` + `server.py` on `:8080`) | **Working** | Operator UI for research → generate → finalize → catalog → draft upload |
| AI Generate mode | **Working** | Candidates → pick → finalize (upscale + print crops + mockups) |
| Public Domain mode | **Working** | Met Open Access search/import → PD pack finalize |
| Graphic Poster mode | **Working** | Real-type compose + recompose; local fonts under `tooling/upload/fonts/` |
| Mockups / Mockup Studio | **Working** | Perspective composites; some templates still need calibration |
| Catalog SEO edit | **Working** | Title / tags / description / price; Gemini title assist |
| PDF + Google Drive delivery | **Built, unused** | Operator pastes Drive folder URL → Compile PDF. **0** download PDFs in runs so far |
| Etsy login (Chrome CDP) | **Built** | Session in local `auth_state.json` (gitignored) |
| Upload Draft (Playwright) | **Built, unproven** | Creates **draft only**. **0** pieces with `uploaded_at` |
| Upload status polling | **Improved** | Dashboard can poll job completion (not just “process started”) |
| API preflight / honest errors | **Improved** | Generation failures surface real errors vs vague key alerts |
| Research honesty | **Improved** | Live vs estimate labeling when scrapers are blocked |
| Shop live / published listings | **Not started** | Shop shell + listing #1 still ahead |
| Automated Drive upload | **Not built** | Manual Drive folder is required for dry-run |
| Auto-publish to live shop | **Not built** | Intentionally draft-only until path is proven |

**On-disk snapshot (25 Jul 2026):** ~28 artwork runs · listing metadata present · **0** delivery PDFs · **0** recorded draft uploads · shop **not live**.

**Do not prioritize yet:** more art styles, more mockup templates, or big UI redesigns — until the dry-run → publish canary below is done.

---

## North star (your end goal)

**Target:** AI / suite produces listings with **minimal** management from you.

**Honest path to that:**

1. Prove the path once by hand (files → Drive → PDF → Etsy draft → you fix breaks).
2. Open the shop shell + policies.
3. Clean delivery branding (Aethelgard PDF / thank-you / links).
4. Align rights language (PD vs AI vs designed-by-you).
5. Publish **one** canary listing.
6. Automate Drive + harden draft upload.
7. Only then add **optional** auto-publish (or one-click “promote draft”) with safety rails.

Skipping #1–#5 makes “full automation” fragile and risky (wrong files, broken Drive links, rights mislabels, paid publish mistakes).

---

## Recommended order (do in sequence)

### Phase A — Operator work (this week)

#### Step 1 — One dry-run listing (highest priority)

Pick **one** finished piece (PD pack **or** graphic poster).

1. Open the suite: start `server.py`, open `http://127.0.0.1:8080`.
2. In **Catalog**, open a piece that already has print JPEGs (or finalize a new keeper first).
3. Create a Google Drive folder for that piece (e.g. `Aethelgard / dry-run / <piece-slug>`).
4. Upload the print JPEG folders/files into Drive.
5. Set share to **Anyone with the link** (Viewer).
6. Copy the folder share URL (`drive.google.com/...`).
7. In Catalog, click **Compile PDF**, paste the Drive URL, confirm.
8. Verify the PDF opens and every Drive link works in a private/incognito window.
9. Ensure Etsy seller login works from the suite (Login / auth status green).
10. Click **Upload Draft** for that piece. Watch the headed browser; intervene if selectors fail.
11. Open the draft in **Etsy Seller Dashboard / Shop Manager**.
12. Fix whatever broke (photos, digital file, title, tags, who-made-it, price, category).
13. **Do not publish yet** — save the draft only. Note every manual fix (this becomes the automation backlog).

**Done when:** One draft exists on Etsy that matches what you expect, with a working PDF attachment and working Drive downloads.

#### Step 2 — Open the shop shell (anytime alongside Step 1)

No perfect tooling required:

1. Create / open the Etsy shop for **Aethelgard Art Co.**
2. Upload logo + banner.
3. Write About / shop announcement.
4. Set digital download policies: delivery expectations, refunds, personal-use license language.
5. Leave listing #1 as draft until Step 5.

#### Step 3 — Fix delivery branding (best coding task after / during dry-run)

1. Confirm Settings thank-you note is Aethelgard-branded (not placeholder / old names).
2. Update PDF template copy if needed (shop name, clean thank-you, clear size/link instructions).
3. Re-run **Compile PDF** on the same dry-run piece with the same Drive folder.
4. Re-check links in incognito.

#### Step 4 — Rights / listing honesty

For each product type, decide and stick to it:

| Mode | Typical honesty |
|---|---|
| Public Domain pack | Restored/curated PD — **not** “I made this art” as original authorship |
| AI Generate | Disclose AI-assisted / digital creation per Etsy rules |
| Graphic Poster | Designed-by-you (composition/typography) if that is accurate |

Align Etsy’s **Who made it**, materials, and description with that decision. Do not ship PD as “I did” by default.

#### Step 5 — Publish listing #1 (QA canary)

Only after the draft looks right:

1. Photos / mockups correct  
2. SEO (title, tags, description) acceptable  
3. Price / quantity set  
4. PDF attached  
5. Drive links open for a stranger-with-link  

Then publish. Treat this listing as the canary: buy/download yourself if needed, confirm buyer experience.

---

### Phase B — Automation toward minimal management

Do **after** Phase A Step 5 succeeds.

#### Step 6 — Automate Google Drive

- Create folder per piece from the suite  
- Upload print files  
- Set “anyone with link”  
- Pass URL into Compile PDF automatically  

#### Step 7 — Harden draft upload

- Fix every failure noted in the dry-run  
- Stronger selectors / completion feedback  
- Reduce manual rescue to rare edge cases  

#### Step 8 — Minimal-management publish loop (later)

Only when drafts are consistently correct:

- One-click **Promote draft → live** (still reviewable), **or**  
- Guarded auto-publish with checklist (PDF present, Drive OK, rights fields set, price set)

**Still expect light management forever:** niche choice, occasional QC, policy/rights decisions, and Etsy UI breakage.

---

## Explicitly deferred

Until Phase A Steps 1–5 are done:

- More art styles / niches for volume  
- Large mockup-template expansion  
- Big dashboard UI redesigns  

---

## Coding backlog (when you ask the agent)

| Priority | Task | Depends on |
|---|---|---|
| P0 | Support dry-run friction (PDF branding #3, clearer Drive instructions) | Optional before Step 1; required before Step 5 polish |
| P1 | Drive API: folder create + upload + share link | Dry-run proven |
| P1 | Upload selector fixes from dry-run notes | At least one attempted Upload Draft |
| P2 | Rights presets per generator mode (PD / AI / poster) | Step 4 decisions |
| P3 | Optional promote-draft / guarded auto-publish | Reliable drafts + live shop |

---

## How to run the suite (quick)

```powershell
cd "f:\Apps\Etsy 2026\roshwillberich"
.\tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\server.py
```

Open `http://127.0.0.1:8080`.
