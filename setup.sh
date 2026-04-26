#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Friday — First-Time Setup Script
#  Installs dependencies, detects hardware, and configures the environment.
#
#  Usage:  bash setup.sh
#          bash setup.sh --non-interactive   (accept all defaults, no prompts)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
IFS=$'\n\t'

# ── Flags ─────────────────────────────────────────────────────────────────────
NON_INTERACTIVE=false
for arg in "$@"; do
  [[ "$arg" == "--non-interactive" || "$arg" == "-y" ]] && NON_INTERACTIVE=true
done

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[ERR ]${NC}  $*"; }
step()    { echo -e "\n${BOLD}${BLUE}▶ $*${NC}"; }

ask() {
  # ask <prompt> — returns 0 (yes) or 1 (no). In non-interactive mode returns 1.
  local prompt="$1"
  if [[ "$NON_INTERACTIVE" == true ]]; then
    info "$prompt → skipped (non-interactive)"
    return 1
  fi
  read -r -p "  $prompt [y/N] " yn
  case "$yn" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${BOLD}${CYAN}"
cat <<'BANNER'
  ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗
  ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝
  █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝
  ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝
  ██║     ██║  ██║██║██████╔╝██║  ██║   ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝
BANNER
echo -e "${NC}${BOLD}  Fully Responsive Intelligent Digital Assistant for You${NC}"
echo -e "  First-time setup  ·  $(date '+%Y-%m-%d %H:%M')\n"

# ── OS detection ──────────────────────────────────────────────────────────────
step "Detecting operating system"
OS="unknown"; DISTRO=""
case "$OSTYPE" in
  linux-gnu*)
    OS="linux"
    if   command -v apt-get &>/dev/null; then DISTRO="debian"
    elif command -v dnf     &>/dev/null; then DISTRO="fedora"
    elif command -v pacman  &>/dev/null; then DISTRO="arch"
    fi
    ;;
  darwin*)  OS="macos" ;;
  msys*|cygwin*) OS="windows" ;;
esac
info "OS: $OS${DISTRO:+ ($DISTRO)}"

if [[ "$OS" == "windows" ]]; then
  warn "Windows detected — use WSL2 (Ubuntu) for best results."
  warn "https://learn.microsoft.com/en-us/windows/wsl/install"
  info "Continuing in WSL/MSYS environment..."
fi

# ── Python 3.11+ check ────────────────────────────────────────────────────────
step "Checking Python version (≥ 3.11 required)"
PYTHON_BIN=""
for py in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$py" &>/dev/null; then
    VER=$("$py" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || true)
    MAJOR="${VER%%.*}"; MINOR="${VER##*.}"
    if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 11 ]] 2>/dev/null; then
      PYTHON_BIN="$py"
      success "$py  ($VER)"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  err "Python ≥ 3.11 is required but was not found."
  case "$OS" in
    linux)
      [[ "$DISTRO" == "debian" ]] && echo "  sudo apt install python3.11"
      [[ "$DISTRO" == "fedora" ]] && echo "  sudo dnf install python3.11"
      [[ "$DISTRO" == "arch"   ]] && echo "  sudo pacman -S python"
      ;;
    macos) echo "  brew install python@3.11" ;;
  esac
  echo "  Or install via: https://github.com/astral-sh/uv  (uv python install 3.11)"
  exit 1
fi

# ── uv ────────────────────────────────────────────────────────────────────────
step "Checking uv (fast Python package manager)"
if ! command -v uv &>/dev/null; then
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Try common install locations
  for p in "$HOME/.cargo/bin" "$HOME/.local/bin"; do
    [[ -f "$p/uv" ]] && export PATH="$p:$PATH" && break
  done
  if command -v uv &>/dev/null; then
    success "uv installed: $(uv --version)"
  else
    err "uv installation failed."
    echo "  Install manually: https://github.com/astral-sh/uv"
    exit 1
  fi
else
  success "uv: $(uv --version)"
fi

# ── System packages ───────────────────────────────────────────────────────────
step "Installing system packages"

