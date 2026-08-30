# Aethelgard UI System — Design Bible

> Drop this file into the Aethelgard repo as `docs/UI_SYSTEM.md`.
> Treat it as law for any visual redesign agent or human pass.

## Mission

Ship a production-grade SaaS UI for an Etsy listing automation suite.
Look senior: calm hierarchy, clear primary actions, consistent density.
**Do not break workflows, API calls, upload logic, or page/view order.**

## Stack context

| Layer | Reality |
|---|---|
| Backend | Python server |
| Frontend | Monolith `dashboard.html` (+ linked CSS/JS as present) |
| Accent | Warm gold/tan — `--primary: #c5a880` |
| Fonts today | Outfit / Inter base — refine into Display / Sans / Mono roles |

**Out of scope for redesign passes:** new features, Next.js migration, Etsy API behavior changes.

## Non-negotiables

1. **Visual / CSS / layout only** unless a tiny markup wrapper is required for styling.
2. **Preserve functional integrity:** every `onclick`, `/api/*` call, view name, and upload sequence stays exactly as-is.
3. **One primary CTA per view.** Secondary actions are quieter.
4. **Shared tokens + shared primitives** — no one-off colors/fonts per view.
5. **Do not clone CareerOS.** Same craft (tokens, roles, primitives). Different brand (gold/tan, not lime).

## Product personality

- **Name:** Aethelgard Art Co. Production Suite
- **Feel:** dark craft studio + operator console — refined, dense, trustworthy
- **Audience:** power user shipping listings daily
- **Metaphor:** atelier / print shop floor — not a marketing landing page, not a neon AI toy

---

## Design tokens

Define once in CSS (`:root` / custom properties). Reuse everywhere. No raw hex in component rules except via variables.

### Color

```css
:root {
  /* Surfaces */
  --canvas: #0c0b0a;       /* page background — warm near-black */
  --panel: #161412;        /* primary elevated surface */
  --panel-2: #1e1b18;      /* hover / secondary surface */
  --line: #2e2a24;         /* borders / dividers */

  /* Text */
  --ink: #efece6;
  --ink-muted: #a39e94;
  --ink-faint: #6f6a60;

  /* Brand */
  --primary: #c5a880;      /* gold/tan — CTAs, active nav, focus accents */
  --primary-dim: #9a8260;  /* muted primary */

  /* Semantic — status only, not decoration */
  --success: #6fbf8a;
  --warn: #d4a84b;
  --danger: #d46767;
  --info: #6fa8d4;
}
```

Use `rgba(primary, …)` for soft fills (`bg-primary/10`, borders) — never invent a second accent “for fun.”

### Typography (3 roles max)

| Role | Use for | Guidance |
|---|---|---|
| **Display** | Page titles, key numbers, brand wordmark | Distinctive — Outfit semibold/medium or a refined display; larger tracking-tight |
| **Sans** | Body, forms, nav, buttons | Inter or Outfit regular/medium |
| **Mono** | Metadata, counts (`104/140`), paths, ports, versions, status codes | IBM Plex Mono / JetBrains Mono / system mono |

```css
:root {
  --font-display: "Outfit", system-ui, sans-serif;
  --font-sans: "Inter", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
}
```

**Do not** use Inter for every size/weight without hierarchy. Labels for field groups use mono uppercase + tracking.

### Spacing & radius

- Page content: consistent horizontal padding; avoid full-bleed chaos inside the main pane
- Section gap: `24–32px`
- Panel padding: `16–20px`
- Radius: **one small** (inputs/buttons ~6–8px), **one medium** (panels ~12px)
- Prefer **borders** over heavy shadows
- Align columns; keep label/control rhythm consistent

### Atmosphere

- Subtle warm radial gradient or light grain on `--canvas` is OK
- No purple glow, glassmorphism spam, emoji decoration, or marketing-hero patterns inside the app shell

---

## Shared primitives

Restyle / introduce these class patterns first. Every view must use them.

| Primitive | Purpose | Notes |
|---|---|---|
| **AppShell** | Sidebar + brand + nav + footer status | Active nav = primary tint, not loud fill |
| **PageHeader** | Title + one-line description + optional actions | Display title; muted description |
| **Panel** | Bordered surface for grouped content | `border: 1px solid var(--line); background: var(--panel)` |
| **Button** | `.btn` / `.btn-primary` / `.btn-secondary` / `.btn-ghost` / `.btn-danger` | Only one primary per view |
| **Badge / StatusPill** | PORTRAIT, Draft confirmed, PDF ready | Mono, small, semantic color when needed |
| **Field** | Label + control + helper + counter | Counters always visible where limits exist |
| **TagInput** | Chips + Add + max rules | Max 13 / max 20 chars stays visible |
| **Alert** | Success / warn / error inline | Panel variant — not a random green box |
| **MediaThumb** | Mockup tile + checkbox + secondary action | Art is the anchor; chrome stays quiet |

