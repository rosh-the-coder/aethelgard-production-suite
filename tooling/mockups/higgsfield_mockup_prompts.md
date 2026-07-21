# Higgsfield Mockup Prompts — Aethelgard Art Co.

Use this guide to generate **photorealistic empty-frame mockup photos** in Higgsfield, then import them into **Mockup Studio** (Calibrate New → draw corners → Save Template).

---

## Quick workflow

1. Pick a prompt below (copy the full block).
2. Generate in Higgsfield at **2K or 4K** (see model table).
3. **Reject** any image that has artwork inside the frame, text, watermarks, warped geometry, or plastic-looking lighting.
4. Download PNG.
5. In the dashboard: **Mockup Studio → Calibrate New → upload PNG → draw frame corners → Save Template**.
6. Name files like: `japandi_shelf_single_4x5`, `dark_academia_trio_portrait`, etc.

---

## Which Higgsfield model to use

| Priority | Model | Best for | Notes |
|----------|--------|----------|--------|
| **1st choice** | **Nano Banana Pro** | Empty frames, correct geometry, “follows instructions” | Best when the frame must stay blank and perspective must be believable. Use native **2K**; enable **4K refine** for listing images. |
| **2nd choice** | **FLUX 2** | Interiors, natural light, wood texture, physics | Excellent walls, shadows, and furniture. Add the **negative block** every time. |
| **3rd choice** | **Seedream** (4.5) | Native 4K output | Use when you want max resolution in one shot without upscaling. |
| **Style / mood** | **Soul 2.0** + **Soul HEX** | Japandi & Dark Academia color grading | Upload a competitor Etsy mockup or Pinterest ref → extract palette with Soul HEX → generate. |
| **Avoid for mockups** | Z-Image | Speed only | Often ignores “empty frame” and adds art. |
| **Do not use** | Real-ESRGAN / local upscaler on templates | — | Caused tiling corruption on our templates. Generate at target size in Higgsfield instead. |

### Recommended settings (all models)

- **Aspect ratio:** `4:5` (portrait listings) or `3:2` / `16:9` (landscape)
- **Resolution:** 2048px short edge minimum; **4096px** if the model offers native 4K
- **Variations:** Generate **4–8** per prompt; keep 1–2 winners
- **Reference:** Optional — upload a competitor mockup with **Color signature / Soul HEX** only (not img2img of the art inside)

### Negative prompt (paste into negative field, or append after main prompt)

```
artwork inside frame, painting in frame, poster in frame, photo in frame, image in frame, printed picture, canvas art, abstract art in frame, landscape in frame, portrait in frame, plaster texture inside frame, clay art inside frame, brown art in frame, textured art in frame, wabi sabi art in frame, text, watermark, logo, signature, brand name, price tag, QR code, people, faces, hands, deformed frame, crooked frame, floating frame, cartoon, illustration, 3D render, CGI, plastic, oversaturated, blurry, low resolution, jpeg artifacts, collage, tiled, duplicated frames, extra frames, mirror reflection of art
```

### Positive quality tail (append to every prompt)

```
Shot on Sony A7IV, 35mm lens, f/2.8, professional interior product photography, soft natural window light, subtle film grain, shallow depth of field, ultra sharp focus, 8K detail, Etsy listing mockup photo, no artwork in frames
```

---

## Global rules for every mockup

- Frame openings must show **plain white, warm-white, or soft cream blank surface only** — completely empty (no art, no texture, no plaster pattern inside).
- **No** paintings, prints, posters, or patterns inside the frame.
- Lighting from one side (window left or right) — consistent shadows; **venetian blind stripe shadows on floor** are a plus for the premium Etsy look.
- Real materials: oak, linen, plaster, velvet, brass — not glossy CGI.
- For **multi-frame** shots: identical frame style, evenly spaced, same proportions.
- **Premium Etsy style** (see reference section): oversized frames, floor-lean compositions, art hung above bed/sofa/console, warm terracotta or greige walls, minimal scandi furniture.

