#!/usr/bin/env bash
# Artwork Orchestrator — one-time setup.
# Builds the Python venv, fetches the Real-ESRGAN upscaler for your OS, and scaffolds
# an (empty) API-key file. Run it once from inside this folder:  ./setup.sh
#
# Nothing here needs sudo, and NO API keys are bundled — you add your own (see step 4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VENV="tooling/ad-creatives/.venv"
UPSCALE_DIR="tooling/upscale"
REALESRGAN_VER="20220424"
REALESRGAN_BASE="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"

echo "Artwork Orchestrator setup"
echo "  root: $ROOT"
echo

# 1. Python venv -----------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ and re-run." >&2; exit 1
fi
echo "[1/4] Creating venv + installing Python deps ($VENV) ..."
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r requirements.txt
echo "      done."
echo

# 2. Real-ESRGAN upscaler (per-OS) -----------------------------------------------
BIN="$UPSCALE_DIR/realesrgan-ncnn-vulkan"
if [ -x "$BIN" ]; then
  echo "[2/4] Upscaler already present ($BIN) — skipping."
else
  OS="$(uname -s)"; ARCH="$(uname -m)"
  case "$OS" in
    Darwin) ASSET="realesrgan-ncnn-vulkan-${REALESRGAN_VER}-macos.zip" ;;
    Linux)  ASSET="realesrgan-ncnn-vulkan-${REALESRGAN_VER}-ubuntu.zip" ;;
    *)      ASSET="" ;;
  esac
  if [ -z "$ASSET" ]; then
    echo "[2/4] No prebuilt upscaler for '$OS'. Windows users: download"
    echo "      $REALESRGAN_BASE/realesrgan-ncnn-vulkan-${REALESRGAN_VER}-windows.zip"
    echo "      and unzip realesrgan-ncnn-vulkan(.exe) + models/ into $UPSCALE_DIR/"
  else
    echo "[2/4] Fetching Real-ESRGAN for $OS/$ARCH ..."
    mkdir -p "$UPSCALE_DIR"
    TMP="$(mktemp -d)"
    curl -fL --progress-bar "$REALESRGAN_BASE/$ASSET" -o "$TMP/ra.zip"
    unzip -q -o "$TMP/ra.zip" -d "$TMP/ra"
    # The release zip contains the binary + a models/ dir (sometimes nested one level).
    SRCBIN="$(find "$TMP/ra" -name 'realesrgan-ncnn-vulkan' -type f | head -1)"
    SRCMODELS="$(dirname "$SRCBIN")/models"
    cp "$SRCBIN" "$BIN"
    [ -d "$SRCMODELS" ] && cp -R "$SRCMODELS" "$UPSCALE_DIR/models"
    chmod +x "$BIN"
    # macOS: clear the Gatekeeper quarantine so the unsigned binary can run.
    [ "$OS" = "Darwin" ] && xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true
    rm -rf "$TMP"
    echo "      installed -> $BIN"
  fi
fi
echo

# 3. Make the mechanical script executable ---------------------------------------
chmod +x .claude/skills/artwork-orchestrator/scripts/artwork.py 2>/dev/null || true

# 4. API-key scaffold (never overwrites an existing file; ships EMPTY) -----------
ENV_FILE="$HOME/.config/ai-images/env"
echo "[3/4] API keys ($ENV_FILE)"
if [ -f "$ENV_FILE" ]; then
  echo "      already exists — leaving it untouched."
else
  mkdir -p "$(dirname "$ENV_FILE")"
  cat > "$ENV_FILE" <<'EOF'
# Artwork Orchestrator — your own API keys (this file is NOT shared).
# You only need GEMINI_API_KEY to run the default (Nano Banana) pipeline.
export GEMINI_API_KEY=""       # https://aistudio.google.com/apikey   (required)
export OPENAI_API_KEY=""       # https://platform.openai.com/api-keys (optional: GPT Image)
export OPENROUTER_API_KEY=""   # https://openrouter.ai/keys           (optional: fallback)
EOF
  chmod 600 "$ENV_FILE"
  echo "      created an empty scaffold — add at least GEMINI_API_KEY, then:  source \"$ENV_FILE\""
fi
echo

# 5. Preflight -------------------------------------------------------------------
echo "[4/4] Preflight:"
set +e
"$VENV/bin/python" .claude/skills/artwork-orchestrator/scripts/artwork.py preflight
echo
echo "Setup complete. Add your key(s) to $ENV_FILE, then open this folder in Claude Code"
echo "and say:  \"run the artwork orchestrator on '<your concept>'\""
