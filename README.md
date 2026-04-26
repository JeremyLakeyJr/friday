# Friday — Autonomous AI Agent

> *"Fully Responsive Intelligent Digital Assistant for You"*

An autonomous AI agent that lives on your machine, accessible via **Telegram** (text or 🎙️ voice).  
Controls your computer, browses the web, manages your smart home, and remembers everything you tell it — across sessions.

---

## What it can do

| Capability | Tools | Notes |
|---|---|---|
| 🖥️ Run shell commands | `run_bash` | Full bash access, configurable timeout |
| 📁 Read / write files | `read_file`, `write_file` | Local filesystem |
| 🌐 Control a browser | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_get_html`, `browser_current_url` | Headless Chromium via Playwright, per-chat isolation |
| 🖥️ Managed browser | `ab_navigate`, `ab_screenshot`, `ab_click`, `ab_type`, `ab_scroll`, `ab_get_text`, `ab_get_html`, `ab_current_url`, `ab_wait`, `ab_exec_js` | Docker-based browser with human takeover + auth profiles |
| 🔍 Search the web | `search_web` | DuckDuckGo — no API key |
| 📰 World news | `get_world_news` | Live RSS headlines |
| 🔗 Fetch a URL | `fetch_url` | Raw page content, no browser overhead |
| 🏠 Home Assistant | `ha_get_states`, `ha_get_state`, `ha_call_service`, `ha_list_domains` | Control lights, switches, climate, media, scripts |
| 🧠 Persistent memory | `add_memory`, `update_memory`, `search_memory`, `forget_memory`, `list_memories` | SQLite + FTS5 — relevant facts injected per turn |
| 🧩 Skills (self-extending) | `skill_install`, `skill_activate`, `skill_deactivate`, `skill_rollback`, `skill_list`, `skill_get`, `skill_validate`, `skill_export`, `skill_search`, `skill_delete` | Install markdown-based skill docs at runtime |
| 🎙️ Voice messages | — | Telegram voice notes → OpenAI Whisper |
| 🛠️ Utilities | `format_json`, `word_count`, `get_system_info`, `get_current_time` | System info + text tools |

38 tools total. No paid third-party APIs required beyond your chosen LLM.

---

## Architecture

```
You (Telegram — text or 🎙️ voice)
       ↓
agent.py  (Telegram bot + tool loop)
       ↓  voice → OpenAI Whisper → text
LLM  (Gemini / OpenAI / GitHub Copilot / Ollama)
       ↓  tool calls (up to 10 per turn)
┌──────────────────────────────────────────────────────────────────────┐
│  bash · browser · auto-browser · web · news · HA · memory · skills  │
└──────────────────────────────────────────────────────────────────────┘
       ↓                 ↓                               ↓
