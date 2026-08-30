# Master prompt — Aethelgard UI redesign

You are redesigning the UI/UX of **Aethelgard Art Co. Production Suite** (Python `server.py` + monolith `tooling/upload/dashboard.html`).

Read and treat as law:

- [`docs/AETHELGARD_UI_SYSTEM.md`](./AETHELGARD_UI_SYSTEM.md) (canonical copy of the design bible)
- [`docs/UI_SYSTEM.md`](./UI_SYSTEM.md) (same content; short path)

## Goals

- Make the product look designed by a senior product designer.
- Keep **100%** of existing functionality, view IDs, `onclick` handlers, and `/api/*` wiring.
- **Visual / layout / CSS only.** No backend, API, or workflow changes.

## Process

1. Inventory views and primary CTAs (see appendix in the design bible).
2. Tokens + AppShell + shared primitives first.
3. Catalog listing **detail** as gold standard (two-column: media | SEO).
4. Roll the same system across Catalog grid, Research, Generator, Studio, Settings.
5. After each view, confirm every control still wired the same.

## Brand

- Dark production suite, warm gold/tan accent (`#c5a880`).
- Dense operator UI is OK — fix hierarchy, not remove capability.
- One primary CTA per view (Upload Draft on listing detail).
- Do **not** clone CareerOS lime/Fraunces — same discipline, different brand.

## Stack note

This is **not** Next.js. Prefer CSS variables and class primitives in `dashboard.html`. Do not start a frontend rewrite in this pass.
