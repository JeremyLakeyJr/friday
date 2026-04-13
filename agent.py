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

from dotenv import load_dotenv
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

from friday.tools import web, system, utils, bash, browser
from friday.config import config
from friday.llm import build_llm

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("friday-agent")


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

TOOL_SCHEMAS = collector._schemas
logger.info("Registered %d tools: %s", len(TOOL_SCHEMAS), [s["function"]["name"] for s in TOOL_SCHEMAS])

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Friday — an autonomous AI assistant running on the user's computer.
You have access to powerful tools: bash shell execution, a web browser (Playwright), web search, and more.
Be concise, direct, and action-oriented. When the user asks you to do something, do it with tools — don't just explain how.
For multi-step tasks, chain tool calls systematically.
When you take a screenshot, the image will be sent to the user automatically — just say what you see.
Always report tool errors clearly."""

# ---------------------------------------------------------------------------
# Conversation history (per chat_id, in-memory)
# ---------------------------------------------------------------------------

_history: dict[int, list[dict]] = {}
MAX_HISTORY = 40  # keep last N messages


def _get_history(chat_id: int) -> list[dict]:
    if chat_id not in _history:
        _history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
    history = _get_history(chat_id)
    history.append({"role": "user", "content": user_text})

    llm = build_llm()
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
                    raw_b64 = tool_output.split(",", 1)[1]
                    image_bytes = base64.b64decode(raw_b64)
                    tool_output = "[screenshot attached]"

                if image_bytes:
                    responses.append(("📸 Screenshot:", image_bytes))

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
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

    # Fallback if max iterations hit
    _trim_history(chat_id)
    return responses or [("I hit the tool-call limit for this turn.", None)]


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Friday online.*\n\n"
        "I'm your autonomous AI agent. I can:\n"
        "• Run bash commands on this machine\n"
        "• Control a web browser (Playwright)\n"
        "• Search the web (DuckDuckGo)\n"
        "• Fetch world news\n"
        "• Read & write files\n\n"
        "Just tell me what to do.\n"
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    if not user_text.strip():
        return

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        responses = await _run_agent_turn(chat_id, user_text)
    except Exception as e:
        logger.exception("Agent turn failed")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    for text, image_bytes in responses:
        if image_bytes:
            await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=text)
        elif text:
            # Telegram message max length is 4096; split if needed
            for chunk in _split_text(text):
                await update.message.reply_text(chunk)


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

    logger.info("Friday agent starting (LLM_PROVIDER=%s)…", config.LLM_PROVIDER)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