install_debian_pkgs() {
  # Packages needed for audio, Playwright, and general operation
  local PKGS=(
    # Audio (voice agent)
    ffmpeg          # audio codec layer used by faster-whisper & Coqui
    portaudio19-dev # sounddevice C bindings
    libsndfile1     # soundfile (WAV I/O)
    libasound2-dev  # ALSA (Linux audio)
    # Playwright Chromium runtime
    libnss3 libxss1 libatk1.0-0 libgtk-3-0 libgbm1
    libxrandr2 libasound2 libpangocairo-1.0-0 libpango-1.0-0
    # General
    git curl
  )
  local MISSING=()
  for pkg in "${PKGS[@]}"; do
    dpkg -s "$pkg" &>/dev/null 2>&1 || MISSING+=("$pkg")
  done
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    info "apt-get install: ${MISSING[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y "${MISSING[@]}"
    success "System packages installed"
  else
    success "All system packages already present"
  fi
}

case "$OS-$DISTRO" in
  linux-debian)  install_debian_pkgs ;;
  linux-fedora)
    PKGS=(ffmpeg libsndfile portaudio-devel alsa-lib-devel
          nss atk gtk3 libXrandr mesa-libgbm pango git curl)
    sudo dnf install -y "${PKGS[@]}" 2>/dev/null || warn "Some packages may need manual install"
    ;;
  linux-arch)
    PKGS=(ffmpeg libsndfile portaudio alsa-lib
          nss atk gtk3 libxrandr mesa pango git curl)
    sudo pacman -S --noconfirm --needed "${PKGS[@]}" 2>/dev/null || warn "Some packages may need manual install"
    ;;
  macos-*)
    if command -v brew &>/dev/null; then
      MISSING=()
      for pkg in ffmpeg portaudio libsndfile git; do
        brew list "$pkg" &>/dev/null 2>&1 || MISSING+=("$pkg")
      done
      if [[ ${#MISSING[@]} -gt 0 ]]; then
        info "brew install: ${MISSING[*]}"
        brew install "${MISSING[@]}"
      fi
      success "Homebrew packages OK"
    else
      warn "Homebrew not found — install from https://brew.sh for audio/voice support"
    fi
    ;;
  *)
    warn "Unknown OS/distro — skipping system package installation"
    ;;
esac

# ── Hardware detection ────────────────────────────────────────────────────────
step "Detecting hardware"

HAS_NVIDIA=false; HAS_AMD=false; HAS_MIC=false; HAS_DOCKER=false; HAS_FFMPEG=false

# ── GPU ──
echo -e "\n  ${BOLD}GPU${NC}"
if command -v nvidia-smi &>/dev/null; then
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)
  if [[ -n "$GPU_NAME" ]]; then
    HAS_NVIDIA=true
    success "NVIDIA GPU: $GPU_NAME"
    CUDA_VER=$(nvidia-smi | grep -oP 'CUDA Version: \K[0-9.]+' || true)
    [[ -n "$CUDA_VER" ]] && info "  CUDA $CUDA_VER available"
    info "  → Set WHISPER_DEVICE=cuda in .env for faster voice transcription"
  fi
elif command -v rocm-smi &>/dev/null; then
  HAS_AMD=true
  success "AMD GPU detected (ROCm)"
  info "  → faster-whisper supports ROCm — check project docs"
else
  info "No dedicated GPU — CPU mode for all AI inference"
fi

# ── Microphone / Audio ──
echo -e "\n  ${BOLD}Audio${NC}"
if [[ "$OS" == "linux" ]]; then
  if command -v arecord &>/dev/null && arecord -l 2>/dev/null | grep -q "card"; then
    HAS_MIC=true
    MIC_INFO=$(arecord -l 2>/dev/null | grep "card" | head -1 || true)
    success "Microphone: $MIC_INFO"
  elif [[ -d /dev/snd ]] && ls /dev/snd/pcm*c 2>/dev/null | head -1 &>/dev/null; then
    HAS_MIC=true
    success "Audio capture device found"
  else
    warn "No microphone detected — voice agent requires a microphone"
  fi
elif [[ "$OS" == "macos" ]]; then
  HAS_MIC=true
  success "Audio system available (macOS)"
fi

if [[ "$HAS_MIC" == false && "$OS" == "linux" ]]; then
  info "  → Confirm mic is connected and ALSA/PulseAudio is running"
  info "  → Run:  arecord -l"
fi

# ── Docker ──
echo -e "\n  ${BOLD}Docker${NC}"
if command -v docker &>/dev/null; then
  if docker info &>/dev/null 2>&1; then
    HAS_DOCKER=true
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    success "Docker $DOCKER_VER (daemon running)"
    info "  → auto-browser (managed Playwright + noVNC) is available"
    if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
      success "Docker Compose available"
    else
      warn "docker compose plugin not found — needed for auto-browser"
    fi
  else
    warn "Docker installed but daemon not running — start with: sudo systemctl start docker"
  fi
else
  warn "Docker not found — auto-browser requires Docker"
  info "  → Install: https://docs.docker.com/get-docker/"
fi

# ── ffmpeg ──
echo -e "\n  ${BOLD}ffmpeg${NC}"
if command -v ffmpeg &>/dev/null; then
  HAS_FFMPEG=true
  FFMPEG_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
  success "ffmpeg $FFMPEG_VER"
else
  warn "ffmpeg not found — required for voice pipeline"
fi

# ── Python deps ───────────────────────────────────────────────────────────────
step "Installing Python dependencies"
uv sync
success "Core dependencies installed"

# ── Playwright Chromium ───────────────────────────────────────────────────────
step "Installing Playwright Chromium browser"
uv run playwright install chromium
success "Playwright Chromium ready"

# ── Voice extras ──────────────────────────────────────────────────────────────
INSTALLED_VOICE=false
if [[ "$HAS_MIC" == true ]]; then
  step "Voice agent (optional)"
  echo -e "  Microphone detected. Voice deps add Coqui TTS + faster-whisper (~600 MB models on first run)."
  if ask "Install voice extras?"; then
    uv sync --extra voice
    success "Voice extras installed"
    INSTALLED_VOICE=true
    if [[ "$HAS_NVIDIA" == true ]]; then
      info "CUDA GPU found — add WHISPER_DEVICE=cuda to .env for faster transcription"
    fi
  else
    info "Skipped. Install later: uv sync --extra voice"
  fi
else
  info "Voice extras skipped (no microphone detected). Install later: uv sync --extra voice"
fi

# ── Auto-browser ──────────────────────────────────────────────────────────────
SETUP_AUTO_BROWSER=false
if [[ "$HAS_DOCKER" == true ]]; then
  step "Auto-browser (optional)"
  echo -e "  Docker available. auto-browser gives Friday a managed browser with human takeover and auth profiles."
  if ask "Set up auto-browser?"; then
    if [[ ! -d "external/auto-browser" ]]; then
      info "Cloning LvcidPsyche/auto-browser..."
      mkdir -p external
      git clone --depth 1 https://github.com/LvcidPsyche/auto-browser.git external/auto-browser
      success "Cloned to external/auto-browser"
    else
      success "external/auto-browser already present"
    fi
    SETUP_AUTO_BROWSER=true
  else
    info "Skipped. Set up later:"
    info "  git clone https://github.com/LvcidPsyche/auto-browser.git external/auto-browser"
  fi
fi

# ── .env setup ────────────────────────────────────────────────────────────────
step "Environment configuration"

# Bootstrap from example if .env doesn't exist yet
[[ ! -f ".env" ]] && cp .env.example .env && success ".env created from .env.example"

# ── Helpers ──
# Write or update a single KEY=VALUE in .env (handles existing, commented, or absent keys)
set_env() {
  local key="$1" value="$2"
  # Escape value for use as sed replacement (& and | need escaping)
  local esc_value
  esc_value=$(printf '%s' "$value" | sed 's/[&|\\]/\\&/g')
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${esc_value}|" .env
  elif grep -qE "^#\s*${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^#\s*${key}=.*|${key}=${esc_value}|" .env
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
  rm -f .env.bak
}

# Read current value of KEY from .env (strips surrounding quotes)
get_env() {
  grep "^${1}=" .env 2>/dev/null | cut -d= -f2- | tr -d "'\""
}

# Prompt: prompt_input <display_label> <KEY> [--secret] [--default <fallback>]
prompt_input() {
  local label="$1" key="$2"
  local secret=false default=""
  shift 2
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --secret)  secret=true ;;
      --default) default="$2"; shift ;;
    esac
    shift
  done

  local current
  current=$(get_env "$key")
  local hint="${current:-${default}}"
  local display_hint=""
  if [[ -n "$hint" ]]; then
    if [[ "$secret" == true ]]; then
      display_hint=" [****]"
    else
      display_hint=" [${hint}]"
    fi
  fi

  local val
  if [[ "$secret" == true ]]; then
    read -r -s -p "  ${label}${display_hint}: " val; echo ""
  else
    read -r -p "  ${label}${display_hint}: " val
  fi

  # Use entered value, fall back to current, then default
  val="${val:-${current:-${default}}}"
  if [[ -n "$val" ]]; then
    set_env "$key" "$val"
    [[ "$secret" == false ]] && success "${key}=${val}" || success "${key} set"
  else
    warn "${key} left empty"
  fi
}

