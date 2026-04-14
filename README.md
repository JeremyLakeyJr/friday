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
| 🔍 Search the web | `search_web` | DuckDuckGo — no API key |
| 📰 World news | `get_world_news` | Live RSS headlines |
| 🔗 Fetch a URL | `fetch_url` | Raw page content, no browser overhead |
| 🏠 Home Assistant | `ha_get_states`, `ha_get_state`, `ha_call_service`, `ha_list_domains` | Control lights, switches, climate, media, scripts |
| 🧠 Persistent memory | `add_memory`, `update_memory`, `search_memory`, `forget_memory`, `list_memories` | SQLite + FTS5 — relevant facts injected per turn |
| 🎙️ Voice messages | — | Telegram voice notes → OpenAI Whisper |
| 🛠️ Utilities | `format_json`, `word_count`, `get_system_info`, `get_current_time` | System info + text tools |

27 tools total. No paid third-party APIs required beyond your chosen LLM.

---

## Architecture

```
You (Telegram — text or 🎙️ voice)
       ↓
agent.py  (Telegram bot + tool loop)
       ↓  voice → OpenAI Whisper → text
LLM  (Gemini / OpenAI / GitHub Copilot / Ollama)
       ↓  tool calls (up to 10 per turn)
┌──────────────────────────────────────────────────┐
│  bash · browser · web · news · HA · memory · sys  │
└──────────────────────────────────────────────────┘
       ↓                              ↓
Your machine                  memory/friday.db (SQLite)
                              skills/*.md (tool docs)
```

---

## Quick start

### 1. Prerequisites

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — `pip install uv`
- A Telegram bot token from [@BotFather](https://t.me/BotFather) (free)
- API key for your chosen LLM (or a local Ollama install)

### 2. Clone & install

```bash
git clone https://github.com/JeremyLakeyJr/friday.git
cd friday
uv sync
uv run playwright install chromium   # headless browser
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set TELEGRAM_TOKEN and at least one LLM key
```

Minimum `.env`:
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

## Skills system

Tool documentation lives in `skills/*.md` — loaded once at startup and injected into the system prompt. The base prompt stays under 1 KB; skill docs add ~6 KB.

To teach Friday a new capability: drop a `.md` file in `skills/` and restart. No Python changes needed for documentation updates.

```
skills/
  shell.md          bash, read_file, write_file
  browser.md        all browser_* tools
  web.md            search_web, fetch_url, get_world_news
  memory.md         all memory tools + rules
  system.md         system info + utilities
  homeassistant.md  Home Assistant control
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
- **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** — free web search
- **[httpx](https://www.python-httpx.org/)** — async HTTP (web + Home Assistant)
- **[SQLite FTS5](https://www.sqlite.org/fts5.html)** — persistent memory + full-text search
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager

---

## License

MIT