---

# Premium Etsy lifestyle layouts (reference style)

**Inspired by top-selling Japandi plaster & clay listings.** These match the “real interior photo” look: large frames, dramatic natural light, minimal furniture, empty canvas-ready placeholders.

**Frame look:** thin natural oak floater frame, OR thin black metal frame, OR frameless gallery-wrap edge — center must be **completely blank** (plain white / warm cream empty surface, no texture, no art).

**Best model:** Nano Banana Pro + upload your reference grid screenshot as **Soul HEX color reference** (palette only).

**Aspect:** `4:5` portrait for all below unless noted.

---

## A — Triple floor lean + window shadow stripes (Japandi)

```
Professional Etsy wall art mockup photograph, japandi wabi-sabi interior. THREE identical large empty portrait picture frames leaning against a warm greige limewash wall on light oak herringbone wood floor. Thin natural oak floater frames, each opening shows completely blank warm-white empty canvas surface — no artwork, no plaster texture, no painting, no abstract art inside any frame. Dramatic natural sunlight through window blinds casting soft parallel shadow stripes across the floor. Minimal scandinavian room, airy and bright, subtle plaster wall texture. Photorealistic architectural digest interior, shot on Sony A7IV 35mm, ultra sharp, real wood grain, Etsy bestseller mockup style
```

## B — Double above platform bed (Japandi)

```
Photorealistic Etsy digital art mockup. TWO empty portrait picture frames hung horizontally centered above a low minimalist japandi platform bed with rumpled natural linen bedding in cream and oatmeal tones. Warm beige textured wall, soft diffused morning light from side window. Thin light oak frames with blank off-white empty mat surface inside — absolutely no artwork, no clay texture, no print. Calm serene bedroom, neutral palette, high-end interior product photography, 8K sharp, real fabric weave detail
```

## C — Triple above white modern sofa (Japandi)

```
Professional Etsy listing mockup photo. THREE identical empty portrait frames in a horizontal row on a warm off-white wall above a clean modern white bouclé sofa. Bright airy scandinavian living room, light wood coffee table edge visible, soft natural daylight, minimal decor. Each frame has blank white empty center — no paintings, no plaster art, no images. Photorealistic lifestyle interior photography, sharp focus, neutral japandi color grading, Sony A7IV 35mm
```

## D — Double above dark sideboard + green chair (Dark Academia / moody Japandi)

```
Etsy wall art mockup, moody sophisticated interior. TWO empty portrait frames with thin black metal frames and wide white mats, hung above a dark walnut mid-century modern sideboard. Deep olive green velvet accent chair, tall vase with dried pampas grass, warm directional sunlight from left casting soft shadows. Frame interiors completely blank white mat only — no artwork, no oil painting, no dark art inside. Photorealistic editorial interior, rich but natural colors, ultra sharp product photo
```

## E — Large double floor lean — spacious room (Japandi)

```
Photorealistic premium Etsy mockup. TWO oversized large empty portrait frames leaning against a tall warm beige plaster wall on wide light oak floorboards. Thin natural wood floater frames, blank warm-white empty canvas surface in each — no art, no texture, no plaster painting. Open minimal living space, golden hour sunlight, long soft shadows, high ceiling feel. Luxury scandinavian-japandi interior, shot on 35mm, ultra sharp, real materials, bestseller listing aesthetic
```

## F — Double on console + terracotta wall + curved sofa (Japandi)

```
Professional Etsy product mockup. TWO empty portrait frames with thin oak frames sitting on a long light wood console table against a warm terracotta clay-colored limewash wall. Cream curved bouclé sofa in foreground soft blur, round wood coffee table, dried botanical stem in ceramic vase. Bright soft window light. Both frames show blank cream-white empty surface — no artwork, no abstract plaster art. Photorealistic interior lifestyle photo, warm earthy neutral palette, 8K detail
```

## G — Double entryway console — minimal white wall (Japandi)