if [[ "$NON_INTERACTIVE" == true ]]; then
  info "Non-interactive mode — skipping guided .env setup. Edit .env manually."
else
  echo ""
  echo -e "  ${BOLD}Guided configuration${NC} — press Enter to keep the value shown in brackets."
  echo ""

  # ── Telegram ──
  echo -e "  ${BOLD}Telegram${NC}  (get a token from @BotFather)"
  prompt_input "Bot Token" "TELEGRAM_TOKEN" --secret
  echo ""
  echo -e "  ${BOLD}Security${NC}  (restrict the bot to specific users — recommended)"
  echo -e "  Get your Telegram user ID from @userinfobot. Comma-separate multiple IDs."
  prompt_input "Allowed User IDs (leave empty = public)" "ALLOWED_USER_IDS"
  echo ""

  # ── AI Provider ──
  echo -e "  ${BOLD}AI Provider${NC}"
  echo ""
  echo -e "    1) ${CYAN}Gemini${NC}   (Google)        — free tier available · gemini-2.5-flash"
  echo -e "    2) ${CYAN}OpenAI${NC}                   — GPT-4o · requires paid API credits"
  echo -e "    3) ${CYAN}Copilot${NC} (GitHub Models)  — included with GitHub Copilot subscription"
  echo -e "    4) ${CYAN}Ollama${NC}                   — fully local · no API key · no cloud"
  echo ""

  _cur_provider=$(get_env "LLM_PROVIDER")
  case "$_cur_provider" in
    openai)  _default_num=2 ;; copilot) _default_num=3 ;;
    ollama)  _default_num=4 ;; *)       _default_num=1 ;;
  esac

  read -r -p "  Choose provider [${_default_num}]: " _pnum
  _pnum="${_pnum:-${_default_num}}"
  echo ""

  case "$_pnum" in
    1|gemini)
      set_env "LLM_PROVIDER" "gemini"
      echo -e "  ${BOLD}Gemini setup${NC}"
      echo -e "  Default model : gemini-2.5-flash"
      echo -e "  Other models  : gemini-2.5-pro  |  gemini-1.5-flash  |  gemini-1.5-pro"
      echo -e "  Get API key   → ${CYAN}https://aistudio.google.com/app/apikey${NC}  (free)"
      echo ""
      prompt_input "Google API Key" "GOOGLE_API_KEY" --secret
      prompt_input "Model override (Enter = gemini-2.5-flash)" "LLM_MODEL"
      ;;
    2|openai)
      set_env "LLM_PROVIDER" "openai"
      echo -e "  ${BOLD}OpenAI setup${NC}"
      echo -e "  Default model : gpt-4o"
      echo -e "  Other models  : gpt-4o-mini  |  gpt-4-turbo  |  o3-mini"
      echo -e "  Get API key   → ${CYAN}https://platform.openai.com/api-keys${NC}"
      echo ""
      prompt_input "OpenAI API Key" "OPENAI_API_KEY" --secret
      prompt_input "Model override (Enter = gpt-4o)" "LLM_MODEL"
      ;;
    3|copilot)
      set_env "LLM_PROVIDER" "copilot"
      echo -e "  ${BOLD}GitHub Copilot / Models setup${NC}"
      echo -e "  Default model : gpt-4o  (via GitHub Models API)"
      echo -e "  Other models  : gpt-4o-mini  |  o3-mini  |  claude-3.5-sonnet"
      echo -e "  Requires      : active GitHub Copilot subscription"
      echo -e "  Get token     → ${CYAN}https://github.com/settings/tokens${NC}"
      echo -e "                  (scopes needed: read:user — or use a classic token)"
      echo ""
      prompt_input "GitHub Token" "GH_TOKEN" --secret
      prompt_input "Model override (Enter = gpt-4o)" "COPILOT_MODEL"
      ;;
    4|ollama)
      set_env "LLM_PROVIDER" "ollama"
      echo -e "  ${BOLD}Ollama setup${NC}  (local inference — no API key)"
      if command -v ollama &>/dev/null; then
        _models=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | tr '\n' '  ' || true)
        [[ -n "$_models" ]] && echo -e "  Installed models: ${CYAN}${_models}${NC}"
      else
        warn "  ollama not in PATH — install from ${CYAN}https://ollama.com${NC}"
        info "  Then pull a model: ollama pull llama3"
      fi
      echo ""
      prompt_input "Ollama URL" "OLLAMA_URL" --default "http://localhost:11434"
      prompt_input "Ollama Model" "OLLAMA_MODEL" --default "llama3"
      prompt_input "Model override (Enter = OLLAMA_MODEL)" "LLM_MODEL"
      ;;
    *)
      warn "Invalid choice — keeping current provider '${_cur_provider:-gemini}'"
      ;;
  esac
  echo ""

  # ── Home Assistant (optional) ──
  if ask "Configure Home Assistant? (optional)"; then
    echo ""
    prompt_input "Home Assistant URL" "HA_URL" --default "http://homeassistant.local:8123"
    echo -e "  Long-lived token → HA → Profile → Security → Long-Lived Access Tokens"
    prompt_input "Home Assistant Token" "HA_TOKEN" --secret
    echo ""
  fi