Your machine   Docker (auto-browser)            memory/friday.db (SQLite)
                  managed Chromium             skills/installed/*.md
```

---

## Quick start

### 1. Prerequisites

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — installed automatically by `setup.sh`
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (free)
- API key for your chosen LLM (or a local Ollama install)

### 2. Clone & run setup

```bash
git clone https://github.com/JeremyLakeyJr/friday.git
cd friday
bash setup.sh
```

`setup.sh` handles everything:
- Detects your OS (Debian/Ubuntu, Fedora, Arch, macOS)
- Installs system packages (`ffmpeg`, `portaudio`, Playwright runtime deps)
- Detects hardware — **NVIDIA GPU** (auto-enables CUDA for Whisper), **microphone** (offers voice install), **Docker** (offers auto-browser setup)
- Runs `uv sync` and `playwright install chromium`
- Creates `.env` from `.env.example`
- Optionally installs voice extras and clones auto-browser

Run with `--non-interactive` / `-y` to skip all prompts (CI/server use).

### 3. Configure

Edit the generated `.env`:

```env
TELEGRAM_TOKEN=your-bot-token
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your-key
```

Optional — restrict to specific Telegram users (recommended):
```env
ALLOWED_USER_IDS=123456789,987654321
```
Get your ID from [@userinfobot](https://t.me/userinfobot).

### 4. Run

```bash
uv run friday_agent
```

Open your bot in Telegram and send it a message — text or voice.

---

## Desktop voice agent

Talk to Friday directly on your desktop — no Telegram, no cloud audio API. Uses local models.

```bash
# Install voice deps (Coqui TTS + faster-whisper + sounddevice)
uv sync --extra voice

# (First run downloads TTS + Whisper models — ~600 MB with default settings)
uv run friday_voice
```

Speak after the `🎤 Listening…` prompt. Friday responds aloud with full tool access.

### Voice model options

Set in `.env` — all optional:

| Variable | Default | Notes |
|---|---|---|
| `WHISPER_MODEL` | `base.en` | `tiny.en` (fast) → `medium.en` (accurate) |
| `WHISPER_DEVICE` | `cpu` | `cuda` for GPU |
| `TTS_MODEL` | `tts_models/en/ljspeech/tacotron2-DDC` | Light, English only |
| `TTS_SPEAKER` | _(blank)_ | Required for multi-speaker models (e.g. XTTS-v2) |
| `TTS_LANGUAGE` | `en` | For multilingual models only |
| `VAD_THRESHOLD` | `0.015` | RMS mic sensitivity |

**Best quality voice (XTTS-v2):**
```env
TTS_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
TTS_SPEAKER=Ana Florence
TTS_LANGUAGE=en
```

---

## LLM Providers

| `LLM_PROVIDER` | Model | Key needed |
|---|---|---|
| `gemini` *(default)* | Gemini 2.5 Flash | `GOOGLE_API_KEY` |
| `openai` | GPT-4o | `OPENAI_API_KEY` |
| `copilot` | GitHub Models API | `GH_TOKEN` |
| `ollama` | any local model | `OLLAMA_URL` + `OLLAMA_MODEL` |

Override the model: `LLM_MODEL=gemini-1.5-pro`

---

## Home Assistant

Add to `.env`:
```env
HA_URL=http://homeassistant.local:8123
HA_TOKEN=<long-lived token from HA → Profile → Security>
```

Then just tell Friday: *"turn off the kitchen lights"*, *"set thermostat to 22°"*, *"what's the living room temperature?"*

Friday will discover your entity IDs automatically via `ha_list_domains` + `ha_get_states`.

---

## Persistent Memory

Friday stores facts in a SQLite database (`memory/friday.db`) that survives across sessions.

| Importance | Behaviour |
|---|---|
| 5 — pinned | Always injected into every prompt (user's name, key preferences) |
| 3 — normal | Injected only when FTS-relevant to the current message |
| 1 — archived | Never auto-injected, but searchable with `search_memory` |

Friday saves new information silently — no permission needed. To inspect or manage memory, ask Friday directly: *"list my memories"*, *"forget that I told you X"*.

---

## Auto-browser

Friday includes a second browser mode powered by [LvcidPsyche/auto-browser](https://github.com/LvcidPsyche/auto-browser) — a Docker-based Playwright control plane with a live noVNC dashboard, auth profile persistence, and human-in-the-loop takeover.

### Why use it over the built-in browser?

| Feature | Built-in (`browser_*`) | Auto-browser (`ab_*`) |
|---|---|---|
| Setup | Zero — Playwright only | Docker required |
| Human takeover | ✗ | ✓ via VNC |
| Auth profiles | ✗ | ✓ (cookies saved) |
| Visual dashboard | ✗ | ✓ http://localhost:8000/dashboard |

### Setup

`setup.sh` will offer to clone and configure this for you. Manual steps:

```bash
git clone https://github.com/LvcidPsyche/auto-browser.git external/auto-browser
docker compose -f docker-compose.auto-browser.yml up -d
```

Add to `.env`:
```env
AUTO_BROWSER_URL=http://127.0.0.1:8000
AUTO_BROWSER_TOKEN=   # optional — set in auto-browser config if auth enabled
```

- Dashboard: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- VNC takeover: [http://127.0.0.1:6080/vnc.html](http://127.0.0.1:6080/vnc.html)

Auto-browser tools are only registered when `AUTO_BROWSER_URL` is set — the default Playwright browser is always available.

---

## Installable Skills

Friday can install new skill documentation at runtime without a restart, powered by the skill management system (ported from [JeremyLakeyJr/mcp-server](https://github.com/JeremyLakeyJr/mcp-server)).

Skills are markdown files with YAML front-matter stored in `skills/installed/`. The system supports versioned installs, rollback, and activation/deactivation.

```
skills/
  installed/      ← installed skills (managed by skill tools)
  backups/        ← previous versions (for rollback)
  registry.json   ← index of all installed skills
```

### Managing skills

Ask Friday directly:

> *"Search for available skills"*  
> *"Install the skill from https://example.com/my-skill.md"*  
> *"List all installed skills"*  
> *"Deactivate the web-scraping skill"*  
> *"Roll back the skill that broke"*

Or use the tools directly: `skill_install`, `skill_list`, `skill_activate`, `skill_deactivate`, `skill_rollback`, `skill_get`, `skill_export`, `skill_search`, `skill_delete`, `skill_validate`.

### Writing a skill

Skill files are Markdown with YAML front-matter:

```markdown
---
name: my-skill
version: 1.0.0
description: Does something useful
tags: [utility, web]
author: you
---

# My Skill

Instructions for Friday on when and how to use these capabilities...
```

---

## Built-in skill docs

Static tool documentation lives in the repo root `skills/` — loaded once at startup and injected into the system prompt. Drop a `.md` file here and restart to add usage documentation without any Python changes.

```
skills/
  shell.md          bash, read_file, write_file
  browser.md        all browser_* tools
  web.md            search_web, fetch_url, get_world_news
  memory.md         all memory tools + rules
  system.md         system info + utilities
  homeassistant.md  Home Assistant control
  installed/        runtime-installed skills (managed by skill_* tools)
```

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/reset` | Clear conversation history for this chat |
| `/tools` | List all registered tools |

---

## Adding a new tool

1. Create `friday/tools/mytool.py` with a `register(mcp)` function
2. Decorate tools with `@mcp.tool()`
3. Import and call `register(collector)` in `agent.py`
4. Add a `skills/mytool.md` with usage docs

---

## Tech stack

- **[python-telegram-bot](https://python-telegram-bot.org/)** — Telegram interface
- **[Playwright](https://playwright.dev/python/)** — headless browser automation
- **[auto-browser](https://github.com/LvcidPsyche/auto-browser)** — Docker-based managed browser with human takeover
- **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** — free web search
- **[httpx](https://www.python-httpx.org/)** — async HTTP (web + Home Assistant + auto-browser)
- **[SQLite FTS5](https://www.sqlite.org/fts5.html)** — persistent memory + full-text search
- **[PyYAML](https://pyyaml.org/)** — skill front-matter parsing
- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server transport
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager

---

## Environment variables

All variables live in `.env` (copy from `.env.example`). `setup.sh` creates it automatically.

### Core

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | ✓ | Bot token from @BotFather |
| `ALLOWED_USER_IDS` | — | Comma-separated Telegram user IDs (leave empty to allow everyone) |
| `LLM_PROVIDER` | — | `gemini` (default) / `openai` / `copilot` / `ollama` |
| `LLM_MODEL` | — | Override the default model for your provider |

### LLM API keys

| Variable | Provider |
|---|---|
| `GOOGLE_API_KEY` | Gemini |
| `OPENAI_API_KEY` | OpenAI |
| `GH_TOKEN` | GitHub Copilot / Models |
| `OLLAMA_URL` | Ollama (default `http://localhost:11434`) |
| `OLLAMA_MODEL` | Ollama model name |

### Voice agent

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base.en` | `tiny.en` → `medium.en` |
| `WHISPER_DEVICE` | `cpu` | `cuda` for NVIDIA GPU |
| `TTS_MODEL` | `tts_models/en/ljspeech/tacotron2-DDC` | Coqui TTS model |
| `TTS_SPEAKER` | — | Required for multi-speaker models (e.g. XTTS-v2) |
| `TTS_LANGUAGE` | `en` | For multilingual models |
| `VAD_THRESHOLD` | `0.015` | Mic RMS sensitivity |

### Auto-browser

| Variable | Description |
|---|---|
| `AUTO_BROWSER_URL` | Base URL of auto-browser controller (e.g. `http://127.0.0.1:8000`) |
| `AUTO_BROWSER_TOKEN` | Bearer token (if auto-browser auth is enabled) |

### Skill system (MCP server)

| Variable | Default | Description |
|---|---|---|
| `FRIDAY_MCP_SKILLS_ROOT` | `./skills` | Root directory for installed skills |
| `FRIDAY_MCP_WORKSPACE_ROOT` | `./` | Workspace root for file operations |
| `FRIDAY_MCP_TRANSPORT` | `sse` | `sse` or `stdio` |
| `FRIDAY_MCP_MAX_FETCH_CHARS` | `50000` | Max chars returned from URL fetches |
| `FRIDAY_MCP_DEFAULT_COMMAND_TIMEOUT` | `30` | Bash command timeout (seconds) |

### Home Assistant

| Variable | Description |
|---|---|
| `HA_URL` | Home Assistant URL (e.g. `http://homeassistant.local:8123`) |
| `HA_TOKEN` | Long-lived access token |

---

## License

MIT