```
Clean minimal Etsy mockup photograph. TWO empty portrait picture frames on a narrow light oak console table against a plain warm white wall. Simple scandinavian entryway, one small ceramic vase, uncluttered composition, soft even daylight. Thin natural wood frames, blank white empty mat inside each — no art, no print. Photorealistic, sharp, bright airy neutral interior, professional product photography
```

## H — Single oversized floor lean — hero shot (Japandi)

```
Etsy hero mockup image. ONE single oversized empty portrait picture frame leaning against warm greige textured wall on light wood floor. Thin oak floater frame, completely blank warm-white empty canvas center — no artwork whatsoever. Dramatic window blind shadow stripes on floor, minimal japandi room, golden natural light. Photorealistic, ultra sharp, premium Etsy digital download listing photo
```

## I — Triple floor lean (Dark Academia variant)

```
Dark academia Etsy mockup. THREE large empty portrait frames leaning on dark herringbone wood floor against charcoal gray wall with subtle panel moulding. Thin black gallery frames, blank aged cream empty mat in each — no gothic art, no oil paintings. Moody warm side light, vintage brass floor lamp edge, leather ottoman blur. Photorealistic cinematic interior, empty frames only
```

## J — Double above sofa (Botanical / neutral)

```
Natural history Etsy mockup style. TWO empty portrait frames above a neutral linen sofa on warm ivory wall. Thin black metal frames, blank warm white mat surface — no botanical print, no specimen chart, no art. Soft north-window daylight, potted fern on side table, calm collector's living room. Photorealistic, sharp, museum-home aesthetic
```

### Premium layout naming guide

| Ref | Save as | Niche |
|-----|---------|-------|
| A | `japandi_triple_floor_lean_shadows_4x5` | Japandi |
| B | `japandi_double_above_bed_4x5` | Japandi |
| C | `japandi_triple_above_sofa_4x5` | Japandi |
| D | `moody_double_sideboard_velvet_4x5` | Japandi / Dark Academia |
| E | `japandi_double_oversized_floor_lean_4x5` | Japandi |
| F | `japandi_double_console_terracotta_4x5` | Japandi |
| G | `japandi_double_entryway_console_4x5` | Japandi |
| H | `japandi_single_hero_floor_lean_4x5` | Japandi |
| I | `dark_academia_triple_floor_lean_4x5` | Dark Academia |
| J | `botanical_double_above_sofa_4x5` | Botanical |

---

# Gallery wall bundle packs (mixed frame sizes)

**For Etsy bundle listings** (50–500+ print packs). These mimic top sellers: **many frames in one photo**, mixed portrait / landscape / square sizes, thin consistent frames, salon-style clustered layout.

### Important notes

- **Purpose:** Hero / carousel images showing “fill an entire wall with this bundle.” You typically **do not** auto-composite art into all 20–40 frames in Mockup Studio — that’s for marketing. For automated mockups, keep using single/trio templates from earlier sections.
- **Frame count:** Ask for **12–20 frames** in Higgsfield (not 40+) — models handle that better; you can still imply a “large bundle” in your listing title.
- **Every frame:** blank white or cream empty surface — **no art, no sketches, no text overlays, no logos**.
- **Aspect:** `4:5` portrait (Etsy listing) or `1:1` square (carousel slide 1).
- **Model:** **Nano Banana Pro** — specify exact frame count and “empty blank placeholder in every frame.”

### Bundle negative prompt (add to standard negative)

```
text overlay, typography, logo, watermark, brand name, "500 prints", category icons, banner, collage labels, artwork inside frames, paintings, sketches, portraits in frames, botanical illustrations in frames, plaster art in frames, gothic art in frames
```

---

## Japandi bundle — 3 variants (Niche 4)

### J-B1 — Salon grid above linen sofa