fi

# ── Hardware-aware auto-writes ──
if [[ "$HAS_NVIDIA" == true && "$INSTALLED_VOICE" == true ]]; then
  if ! grep -q "^WHISPER_DEVICE=cuda" .env 2>/dev/null; then
    set_env "WHISPER_DEVICE" "cuda"
    success "WHISPER_DEVICE=cuda written (NVIDIA GPU detected)"
  fi
fi

if [[ "$SETUP_AUTO_BROWSER" == true ]]; then
  current_ab=$(get_env "AUTO_BROWSER_URL")
  if [[ -z "$current_ab" ]]; then
    set_env "AUTO_BROWSER_URL" "http://127.0.0.1:8000"
    success "AUTO_BROWSER_URL=http://127.0.0.1:8000 written"
  fi
fi

# ── Directories ───────────────────────────────────────────────────────────────
step "Creating required directories"
mkdir -p memory skills/installed skills/backups
[[ ! -f skills/installed/.gitkeep ]] && touch skills/installed/.gitkeep
success "Directories OK"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Friday setup complete!${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Hardware summary${NC}"
echo -e "  Python    $("$PYTHON_BIN" --version)"
echo -e "  uv        $(uv --version)"
if   [[ "$HAS_NVIDIA" == true ]]; then echo -e "  GPU       NVIDIA (CUDA available)"
elif [[ "$HAS_AMD"    == true ]]; then echo -e "  GPU       AMD (ROCm)"
else                                    echo -e "  GPU       CPU only"; fi
echo -e "  Mic       $([[ "$HAS_MIC"    == true ]] && echo '✓ detected'  || echo '✗ not found')"
echo -e "  Docker    $([[ "$HAS_DOCKER" == true ]] && echo '✓ running'   || echo '✗ not available')"
echo -e "  ffmpeg    $([[ "$HAS_FFMPEG" == true ]] && echo '✓'           || echo '✗ not found')"
echo ""
echo -e "  ${BOLD}Next steps${NC}"
echo ""
echo -e "  1. Edit ${CYAN}.env${NC}:"
echo -e "       TELEGRAM_TOKEN=<your-bot-token>       # from @BotFather"
echo -e "       LLM_PROVIDER=gemini                   # or openai / copilot / ollama"
echo -e "       GOOGLE_API_KEY=<key>                  # if using Gemini"
echo ""
echo -e "  2. Start the Telegram agent:"
echo -e "       ${CYAN}uv run friday_agent${NC}"
echo ""
if [[ "$INSTALLED_VOICE" == true ]]; then
echo -e "  3. Start the desktop voice agent:"
echo -e "       ${CYAN}uv run friday_voice${NC}"
echo ""
fi
if [[ "$SETUP_AUTO_BROWSER" == true ]]; then
echo -e "  4. Start the auto-browser:"
echo -e "       ${CYAN}docker compose -f docker-compose.auto-browser.yml up -d${NC}"
echo -e "       Dashboard → http://127.0.0.1:8000/dashboard"
echo -e "       VNC takeover → http://127.0.0.1:6080/vnc.html"
echo ""
fi
echo -e "  Docs: ${CYAN}README.md${NC}"
echo ""
