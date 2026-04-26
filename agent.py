"""
Friday — Autonomous Telegram Agent
====================================
A persistent AI agent that lives on your machine and is accessible via Telegram.

Features:
  - Full bash shell access (run commands, read/write files)
  - Full web browser control (Playwright, headless Chromium)
  - Web search (DuckDuckGo, no API key)
  - World news (RSS feeds)
  - System info
  - Configurable LLM: gemini | openai | copilot | ollama
  - Voice messages (transcribed via OpenAI Whisper API)

Run:
  uv run friday_agent

Commands:
  /start  — Welcome message
  /reset  — Clear conversation history for this chat
  /tools  — List available tools
"""

import asyncio
import base64
import io
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Bootstrap tools (direct import — no separate MCP server process needed)
# ---------------------------------------------------------------------------

from friday.tools import web, system, utils, bash, browser, memory as memory_tools, homeassistant as ha_tools, skills as skills_module, auto_browser as auto_browser_module
from friday.config import config
from friday.llm import get_llm

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("friday-agent")

# Lazy OpenAI client for Whisper transcription (created on first voice message)
_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _openai_client


# ---------------------------------------------------------------------------
# Build tool registry from MCP-style register() functions
# ---------------------------------------------------------------------------

class _ToolCollector:
    """Minimal shim that collects tool functions registered via @mcp.tool()."""

    def __init__(self):
        self._tools: dict[str, callable] = {}
        self._schemas: list[dict] = []

    def tool(self):
        import inspect

        def decorator(fn):
            self._tools[fn.__name__] = fn
            # Build JSON schema from type hints / docstring
            sig = inspect.signature(fn)
            params: dict = {"type": "object", "properties": {}, "required": []}
            for name, param in sig.parameters.items():
                annotation = param.annotation
                if annotation == inspect.Parameter.empty:
                    ptype = "string"
                elif annotation == int:
                    ptype = "integer"
                elif annotation == bool:
                    ptype = "boolean"
                else:
                    ptype = "string"
                params["properties"][name] = {"type": ptype}
                if param.default == inspect.Parameter.empty:
                    params["required"].append(name)
            self._schemas.append({
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": (fn.__doc__ or "").strip(),
                    "parameters": params,
                },
            })
            return fn
        return decorator

    async def call(self, name: str, arguments: dict):
        fn = self._tools.get(name)
        if fn is None:
            return f"Unknown tool: {name}"
        try:
            result = fn(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            return f"Tool error ({name}): {e}"


collector = _ToolCollector()
web.register(collector)
system.register(collector)
utils.register(collector)
bash.register(collector)
browser.register(collector)
memory_tools.register(collector)
ha_tools.register(collector)

from pathlib import Path
from friday.tools.skill_store import SkillStore

_skill_store = SkillStore(Path(config.FRIDAY_MCP_SKILLS_ROOT).expanduser().resolve())
skills_module.register(collector, skill_store=_skill_store)
auto_browser_module.register(collector)

TOOL_SCHEMAS = collector._schemas
logger.info("Registered %d tools: %s", len(TOOL_SCHEMAS), [s["function"]["name"] for s in TOOL_SCHEMAS])

# ---------------------------------------------------------------------------
# Security — allowed user whitelist
# ---------------------------------------------------------------------------

_raw_ids = config.ALLOWED_USER_IDS.strip()
ALLOWED_USER_IDS: frozenset[int] = (
    frozenset(int(i) for i in _raw_ids.split(",") if i.strip())
    if _raw_ids else frozenset()
)
if not ALLOWED_USER_IDS:
    logger.warning("ALLOWED_USER_IDS not set — bot is open to ALL users!")


def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


# ---------------------------------------------------------------------------
# Per-chat concurrency lock
# ---------------------------------------------------------------------------

_chat_locks: dict[int, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """You are Friday (F.R.I.D.A.Y.) — an autonomous AI assistant running directly on the user's machine.
Be concise, direct, and action-oriented. When asked to do something, DO it with tools — don't just explain how.
Chain multiple tool calls in one turn for complex tasks. Report errors clearly.

## Decision rules
- Run code / install / check system? → run_bash
- Browse a website visually? → browser_navigate → browser_screenshot
- Find info online? → search_web first, then browser_navigate or fetch_url
- Read/write files on disk? → read_file / write_file
- User shares personal info (name, prefs, projects)? → add_memory immediately (don't ask)
- Screenshot taken? → describe what you see; Telegram sends the image automatically

## Skills loaded below — full tool docs are in skills/*.md"""


def _load_skills() -> str:
    """Read all skills/*.md files and return combined text."""
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.exists():
        return ""
    parts = []
    for path in sorted(skills_dir.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)


_SKILLS_CONTENT = _load_skills()  # loaded once at startup

# ---------------------------------------------------------------------------
# Conversation history (per chat_id, in-memory)
# ---------------------------------------------------------------------------

_history: dict[int, list[dict]] = {}
MAX_HISTORY = 40  # keep last N messages


def _get_system_prompt(user_text: str = "") -> str:
    """Build system prompt: base identity + skill docs + relevant memory."""
    from friday.tools.memory import get_memory_context
    return _BASE_SYSTEM_PROMPT + "\n\n" + _SKILLS_CONTENT + get_memory_context(user_text)


def _get_history(chat_id: int, user_text: str = "") -> list[dict]:
    if chat_id not in _history:
        _history[chat_id] = [{"role": "system", "content": _get_system_prompt(user_text)}]
    else:
        _history[chat_id][0] = {"role": "system", "content": _get_system_prompt(user_text)}
    return _history[chat_id]


def _trim_history(chat_id: int):
    h = _history[chat_id]
    # Keep system message + last MAX_HISTORY exchanges
    if len(h) > MAX_HISTORY + 1:
        _history[chat_id] = [h[0]] + h[-(MAX_HISTORY):]


# ---------------------------------------------------------------------------
# Agent loop — one turn
# ---------------------------------------------------------------------------

async def _run_agent_turn(chat_id: int, user_text: str) -> list[tuple[str, bytes | None]]:
    """
    Process one user message through the LLM + tool loop.
    Returns list of (text, image_bytes_or_None) tuples to send back.
    """
    from friday.tools.browser import current_chat_id
    current_chat_id.set(chat_id)

    history = _get_history(chat_id, user_text)
    history.append({"role": "user", "content": user_text})

    llm = get_llm()
    responses: list[tuple[str, bytes | None]] = []

    for _ in range(10):  # max tool-call iterations per turn
        result = await llm.chat(history, tools=TOOL_SCHEMAS)

        if result.tool_calls:
            # Append assistant message with tool calls
            history.append({
                "role": "assistant",
                "content": result.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in result.tool_calls
                ],
            })

            # Execute each tool call
            tool_results = []
            for tc in result.tool_calls:
                logger.info("Tool call: %s(%s)", tc.name, tc.arguments)
                tool_output = await collector.call(tc.name, tc.arguments)

                # Handle screenshot — extract base64 image
                image_bytes = None
                if isinstance(tool_output, str) and tool_output.startswith("data:image/png;base64,"):
                    try:
                        raw_b64 = tool_output.split(",", 1)[1]
                        image_bytes = base64.b64decode(raw_b64)
                        tool_output = "[screenshot attached]"
                    except Exception as exc:
                        logger.warning("Failed to decode screenshot: %s", exc)
                        tool_output = "[screenshot decode error]"

                if image_bytes:
                    responses.append(("📸 Screenshot:", image_bytes))

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": str(tool_output),
                })
                logger.debug("Tool result: %s", str(tool_output)[:200])

            history.extend(tool_results)
            # Continue loop — let LLM respond to tool results

        else:
            # Final text response
            if result.content:
                history.append({"role": "assistant", "content": result.content})
                responses.append((result.content, None))
            _trim_history(chat_id)
            return responses

    # Fallback if max iterations hit — still append a minimal assistant message
    fallback = "I hit the tool-call limit for this turn."
    history.append({"role": "assistant", "content": fallback})
    _trim_history(chat_id)
    return responses or [(fallback, None)]


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------