```
Professional Etsy bundle pack mockup, japandi wabi-sabi interior. Gallery wall with exactly EIGHTEEN empty picture frames of varying sizes — mix of large portrait, medium landscape, and small square frames — arranged in an organic salon-style cluster on warm greige limewash plaster wall. All frames thin natural light oak with blank warm-white empty mat or canvas in every opening — no artwork, no plaster texture, no abstract art in any frame. Below: neutral beige linen sofa with cream throw pillows, light oak side table with ceramic vase and dried branch. Soft natural window light from left, subtle frame shadows on wall. Photorealistic architectural digest interior, Sony A7IV 35mm, ultra sharp, premium digital download bundle listing photo
```

### J-B2 — Corner gallery wall (two walls)

```
Etsy printable wall art bundle mockup. Room corner showing two walls meeting at 90 degrees, covered with SIXTEEN empty frames of mixed sizes and orientations — large vertical, medium horizontal, small squares — thin light oak frames, every frame completely blank warm-white empty surface, no art. Minimal scandinavian-japandi corner, light wood floor, simple lounge chair with oatmeal linen cushion, small wooden stool with book. Soft diffused daylight, calm neutral palette, photorealistic interior photography, sharp detail
```

### J-B3 — Dense grid hero + console styling

```
Japandi gallery wall bundle hero image. FIFTEEN empty picture frames in tight salon arrangement on tall warm beige textured plaster wall — varied portrait landscape and square sizes, thin oak frames, all openings blank cream-white empty placeholders — zero artwork. Bottom of frame: long light wood console with stacked neutral books, handmade ceramic bowl, single dried pampas stem. Bright airy minimal room, soft shadows, photorealistic Etsy bestseller bundle mockup style, 8K sharp
```

| Save as | Layout |
|---------|--------|
| `japandi_bundle_salon_sofa_18frames_4x5` | 18 frames above sofa |
| `japandi_bundle_corner_16frames_4x5` | Corner two-wall |
| `japandi_bundle_grid_console_15frames_4x5` | Dense grid + console |

---

## Dark Academia bundle — 3 variants (Niche 3)

### D-B1 — Above sofa + bookshelves (moody living room)

```
Dark academia Etsy bundle mockup photograph. Gallery wall with exactly SEVENTEEN empty picture frames of varying sizes — large portrait centerpieces, medium landscapes, small squares — thin matte black frames clustered salon-style on charcoal gray wall. Every frame opening blank aged cream empty mat — no gothic art, no oil paintings, no portraits, no ravens, no skulls in any frame. Below: tufted beige linen sofa with dark brown pillows, dark wood side table with vintage brass table lamp glowing warm, floor-to-ceiling bookshelves with leather books at edges. Moody cinematic lighting, warm lamp light mixed with cool window rim light. Photorealistic editorial interior, ultra sharp, bundle pack listing image
```

### D-B2 — Forest green wall salon (frame variety)

```
Moody dark academia bundle listing mockup. TWENTY empty frames of mixed sizes — portrait, landscape, square — thin antique cream/off-white frames in dense salon-style puzzle arrangement on deep matte forest green wall. All frames completely blank empty cream mat surface — no artwork whatsoever. Even soft moody lighting, subtle shadows behind each frame, no furniture visible, wall fills frame. Photorealistic gallery wall product photo for 300+ printable wall art bundle, Sony A7IV, sharp
```

### D-B3 — Beige wall grid + books and dried florals

```
Dark academia printable bundle hero mockup. Large gallery wall with NINETEEN empty frames of varying sizes in tight clustered grid on warm antique beige plaster wall, thin black frames, blank white empty mat in every opening — no sketches, no vintage art, no text. Bottom foreground: dark wooden surface with stacks of old leather-bound books, tall dark ceramic vases with dried dark botanical stems left and right. Atmospheric warm low-key lighting, photorealistic, premium Etsy digital bundle aesthetic, 8K detail
```

| Save as | Layout |
|---------|--------|
| `dark_academia_bundle_sofa_17frames_4x5` | Above sofa + library |
| `dark_academia_bundle_green_wall_20frames_4x5` | Green wall salon |
| `dark_academia_bundle_books_grid_19frames_4x5` | Beige grid + props |

