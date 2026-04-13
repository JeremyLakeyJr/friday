# Friday — Autonomous AI Agent

> *"Fully Responsive Intelligent Digital Assistant for You"*

An autonomous AI agent that lives on your machine and is accessible via **Telegram**.  
It can browse the web, run bash commands, search the internet, and more — all triggered by a text message.

---

## What it can do

| Capability | Tool | Notes |
|---|---|---|
| Run shell commands | `run_bash` | Full bash access, 30s timeout |
| Read / write files | `read_file`, `write_file` | Local filesystem |
| Control a browser | `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_get_text` | Headless Chromium via Playwright |
| Search the web | `search_web` | DuckDuckGo — no API key |
| World news | `get_world_news` | Live RSS (BBC, CNBC, NYT, Al Jazeera) |
| Fetch a URL | `fetch_url` | Raw page content |
| System info | `get_system_info`, `get_current_time` | Host machine details |
| 🎙️ Voice messages | — | Telegram voice notes transcribed via OpenAI Whisper API |

All tools run **locally** on your machine. No paid third-party APIs required (beyond your chosen LLM).

---

## Architecture

```
You (Telegram — text or 🎙️ voice)
       ↓
Telegram Bot  (agent.py)
       ↓  voice note → OpenAI Whisper API → text
LLM  (Gemini / OpenAI / GitHub Copilot / Ollama)
       ↓  tool calls
Tool layer  (bash · browser · web search · news · system)
       ↓
Your machine
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
uv sync                                  # core agent deps
uv run playwright install chromium       # download Chromium for browser tools
# Optional: voice interface
# uv sync --extra voice
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set TELEGRAM_TOKEN and one LLM provider key
```

### 4. Run

```bash
uv run friday_agent
```

The bot starts polling Telegram. Open your bot in the Telegram app and send it a message.

---

## LLM Providers

Set `LLM_PROVIDER` in `.env`:

| Value | What it uses | Key needed |
|---|---|---|
| `gemini` *(default)* | Google Gemini 2.5 Flash | `GOOGLE_API_KEY` |
| `openai` | OpenAI GPT-4o | `OPENAI_API_KEY` |
| `copilot` | GitHub Models API (Copilot) | `GH_TOKEN` |
| `ollama` | Self-hosted Ollama | none (set `OLLAMA_URL`) |

Override the default model with `LLM_MODEL=your-model-name`.

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/reset` | Clear conversation history for this chat |
| `/tools` | List all available tools |

---

## Optional: Voice interface (standalone agent)

The standalone LiveKit voice agent (`agent_friday.py`) now uses **OpenAI Whisper** (`whisper-1`) for speech-to-text instead of Sarvam.

> **Telegram voice messages are supported out of the box** — no extra setup required beyond setting `OPENAI_API_KEY`. Just send a voice note to your bot.

To run the standalone voice agent (requires LiveKit):

```bash
# Terminal 1 — MCP server
uv run friday

# Terminal 2 — Voice agent
uv sync --extra voice
uv run friday_voice
```

---

## Adding a new tool

1. Create or open a file in `friday/tools/`
2. Define a `register(mcp)` function and decorate tools with `@mcp.tool()`
3. Import and call `register(mcp)` in `friday/tools/__init__.py`

The tool is immediately available to both the Telegram agent and the MCP voice server.

---

## Tech stack

- **[python-telegram-bot](https://python-telegram-bot.org/)** — Telegram interface
- **[Playwright](https://playwright.dev/python/)** — headless browser automation
- **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** — free web search
- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server (voice mode)
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager

---

## License

MIT

