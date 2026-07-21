---
name: designing-ui-ux
description: >
  AI-powered design intelligence toolkit with searchable databases of UI styles, color palettes,
  font pairings, chart types, and UX guidelines. Use when the user wants to design, build, style,
  or improve a website or application UI, pick colors, choose fonts, or follow UX best practices.
---

# UI/UX Pro Max — Design Intelligence Toolkit

## When to use this skill
- User wants to design or build a website/app UI
- User asks about color palettes, fonts, or styling
- User needs UX best practices or accessibility guidance
- User mentions glassmorphism, minimalism, dark mode, or any visual style
- User wants to create a landing page, dashboard, or portfolio

## Prerequisites

Python 3.x (no external dependencies). Check with:
```bash
python3 --version || python --version
```

## Workflow

### Step 1: Analyze Requirements
Extract from user request:
- **Product type**: SaaS, e-commerce, portfolio, dashboard, landing page, service
- **Style keywords**: minimal, playful, professional, elegant, dark mode
- **Industry**: healthcare, fintech, gaming, education, beauty, cleaning
- **Stack**: React, Vue, Next.js, or default `html-tailwind`

### Step 2: Generate Design System (REQUIRED — always start here)

```bash
python3 .agent/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py "<product_type> <industry> <keywords>" --design-system [-p "Project Name"]
```

This searches 5 domains in parallel (product, style, color, landing, typography) and returns a complete design system.

**Example:**
```bash
python3 .agent/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py "service cleaning professional" --design-system -p "CleanPro"
```

### Step 3: Detailed Domain Searches (as needed)

```bash
python3 .agent/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py "<keyword>" --domain <domain> [-n <max>]
```

| Domain | Use For |
|--------|---------|
| `product` | Product type recommendations |
| `style` | UI styles + CSS keywords |
| `typography` | Font pairings with Google Fonts |
| `color` | Color palettes by product type |
| `landing` | Page structure, CTA strategies |
| `chart` | Chart types, library recs |
| `ux` | Best practices, anti-patterns |

### Step 4: Stack Guidelines

```bash
python3 .agent/skills/ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py "<keyword>" --stack html-tailwind
```

Stacks: `html-tailwind`, `react`, `nextjs`, `vue`, `svelte`, `swiftui`, `react-native`, `flutter`, `shadcn`, `jetpack-compose`

## Pre-Delivery Checklist

- [ ] No emojis as icons (use SVG: Heroicons/Lucide)
- [ ] All clickable elements have `cursor-pointer`
- [ ] Hover states don't cause layout shift
- [ ] Light/dark mode contrast meets 4.5:1
- [ ] Responsive at 375px, 768px, 1024px, 1440px
- [ ] All images have alt text
- [ ] Transitions 150-300ms, smooth

## Resources
- [Full skill content template](src/ui-ux-pro-max/templates/base/skill-content.md)
- [Search script](src/ui-ux-pro-max/scripts/search.py)
- [CSV databases](src/ui-ux-pro-max/data/)