---

## Botanical / Specimen bundle — 3 variants (Niche 1)

### B-B1 — Museum salon above bench

```
Scientific botanical Etsy bundle mockup. Gallery wall with SIXTEEN empty frames of varying sizes — mix of portrait specimen-chart proportions, landscape plates, and small squares — thin black metal frames in curated museum salon arrangement on warm ivory gallery wall. Every frame blank warm-white empty mat — no botanical illustrations, no lithographs, no charts, no mushroom prints in any frame. Below: simple oak museum bench, potted fern, soft diffused north-light. Photorealistic natural history aesthetic, sharp product photography
```

### B-B2 — Collector study corner (two walls)

```
Vintage botanical printable bundle mockup. Room corner with FIFTEEN empty frames of mixed sizes on two cream linen-textured walls, thin black and light maple frames alternating, salon-style cluster, all openings blank off-white empty surface — no specimen art. Curator's study corner: wooden desk edge with magnifying glass, glass cloche, field notebook, dried pressed leaf. Soft daylight, calm collector's home aesthetic, photorealistic Etsy bundle listing photo
```

### B-B3 — Apothecary wall + shelf props

```
Botanical lithograph bundle hero mockup. EIGHTEEN empty picture frames of varied portrait landscape and square sizes in dense arrangement on warm aged cream wall, thin brass and black frames, every frame completely blank ivory empty mat — no botanical prints, no anatomy charts. Bottom: rustic wooden apothecary shelf with glass jars of dried herbs, linen cloth, small mortar. Soft natural light, museum-apothecary style, photorealistic sharp interior photo for digital download bundle
```

| Save as | Layout |
|---------|--------|
| `botanical_bundle_museum_16frames_4x5` | Museum + bench |
| `botanical_bundle_corner_study_15frames_4x5` | Corner study |
| `botanical_bundle_apothecary_18frames_4x5` | Apothecary grid |

### Bundle pack workflow on Etsy

1. Generate 3 bundle heroes per niche (9 total) in Higgsfield.
2. Use as **listing image 1–3** (or carousel) with your own text overlay in Canva if needed — not in the AI prompt.
3. Optionally composite 3–6 real prints into select frames in Photoshop for a “filled” version; keep one fully-empty version for honesty.
4. Single-print mockups (earlier sections) remain your workhorse for per-piece automated compositing in the pipeline.

---

# Niche 4 — Japandi Plaster & Clay Abstract Art

**Vibe:** Warm beige plaster, wabi-sabi, muted clay tones, linen, ceramic, minimal branches, soft daylight.  
**Frame style:** Light oak or natural birch, thin profile, wide white mat.  
**Tags when saving in Mockup Studio:** `japandi`, `minimalist`, `neutral`

---

## Single frame — shelf (portrait 4:5)

```
Professional Etsy product mockup photograph. A single empty portrait picture frame with a wide bright white mat and light oak wood border, sitting on a minimalist japandi floating wall shelf. Warm beige limewash plaster wall with subtle texture. Small handmade ceramic vase with dried bunny tail grass, linen napkin, wabi-sabi styling. Soft morning sunlight from the left, gentle shadow falloff. The frame opening is completely empty white mat board only — absolutely no artwork, no painting, no print inside. Shot on Sony A7IV, 35mm lens, f/2.8, professional interior product photography, soft natural window light, subtle film grain, ultra sharp focus, 8K detail, Etsy listing mockup photo
```

## Single frame — glass portrait on shelf (portrait 4:5)

**Best model:** FLUX 2 or Nano Banana Pro. Glass glare/reflections help sell realism — reject any generation that puts art behind the glass.

