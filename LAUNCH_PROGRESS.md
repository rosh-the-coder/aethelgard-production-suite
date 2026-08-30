# Aethelgard Art Co. — Launch Progress & Operator Roadmap

**Repo:** https://github.com/rosh-the-coder/aethelgard-production-suite  
**Updated:** 28 Jul 2026  
**Brand:** Aethelgard Art Co.  
**End goal:** Near-unattended listing creation (draft → publish path proven, then automate Drive; auto-publish only after drafts are trustworthy).

---

## Current progress (what is built)

| Area | Status | Notes |
|---|---|---|
| Local Production Suite (`dashboard` + `server.py` on `:8080`) | **Working** | Research → generate → finalize → catalog → draft upload |
| AI / Public Domain / Graphic Poster modes | **Working** | |
| Mockups / Mockup Studio | **Working** | Some templates may still need calibration |
| Catalog SEO + materials + photo drag-order | **Working** | Watermark kept off cover by default |
| Groq SEO pack + Artwork library bundles | **Built** | Needs `GROQ_API_KEY` in `~/.config/ai-images/env` |
| Pricing presets by product type | **Working** | Settings → single / poster / PD pack / bundle |
| PDF + Google Drive delivery | **Working** | Operator pastes Drive folder URL → Compile PDF |
| **Etsy Open API** Connect + Upload Draft | **Working** | Preferred path (no Seller Manager bot wall) |
| Browser / Playwright upload | **Legacy** | Ghost action in Catalog; use only if API fails |
| UI redesign (tokens / AppShell / Catalog detail) | **In progress** | See `docs/AETHELGARD_UI_SYSTEM.md` |
| Shop live / multi-listing publish | **Operator** | Publish canary from Shop Manager |
| Automated Drive upload | **Not built** | Still paste Drive link by hand |
| Auto-publish to live | **Not built** | Intentionally draft-only |

---

## You still need to do (checklist)

1. Add **`GROQ_API_KEY`** to `~/.config/ai-images/env`, then restart the suite (SEO pack + Suggest bundles).
2. Confirm **`ETSY_API_KEY` + `ETSY_SHARED_SECRET`**; Connect Etsy API if tokens expired.
3. For each listing: Drive folder → Compile PDF → Upload Draft (API) → review in Shop Manager (keep type **Digital**).
4. Publish **one canary** live when a draft looks perfect.
5. Fill subject/style on Etsy until API attributes ship.

---

## Recommended next builds (after UI polish)

1. Drive automation (folder + upload prints).
2. Etsy listing attributes via API.
3. Deeper keyword / competitor research → niches.
4. Batch SEO / batch upload.
5. Optional promote-draft / auto-publish with safety rails.
6. Separate project later: React/Next shell (do not mix with CSS-only redesign).

---

## UI system

- Design bible: [`docs/AETHELGARD_UI_SYSTEM.md`](./docs/AETHELGARD_UI_SYSTEM.md)
- Agent prompt: [`docs/UI_REDESIGN_PROMPT.md`](./docs/UI_REDESIGN_PROMPT.md)