def _time_greeting() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning ☀️"
    if 12 <= hour < 17:
        return "Good afternoon 🌤️"
    if 17 <= hour < 21:
        return "Good evening 🌆"
    return "Good night 🌙"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 *{_time_greeting()} — Friday online.*\n\n"
        "I'm your autonomous AI agent. I can:\n"
        "• Run bash commands on this machine\n"
        "• Control a web browser (Playwright)\n"
        "• Search the web (DuckDuckGo)\n"
        "• Fetch world news\n"
        "• Read & write files\n"
        "• 🎙️ Understand voice messages (transcribed via Whisper)\n\n"
        "Just tell me what to do — by text *or* voice.\n"
        "Use /reset to clear conversation history.\n"
        "Use /tools to see available tools.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    _history.pop(chat_id, None)
    await update.message.reply_text("🔄 Conversation history cleared.")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    lines = "\n".join(f"• `{n}`" for n in names)
    await update.message.reply_text(f"*Available tools:*\n{lines}", parse_mode=ParseMode.MARKDOWN)


async def _send_responses(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    responses: list[tuple[str, bytes | None]],
) -> None:
    """Send agent responses (text and/or photos) back to the chat."""
    chat_id = update.effective_chat.id
    for text, image_bytes in responses:
        if image_bytes:
            await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=text)
        elif text:
            for chunk in _split_text(text):
                await update.message.reply_text(chunk)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("⛔ Not authorised.")
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        try:
            responses = await _run_agent_turn(chat_id, user_text)
        except Exception as e:
            logger.exception("Agent turn failed")
            await update.message.reply_text(f"⚠️ Error: {e}")
            return

    await _send_responses(update, context, responses)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a Telegram voice note via OpenAI Whisper, then run the agent."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        await update.message.reply_text("⛔ Not authorised.")
        return

    if not config.OPENAI_API_KEY:
        await update.message.reply_text(
            "⚠️ Voice transcription requires OPENAI_API_KEY to be set in .env"
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        audio_io = io.BytesIO(bytes(voice_bytes))
        audio_io.name = "voice.ogg"

        transcript = await _get_openai_client().audio.transcriptions.create(
            model="whisper-1",
            file=audio_io,
        )
        user_text = transcript.text.strip()
        logger.info("Voice → text: %r", user_text)
    except Exception as e:
        logger.exception("Voice transcription failed")
        await update.message.reply_text(f"⚠️ Transcription error: {e}")
        return

    if not user_text:
        await update.message.reply_text("⚠️ Could not understand the voice message.")
        return

    # Echo the transcription so the user knows what was heard
    await update.message.reply_text(f"🎙️ _{user_text}_", parse_mode=ParseMode.MARKDOWN)

    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        try:
            responses = await _run_agent_turn(chat_id, user_text)
        except Exception as e:
            logger.exception("Agent turn failed (voice)")
            await update.message.reply_text(f"⚠️ Error: {e}")
            return

    await _send_responses(update, context, responses)


def _split_text(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    token = config.TELEGRAM_TOKEN
    if not token:
        sys.exit("TELEGRAM_TOKEN is not set. Get one from @BotFather and add it to .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    async def _shutdown(_app):
        from friday.tools.browser import close_browser
        await close_browser()

    app.post_shutdown(_shutdown)

    logger.info("Friday agent starting (LLM_PROVIDER=%s)…", config.LLM_PROVIDER)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