```
Professional Etsy product mockup photograph. A single empty portrait picture frame with thin brushed brass frame and clear museum glass, wide bright white mat, sitting on a minimalist japandi floating oak wall shelf. Warm beige limewash plaster wall with subtle texture. Small handmade ceramic vase with dried bunny tail grass, linen napkin draped on shelf. Soft morning sunlight from the left casting gentle shadow on wall, subtle realistic glass reflections and faint glare streak on glass surface. Frame opening completely empty white mat board only — absolutely no artwork, no painting, no print behind glass. Shot on Sony A7IV, 35mm lens, f/2.8, professional interior product photography, soft natural window light, ultra sharp focus, 8K detail, Etsy listing mockup photo
```

**Save as:** `japandi_glass_portrait_shelf_4x5` — tags: `japandi`, `minimalist`, `neutral`, `glass`

## Single frame — leaning on sideboard (portrait 4:5)

```
Photorealistic interior mockup for Etsy digital art listing. One empty portrait frame, natural light oak with white mat, leaning against a textured warm greige plaster wall on a low japandi oak sideboard. Single stoneware bowl, dried pampas stem in ceramic vase, neutral linen throw edge visible. Calm scandinavian-japandi living room, soft diffused daylight, realistic wood grain and plaster pores. Frame interior is blank white mat only, no art, no image, no poster. Professional product photography, 35mm, natural color grading
```

## Single frame — desk / workspace (landscape 3:2)

```
Etsy wall art mockup photo, landscape orientation. Single empty thin black aluminum or light oak frame with white mat on a clean white oak desk in a japandi home office. Textured off-white wall, small monstera plant soft blur in background, minimal stationery, bright soft daylight from window. Completely empty frame opening — plain white mat, no artwork. Photorealistic, architectural digest style interior, sharp focus on frame, Sony A7IV 35mm
```

## Trio — horizontal row above console (portrait 4:5)

```
Professional Etsy gallery mockup. Living room wall with THREE identical empty portrait picture frames in a horizontal row, light oak frames with wide white mats, evenly spaced. Below: minimalist japandi oak console table, cream plaster wall, monstera plant in white pot, ceramic vase, soft natural light from left. Each frame opening is completely empty white mat board — no paintings, no prints, no artwork in any frame. Photorealistic interior photography, 8K sharp, subtle shadows, real materials
```

## Five frames — gallery wall (portrait 4:5)

```
Photorealistic gallery wall mockup for Etsy. FIVE identical empty portrait frames in a single horizontal row on a warm beige japandi plaster wall, light wood frames, white mats, equal spacing. Modern minimal living room, oak bench below, woven basket, neutral tones, soft daylight. All five frame openings blank white mat only, zero artwork. Professional interior product photo, ultra sharp, natural lighting
```

## Nine frames — grid (portrait 4:5)

```
Etsy product mockup, japandi interior. Gallery wall with NINE empty portrait frames in a 3x3 grid, matching light oak frames and white mats on warm greige plaster wall. Minimal scandinavian room, soft window light, calm neutral decor. Every frame completely empty — white mat board only, no art in any opening. Photorealistic, high-end interior photography, sharp detail
```

---

# Niche 3 — Moody Dark Academia & Gothic Oil Sketches

**Vibe:** Mahogany, leather, brass candlesticks, vintage books, charcoal walls, candlelight + window rim light.  
**Frame style:** Ornate dark wood, antique gold, or thin black gallery frame; cream or aged-white mat.  
**Tags when saving:** `dark_academia`, `neutral`, `botanical`

---

## Single frame — study desk (portrait 4:5)

```
Professional Etsy mockup photograph, dark academia aesthetic. Single empty ornate antique dark walnut portrait frame with aged cream mat, on a mahogany writing desk. Leather-bound books stacked, brass candlestick with lit candle, glass inkwell, moody Victorian study background softly blurred. Warm candlelight mixed with cool window light from left. Frame opening completely empty — plain cream mat only, no painting, no portrait, no artwork inside. Photorealistic, cinematic but natural, 35mm product photography, ultra sharp
```

## Single frame — above fireplace (portrait 4:5)

