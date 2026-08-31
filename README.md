# Aethelgard Art Co. Production Suite

**Shop brand:** Aethelgard Art Co. (not live yet)  
**GitHub:** https://github.com/rosh-the-coder/aethelgard-production-suite  
**Operator status & next steps:** [`LAUNCH_PROGRESS.md`](./LAUNCH_PROGRESS.md)  
**Full technical handover:** [`AETHELGARD_HANDOVER.md`](./AETHELGARD_HANDOVER.md)

Local Windows dashboard (`tooling/upload/server.py` → `http://127.0.0.1:8080`) that turns concepts into print files, mockups, SEO copy, a Drive-linked delivery PDF, and an Etsy **draft** listing. Generator modes: AI, Public Domain (Met), Graphic Poster. **Archive Studio** is the bulk open-access acquisition engine (see [`tooling/upload/docs/ARCHIVE_STUDIO.md`](./tooling/upload/docs/ARCHIVE_STUDIO.md)).

## Open this locally (viewable — it will not run as it does here)

This repository is **inspectable**. You can clone it and open it on your computer to read the code and, if the dashboard process starts, look around the UI.

**It will not work as a production suite on your machine.** Image generation, Etsy drafts, Google Drive packaging, and research scrapes depend on private API keys, OAuth apps, Playwright browsers, and local artwork that are **not** in this repo. Treat a clone as a view-only copy of the system.

**[Open in Cursor / VS Code](vscode://vscode.git/clone?url=https://github.com/rosh-the-coder/aethelgard-production-suite.git)** · **[View on GitHub](https://github.com/rosh-the-coder/aethelgard-production-suite)** · **[Browse in the browser](https://github.dev/rosh-the-coder/aethelgard-production-suite)**

```bash
git clone https://github.com/rosh-the-coder/aethelgard-production-suite.git
cd aethelgard-production-suite
```

On the operator machine only (keys already configured):

```powershell
.\tooling\ad-creatives\.venv\Scripts\python.exe tooling\upload\server.py
```

---

# Artwork Orchestrator (upstream Claude Skill)

This repo also contains Alek’s Artwork Orchestrator skill/engine (generate → upscale → crop).

Turn **one artwork concept** into organized, list-ready print products in a single run —
inside [Claude Code](https://claude.com/claude-code). You give it an idea; it drafts a few
prompt variations, generates locally, **upscales**, **crops to standard print sizes at 300 DPI**,
titles each piece, files it into its own folder, and writes listing SEO copy.

Prompt-first and fully local. It is the "I already know what I want to make" tool — for a single
concept straight through to finished print files.

---

## What's in this folder

```
artwork-orchestrator/
├── README.md            ← you are here
├── setup.sh             ← one-time installer (venv + upscaler + key scaffold)
├── requirements.txt
├── .claude/skills/artwork-orchestrator/   ← the skill (SKILL.md + scripts + references)
└── tooling/ad-creatives/generate.py       ← the image-generation engine the skill calls
```

There's also an **`artwork-orchestrator.skill`** file next to this folder — that's the same skill
packaged for a one-click drop into Claude Code if you just want the skill and will wire up the
engine yourself. Most people should use this folder + `setup.sh` instead.

---

## Requirements

- **macOS (Apple Silicon) or Linux**, with **Python 3.10+**
- **[Claude Code](https://claude.com/claude-code)**
- A **Google AI Studio API key** (free tier works to start). Optional: OpenAI + OpenRouter keys.

## Setup (once)

```bash
cd artwork-orchestrator
./setup.sh
```

`setup.sh` builds the Python environment, downloads the Real-ESRGAN upscaler for your OS, and
creates an **empty** key file at `~/.config/ai-images/env`. **No keys are included in this
download** — you add your own:

1. Get a key at **https://aistudio.google.com/apikey**
2. Put it in `~/.config/ai-images/env`:
   ```bash
   export GEMINI_API_KEY="your-key-here"
   ```
3. Load it:  `source ~/.config/ai-images/env`

(OpenAI and OpenRouter keys are optional — only needed if you want those providers.)

## Run it

Open this folder in Claude Code and say, for example:

> **"Run the artwork orchestrator on 'misty Pacific Northwest forest at dawn, muted greens'."**

Claude drafts the prompt variations, generates candidates, opens a contact sheet for you to pick
winners, then upscales + crops + titles + writes SEO for each keeper. Everything lands under
`tooling/digital-product-research/artwork-runs/<your-concept>/`.

Prefer the command line? The mechanical steps are:
```bash
PY=tooling/ad-creatives/.venv/bin/python
ART=.claude/skills/artwork-orchestrator/scripts/artwork.py
$PY $ART preflight            # check env + upscaler
# ... generate + choose a source image, then:
$PY $ART finalize piece.json  # upscale -> crop -> titled folder
$PY $ART index <run_dir>      # build the run index
```
See `.claude/skills/artwork-orchestrator/SKILL.md` for the full walkthrough.

## Print sizes (300 DPI)

- **Portrait:** 4×6, 5×7, 8×10, 11×14
- **Landscape:** 12×9, 20×16, 24×18, 36×24, A2

## Notes

- **Your keys stay on your machine** in `~/.config/ai-images/env` — they are never part of this
  package and are `.gitignore`d.
- **Cost** is whatever your image-model usage costs (Google AI Studio has a free tier to start).
- Generated art and print files are yours. This tool doesn't upload anything anywhere.

---

*Made by Alek. If this is useful, subscribe on YouTube — it genuinely helps. Thanks for watching!*