### Button hierarchy (mandatory)

1. **Primary** — advances the pipeline (Upload Draft, Generate, Run research)
2. **Secondary** — Save / Reload / Connect / Compile
3. **Ghost / text link** — legacy, Inspect, Open in new tab, browser upload fallback

Never show six equal-weight buttons in a 2×2 grid.

---

## Information architecture

Pipeline order stays:

**Market Research → Print Generator → Catalog & Uploads → Mockup Studio → Presets & Settings**

Nav labels may be polished; **route / view IDs / order must not change.**

Document exact view IDs from `dashboard.html` in a short appendix when inventorying (e.g. `#view-catalog`, `#view-research`, …). Primary CTA per view goes next to that ID.

---

## Page recipes

### List / Grid (Catalog grid, Artwork library)

- `PageHeader` + filter/actions row
- Card grid **or** table — pick one density model and stick to it
- Card: thumb, title (2 lines max), 1–2 badges, one hover affordance
- Click opens detail — **no full SEO form on the grid**

### Detail / Editor (Catalog listing detail — gold standard)

Two-column operator layout:

| Left | Right |
|---|---|
| Preview + mockup selection (visual truth) | SEO fields + primary upload CTA (decision truth) |

Rules:

- **One** sticky or bottom primary CTA: **Upload Draft (API)**
- Cluster secondary tools: Open folder / Select & update mockups / Save SEO / Compile PDF
- Status badges near the title, not scattered
- Success state = `Alert` / Panel success variant (e.g. “SUCCEEDED: API draft created”)
- Mockup checkboxes are the main interaction; “Change art” is secondary
- Char counts, tag limits, price/qty stay visible

### Research / Keywords

- Query / run control is the hero action
- Results as scannable table with mono metrics
- Empty state: one clear next step

### Generator / Mockup Studio

- Preview dominates the viewport
- Controls in a narrow rail
- Progress / server status always visible
- Destructive actions need confirm

### Settings / Presets

- Group by purpose (one section = one job)
- Dangerous settings visually separated
- Save is secondary unless leaving dirty state

---

## Hierarchy rules (senior bar)

- Brand mark clear in shell; page title uses Display and does not fight the brand
- Each section: **one purpose, one heading**, optional one helper line
- Field-group labels: mono uppercase tracking (`TAGS`, `LISTING MOCKUPS`)
- Body copy short; scannable structure over paragraphs
- Constraints always visible (tags 13, title 140, price, qty)

## Density

- Tool UI may be dense; density ≠ clutter
- Quieter chrome so art/mockups remain the visual anchor
- Prefer alignment and muted labels over extra boxes

## Accessibility & states

- Visible focus rings on all controls (primary-tinted)
- Disabled = muted + no pointer
- Loading state on primary CTA while upload/generate runs
- Errors inline near the failing field
- Don’t rely on color alone for status

---

## Rollout order (mandatory)

| Phase | Work |
|---|---|
| **P0** | CSS variables, typography roles, AppShell (sidebar, nav active, status footer) |
| **P1** | Shared primitives: buttons, Panel, PageHeader, Field, Badge, tags, MediaThumb |
| **P2** | Catalog detail gold standard (media \| SEO, one Upload Draft CTA) |
| **P3** | Catalog grid + Artwork library |
| **P4** | Research, Generator, Studio, Settings — same primitives |
| **P5** | Empty / loading / error pass across all views |

**Checkpoint:** after P0–P1 (token + AppShell + primitives), stop for human approval before mass view restyling.

---

## Explicit don’ts

- Don’t rebuild backend or change upload sequence
- Don’t add features during the visual pass
- Don’t introduce a second brand accent
- Don’t card-wrap everything
- Don’t put marketing hero patterns into the app shell
- Don’t clone CareerOS lime / Fraunces look
- Don’t replace Inter/Outfit with a random trendy stack without defining the three roles

---

## Appendix — View inventory

| View ID | Nav label | Primary CTA | Notes |
|---|---|---|---|
| `#view-research` | Market Research | Run research / analyze | Query bar is hero |
| `#view-generator` | Print Generator | Generate / Finalize | Modes: AI, PD, poster |
| `#view-catalog` | Catalog & Uploads | **Upload Draft (API)** | Detail = gold standard; grid + Artwork library tab |
| `#view-studio` | Mockup Studio | Auto-detect / Save template | Preview-dominant |
| `#view-settings` | Presets & Settings | Save Preset Configuration | Prices by product type |

Preserve every existing control even if visually demoted.

Legacy browser upload is a ghost/text action on Catalog detail only.