```
Photorealistic dark academia interior mockup. One empty portrait frame with ornate dark wood and off-white mat, hanging centered above a vintage stone fireplace mantel. Gothic revival details, ivy outside window bokeh, deep green walls, antique brass lamp. Empty white mat visible inside frame — no art, no oil painting, no image. Moody atmospheric lighting, realistic textures, Etsy listing quality photo
```

## Single frame — leaning on bookshelf (portrait 4:5)

```
Etsy digital art mockup, moody dark academia library. Single empty portrait frame with black gallery moulding and white mat, leaning against floor-to-ceiling antique bookshelf filled with old books. Velvet armchair edge visible, warm tungsten reading lamp, dust motes in window light. Frame interior blank white mat only — absolutely no artwork. Photorealistic interior photography, sharp focus, natural film grain
```

## Trio — above velvet sofa (portrait 4:5)

```
Professional gallery mockup photo, dark academia living room. THREE empty portrait frames in a row on charcoal gray wall above a deep green velvet chesterfield sofa. Matching ornate dark wood frames with cream mats, vintage library shelves, brass floor lamp, moody cinematic lighting. All three frames empty — cream mat board only, no paintings. Photorealistic, high-end editorial interior, 8K detail
```

## Five frames — library gallery wall (portrait 4:5)

```
Dark academia gallery wall mockup for Etsy. FIVE empty portrait frames in a horizontal row on dark paneled library wall, antique gold and dark wood frames, cream mats. Leather sofa below, globe on side table, candlelight and window light mix. Every frame opening blank — no artwork, no gothic paintings. Photorealistic Victorian interior product photography
```

## Landscape — desk with quill & books (landscape 3:2)

```
Etsy mockup landscape format. Single empty landscape-oriented antique dark wood frame with cream mat on mahogany desk, open leather journal, feather quill, wax seal, stacked vintage books, candle glow. Gothic dark academia study, shallow depth of field. Frame completely empty white mat — no landscape painting inside. Photorealistic 35mm interior photo
```

---

# Niche 1 — Scientific Specimen Charts & Botanical Lithographs

**Vibe:** Natural history museum, apothecary, aged paper, linen, pressed plants, glass cloches, warm ivory walls.  
**Frame style:** Thin black, brass, or light maple gallery frame; off-white or warm ivory mat.  
**Tags when saving:** `botanical`, `neutral`, `vintage_botanical_chart`

---

## Single frame — apothecary shelf (portrait 4:5)

```
Professional Etsy mockup, vintage botanical aesthetic. Single empty portrait frame with thin black metal frame and warm ivory mat on a rustic wooden apothecary shelf. Glass jars with dried herbs, pressed fern specimen, linen cloth, aged plaster wall. Soft natural north-window light. Frame opening completely empty ivory mat — no botanical print, no chart, no illustration inside. Photorealistic product photography, museum catalog style, ultra sharp
```

## Single frame — above specimen desk (portrait 4:5)

```
Photorealistic natural history mockup. One empty portrait frame with light maple wood and off-white mat, hanging above a curator's desk with magnifying glass, field notebook, dried mushroom specimen on paper, brass ruler. Warm cream wall, soft daylight. Empty mat board only — no scientific illustration, no lithograph, no art. Etsy listing interior photo, 35mm, natural colors
```

## Single frame — cottage kitchen (portrait 4:5)

```
Etsy wall art mockup, botanical cottagecore. Single empty portrait frame with thin brass frame and white mat on a painted sage-green kitchen wall above open wooden shelving. Ceramic bowls, dried wildflowers in glass bottle, woven basket. Bright soft daylight. Frame interior blank white mat — no botanical poster, no chart. Photorealistic lifestyle interior photography
```

## Trio — museum wall (portrait 4:5)

```
Professional gallery mockup, natural history museum aesthetic. THREE empty portrait frames in a horizontal row on warm ivory gallery wall, thin black frames with off-white mats, evenly spaced. Oak bench below, potted fern, soft diffused museum lighting. All three openings empty ivory mat only — no specimen charts, no lithographs. Photorealistic, sharp, Etsy product photo
```

## Five frames — collector's study (portrait 4:5)

```
Botanical collector study mockup for Etsy. FIVE empty portrait frames in a row on cream linen-textured wall, matching thin black gallery frames, warm white mats. Wooden desk with microscope, stacked nature journals, glass cloche with dried flowers. All frames completely empty — no prints inside. Photorealistic interior photography, soft window light
```

## Landscape — lab table (landscape 3:2)

```
Etsy mockup landscape. Single empty landscape frame with thin black frame and ivory mat on old wooden laboratory table, botanical field guides, specimen tweezers, handwritten labels, north light from tall window. Frame opening blank ivory mat — no chart artwork. Photorealistic vintage science aesthetic, sharp product photo
```

---

## Aspect ratio cheat sheet (Etsy digital prints)

| Your print format | Mockup aspect in Higgsfield | Example prompt set |
|-------------------|----------------------------|-------------------|
| 4:5, 8×10, 11×14 portrait | **4:5** | Most prompts above |
| 3:2, 24×36 landscape | **3:2** | Desk / landscape prompts |
| Square bundle previews | **1:1** | Use trio/grid prompts cropped mentally |

---

## After you generate — import checklist

- [ ] Frame is **empty** (white/cream mat only)
- [ ] No AI art snuck into the mat opening
- [ ] Perspective is straight-on or gentle angle (not extreme fisheye)
- [ ] Resolution ≥ **2048px** on the long edge
- [ ] File saved as **PNG**
- [ ] Calibrated in Mockup Studio (perspective corners on the **inner mat edge**)
- [ ] Regenerate listing mockups from Catalog

---

## Suggested template set (minimum viable library)

| # | Name idea | Niche | Layout |
|---|-----------|-------|--------|
| 1 | `japandi_triple_floor_lean_shadows_4x5` | Japandi | 3 floor lean ⭐ |
| 2 | `japandi_double_above_bed_4x5` | Japandi | 2 above bed ⭐ |
| 3 | `japandi_triple_above_sofa_4x5` | Japandi | 3 above sofa ⭐ |
| 4 | `japandi_double_console_terracotta_4x5` | Japandi | 2 on console ⭐ |
| 5 | `japandi_double_oversized_floor_lean_4x5` | Japandi | 2 floor lean ⭐ |
| 6 | `moody_double_sideboard_velvet_4x5` | Japandi / DA | 2 above sideboard ⭐ |
| 7 | `japandi_bundle_salon_sofa_18frames_4x5` | Japandi | Bundle 18-frame ⭐ |
| 8 | `dark_academia_bundle_sofa_17frames_4x5` | Dark Academia | Bundle 17-frame ⭐ |
| 9 | `botanical_bundle_museum_16frames_4x5` | Botanical | Bundle 16-frame ⭐ |

⭐ = premium reference style. **Bundle prompts (B1–B3 per niche):** see Gallery wall bundle packs section — 3 per niche for pack listings.

---

## Troubleshooting in Higgsfield

| Problem | Fix |
|---------|-----|
| Art appears inside frame | Regenerate with negative prompt; switch to **Nano Banana Pro**; add “EMPTY white mat, NO artwork” twice in prompt |
| Frame looks fake / CGI | Add “shot on real camera, imperfect natural light, real wood grain pores” |
| Wrong colors for niche | Use **Soul HEX** with a Pinterest reference from that niche |
| Text or watermark | Regenerate; add “no text, no watermark” to negative |
| Wrong number of frames | Switch to Nano Banana Pro; specify “exactly three frames” numerically |
| Art/textured plaster appears inside frame | Add to negative: “plaster texture inside frame, clay art, brown art”; emphasize “blank empty white canvas, NO texture inside frame” |
| Doesn't match reference vibe | Upload reference screenshot to **Soul HEX**; use Premium layout prompts A–H |

---

*Generated for Aethelgard Art Co. — replace broken pipeline templates with Higgsfield sources, then calibrate in Mockup Studio.*
