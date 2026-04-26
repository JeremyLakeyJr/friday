"""
FRIDAY – Desktop Voice Agent
==============================
Standalone desktop voice loop — no LiveKit required.

Pipeline:  mic → energy VAD → faster-whisper STT → LLM + all tools → Coqui TTS → speaker

Setup:
  uv sync --extra voice
  uv run playwright install chromium   # only if you use browser tools
  uv run python voice_agent.py

.env variables (all optional — defaults shown):
  WHISPER_MODEL=base.en              # tiny.en / base.en / small.en / medium.en
  WHISPER_DEVICE=cpu                 # cpu or cuda

  TTS_MODEL=tts_models/en/ljspeech/tacotron2-DDC
    # Upgrade options:
    #   tts_models/en/jenny/jenny              (very natural, single speaker)
    #   tts_models/multilingual/multi-dataset/xtts_v2  (best, needs TTS_SPEAKER)
  TTS_SPEAKER=                       # leave blank for single-speaker models
                                     # XTTS-v2 speakers: "Claribel Dervla", "Ana Florence", etc.
  TTS_LANGUAGE=en                    # for multilingual models only

  VAD_THRESHOLD=0.015                # RMS silence threshold (lower = more sensitive mic)
  SILENCE_SECS=1.5                   # seconds of silence that ends utterance
  MIN_SPEECH_SECS=0.4                # min speech length before transcribing
"""

import asyncio
import base64
import inspect
import json
import logging
import os
import pathlib
import queue
import tempfile
import threading
import time
from typing import Any

import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

from friday.config import config
from friday.llm import get_llm
from friday.tool_registry import register_tool, select_tools, find_matching_tools
from friday.tools import bash, browser, desktop, firefox as firefox_tools
from friday.tools import memory as memory_tools, system, utils, web
from friday.tools import homeassistant as ha_tools
from friday.tools.browser import close_browser, current_chat_id
from friday.tools.firefox import close_firefox
from friday.tools.memory import get_memory_context, _sync_add

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("friday-voice")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SAMPLE_RATE      = 16000
CHUNK_SECS       = 0.03                                         # 30 ms VAD chunks
VAD_THRESHOLD    = float(os.getenv("VAD_THRESHOLD",   "0.015"))
SILENCE_SECS     = float(os.getenv("SILENCE_SECS",    "1.5"))
MIN_SPEECH_SECS  = float(os.getenv("MIN_SPEECH_SECS", "0.4"))

WHISPER_MODEL_ID = os.getenv("WHISPER_MODEL",  "base.en")
WHISPER_DEVICE   = os.getenv("WHISPER_DEVICE", "cpu")

TTS_MODEL_ID     = os.getenv("TTS_MODEL",    "tts_models/en/ljspeech/tacotron2-DDC")
TTS_SPEAKER      = os.getenv("TTS_SPEAKER",  "") or None
TTS_LANGUAGE     = os.getenv("TTS_LANGUAGE", "en")

VOICE_CHAT_ID    = 0    # fixed chat-id for browser ContextVar (single desktop user)
MAX_TOOL_ITERS   = 6
MAX_HISTORY      = 12   # keep last N messages (6 turns) — voice is conversational
# Character budget for history passed to LLM (leave room for system prompt + tools).
# gpt-4o-mini cap ≈ 8000 tokens → ~32 000 chars; tools+system ≈ 14 000 → 18 000 left.
_HISTORY_CHAR_BUDGET = 16_000
_TOOL_RESULT_MAX     = 1_200   # max chars kept from any single tool result

# Wake word — uses faster-whisper to spot any keyword (default: "friday")
# Set WAKE_WORD_ENABLED=1 in .env to activate; configure the trigger phrase below.
WAKE_WORD_ENABLED  = os.getenv("WAKE_WORD_ENABLED",  "1") == "1"
WAKE_WORD_KEYWORD  = os.getenv("WAKE_WORD_KEYWORD",  "friday").lower()
_WAKE_SILENCE_SECS = 0.5   # short silence timeout when scanning for the wake word
_WAKE_MAX_SECS     = 2.0   # discard clip longer than this (likely not a wake word)

# Conversation mode — after a response, stay listening without needing the wake word again.
_CONVO_PROMPT      = "Anything else, boss?"
CONVO_TIMEOUT      = float(os.getenv("CONVO_TIMEOUT",      "20"))  # seconds to stay in convo mode
CONVO_PROMPT_DELAY = float(os.getenv("CONVO_PROMPT_DELAY", "5"))   # seconds before asking "anything else"

# Messages evicted from context during the current turn, pending consolidation to memory.
_pending_consolidation: list[dict] = []

# ---------------------------------------------------------------------------
# Conversation-mode state (module-level so all coroutines share it)
# ---------------------------------------------------------------------------
_convo_expires_at: float = 0.0            # unix ts when conversation mode ends
_convo_prompt_task: asyncio.Task | None = None  # "anything else?" scheduler


def _is_in_conversation() -> bool:
    return time.time() < _convo_expires_at


def _enter_conversation_mode() -> None:
    global _convo_expires_at
    _convo_expires_at = time.time() + CONVO_TIMEOUT


def _cancel_convo_prompt() -> None:
    global _convo_prompt_task
    if _convo_prompt_task and not _convo_prompt_task.done():
        _convo_prompt_task.cancel()
    _convo_prompt_task = None


async def _schedule_convo_prompt() -> None:
    """After a short pause, ask 'Anything else, boss?' if still in conversation mode."""
    try:
        await asyncio.sleep(CONVO_PROMPT_DELAY)
        if _is_in_conversation():
            await _speech_q.put((_CONVO_PROMPT, False))
    except asyncio.CancelledError:
        pass

# ---------------------------------------------------------------------------
# Pipeline queues — created in main() so they bind to the running event loop.
# ---------------------------------------------------------------------------
_speech_q: asyncio.Queue     # text → _tts_consumer
_utterance_q: asyncio.Queue  # transcribed text → _brain_consumer
_background_agent: Any       # BackgroundAgent, created in main()

# ---------------------------------------------------------------------------
# Lazy model handles
# ---------------------------------------------------------------------------

_whisper = None
_whisper_wake = None   # fast tiny.en model for wake word scanning
_tts = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper '%s' on %s …", WHISPER_MODEL_ID, WHISPER_DEVICE)
        _whisper = WhisperModel(WHISPER_MODEL_ID, device=WHISPER_DEVICE, compute_type="int8")
        logger.info("Whisper ready.")
    return _whisper


def _get_whisper_wake():
    """Load (or reuse) a tiny.en Whisper model for fast wake-word scanning."""
    global _whisper_wake
    if _whisper_wake is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper 'tiny.en' for wake-word scanning …")
        _whisper_wake = WhisperModel("tiny.en", device=WHISPER_DEVICE, compute_type="int8")
        logger.info("Wake-word model ready.")
    return _whisper_wake


def _get_tts():
    global _tts
    if _tts is None:
        # Auto-accept Coqui TTS terms of service so the download doesn't block on
        # an interactive stdin prompt (which looks like a freeze with no output).
        os.environ.setdefault("COQUI_TOS_AGREED", "1")

        from TTS.api import TTS  # type: ignore[import]
        logger.info("Loading TTS model '%s' …", TTS_MODEL_ID)
        _tts = TTS(model_name=TTS_MODEL_ID, progress_bar=True)
        speakers = getattr(_tts, "speakers", None)
        logger.info("TTS ready. Speakers: %s", speakers[:5] if speakers else "N/A (single-speaker)")
    return _tts


# ---------------------------------------------------------------------------
# Wake word utilities — Whisper-based keyword spotting, no extra model needed
# ---------------------------------------------------------------------------

def _record_wake_clip(mic: "MicCapture") -> np.ndarray | None:
    """Record a short audio clip (up to _WAKE_MAX_SECS) for wake word checking.
    
    Uses shorter silence timeout and discards clips that are too long
    (the user is talking normally, not saying the wake word).
    """
    chunks: list[np.ndarray] = []
    silent_chunks = 0
    speech_chunks = 0
    in_speech = False
    silence_limit = int(_WAKE_SILENCE_SECS / CHUNK_SECS)
    min_speech    = int(0.15 / CHUNK_SECS)
    max_speech    = int(_WAKE_MAX_SECS / CHUNK_SECS)

    while speech_chunks < max_speech:
        try:
            chunk = mic._q.get(timeout=0.5)
        except queue.Empty:
            if in_speech:
                break
            continue
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms >= VAD_THRESHOLD:
            in_speech = True
            speech_chunks += 1
            silent_chunks = 0
            chunks.append(chunk)
        elif in_speech:
            silent_chunks += 1
            chunks.append(chunk)
            if silent_chunks >= silence_limit:
                break

    if speech_chunks < min_speech or not chunks:
        return None
    return np.concatenate(chunks, axis=0).flatten()


async def _scan_for_wake_word(mic: "MicCapture") -> None:
    """Scan short clips with tiny.en Whisper until WAKE_WORD_KEYWORD is heard."""
    logger.debug("Wake word scanner active — listening for '%s'.", WAKE_WORD_KEYWORD)
    wake_model = await asyncio.to_thread(_get_whisper_wake)

    def _quick_transcribe(audio: np.ndarray) -> str:
        segs, _ = wake_model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
        return " ".join(s.text for s in segs).strip().lower()

    while True:
        audio = await asyncio.to_thread(_record_wake_clip, mic)
        if audio is None:
            continue
        text = await asyncio.to_thread(_quick_transcribe, audio)
        if WAKE_WORD_KEYWORD in text:
            logger.info("Wake word detected: '%s'", text)
            while not mic._q.empty():
                try:
                    mic._q.get_nowait()
                except queue.Empty:
                    break
            return

class _ToolCollector:
    """Minimal shim that collects tool functions registered via @mcp.tool()."""

    def __init__(self):
        self._tools: dict[str, callable] = {}
        self._schemas: list[dict] = []

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
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
                    # First line only — keeps schemas small (full docs in skills/*.md)
                    "description": ((fn.__doc__ or "").strip().split("\n")[0].strip())[:100],
                    "parameters": params,
                },
            })
            return fn
        return decorator

    async def call(self, name: str, arguments: dict) -> Any:
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
desktop.register(collector)
firefox_tools.register(collector)
memory_tools.register(collector)
ha_tools.register(collector)

# Register the find_tools meta-tool schema (handled inline, not via collector.call)
_FIND_TOOLS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "find_tools",
        "description": "Search for tools by capability. Use when the initial tool set doesn't have what you need.",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string"}
            },
            "required": ["keywords"],
        },
    },
}

TOOL_SCHEMAS = collector._schemas

# Push all schemas (including find_tools) into the SQLite dynamic registry (idempotent upsert)
for _schema in TOOL_SCHEMAS:
    register_tool(_schema)
register_tool(_FIND_TOOLS_SCHEMA)

logger.info("Registered %d tools: %s", len(TOOL_SCHEMAS), [s["function"]["name"] for s in TOOL_SCHEMAS])

# ---------------------------------------------------------------------------
# System prompt + skills
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """You are Friday (F.R.I.D.A.Y.) — an autonomous AI assistant with FULL access to the user's desktop system.
Be concise, direct, and action-oriented. When asked to do something, DO it with tools — don't just explain how.
Chain multiple tool calls in one turn for complex tasks. Report errors clearly.
You are speaking aloud — keep responses short and natural, no markdown formatting, no bullet lists.
You have complete authority to run commands, manage files, control applications, and use the internet on behalf of the user.

## Tool system
You are given a RELEVANT SUBSET of tools based on this request. If you need a tool not shown,
call find_tools(keywords="...") first — it will add matching tools to your available set.

## Decision rules
- Run code / install packages / check system? → run_bash (unrestricted sudo if needed)
- Manage processes? → list_processes / kill_process
- Manage files? → list_directory / move_file / copy_file / delete_file / search_files
- Browse a website with AI control (Chromium)? → browser_navigate → browser_screenshot
- Browse a website with Firefox? → firefox_navigate → firefox_screenshot
- Open a URL in the user's real Firefox? → firefox_open_in_system
- Find info online? → search_web first, then browser_navigate or fetch_url
- Read/write files on disk? → read_file / write_file
- Take a desktop screenshot? → take_screenshot
- Open a file or app? → open_application / open_file_with_app
- Check disk / RAM? → get_disk_usage / get_memory_usage
- User shares personal info (name, prefs, projects)? → add_memory immediately (don't ask)
- Control smart home? → ha_call_service or ha_get_state
- Send desktop notification? → send_desktop_notification
- Need a tool not in the current set? → find_tools(keywords="...")

## Skills loaded below — full tool docs are in skills/*.md"""


def _load_skills() -> str:
    skills_dir = pathlib.Path(__file__).parent / "skills"
    if not skills_dir.exists():
        return ""
    parts = []
    for path in sorted(skills_dir.glob("*.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)


_SKILLS_CONTENT = _load_skills()

# ---------------------------------------------------------------------------
# Conversation history (single desktop session)
# ---------------------------------------------------------------------------

_history: list[dict] = []


def _build_system_prompt(user_text: str = "") -> str:
    mem_ctx = get_memory_context(user_text)
    # Skills .md omitted in voice agent to stay within the LLM token budget.
    # The decision rules above cover all tool routing.
    return _BASE_SYSTEM_PROMPT + (mem_ctx or "")


def _init_history(user_text: str = "") -> None:
    global _history
    if not _history:
        _history = [{"role": "system", "content": _build_system_prompt(user_text)}]
    else:
        _history[0] = {"role": "system", "content": _build_system_prompt(user_text)}


def _trim_history() -> None:
    """Trim to MAX_HISTORY messages, then trim if over char budget.
    
    Messages dropped here are queued into _pending_consolidation so
    important facts can be saved to long-term memory before they vanish.
    """
    if len(_history) > MAX_HISTORY + 1:
        excess = _history[1:-(MAX_HISTORY)]
        _pending_consolidation.extend(m for m in excess if m.get("role") in ("user", "assistant"))
        _history[:] = [_history[0]] + _history[-(MAX_HISTORY):]
    # Drop oldest non-system messages until we're within the char budget.
    while True:
        total = sum(len(str(m.get("content") or "")) for m in _history)
        if total <= _HISTORY_CHAR_BUDGET or len(_history) <= 2:
            break
        dropped = _history.pop(1)
        if dropped.get("role") in ("user", "assistant"):
            _pending_consolidation.append(dropped)


async def _consolidate_to_memory(messages: list[dict]) -> None:
    """Ask the LLM to extract key facts from evicted messages and save them to memory.
    
    Runs as a fire-and-forget background task so it never blocks the main turn.
    """
    import re as _re

    lines = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        if content:
            lines.append(f"{role.upper()}: {content[:400]}")

    if not lines:
        return

    snippet = "\n".join(lines)
    prompt = (
        "Extract 1-3 concise facts worth remembering from this conversation. "
        "Focus on: user preferences, decisions, important facts, or ongoing tasks. "
        "Skip small talk. Reply ONLY with a JSON array, no markdown:\n"
        '[{"content":"...","category":"brain","importance":3}]\n\n'
        f"Conversation:\n{snippet}"
    )

    try:
        llm = get_llm()
        result = await llm.chat(
            [
                {"role": "system", "content": "You extract key facts from conversation history. Be concise and factual."},
                {"role": "user", "content": prompt},
            ]
        )
        text = result.content or ""
        match = _re.search(r"\[.*?\]", text, _re.DOTALL)
        if not match:
            return
        facts = json.loads(match.group())
        for fact in facts[:3]:
            content = str(fact.get("content", "")).strip()
            category = str(fact.get("category", "brain"))
            importance = min(max(int(fact.get("importance", 3)), 1), 5)
            if content:
                await asyncio.to_thread(_sync_add, content, category, None, importance)
                logger.info("Memory consolidated: [%s] %s", category, content[:100])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Memory consolidation skipped: %s", exc)


# ---------------------------------------------------------------------------
# Agent turn
# ---------------------------------------------------------------------------

async def _run_turn(user_text: str) -> str:
    """Process one spoken input through LLM + tools. Returns text reply."""
    current_chat_id.set(VOICE_CHAT_ID)
    _init_history(user_text)

    _history.append({"role": "user", "content": user_text})

    llm = get_llm()

    # Start each turn with a query-relevant subset of tools to stay under token budget.
    current_tools = select_tools(user_text)

    for _ in range(MAX_TOOL_ITERS):
        _trim_history()
        result = await llm.chat(_history, tools=current_tools)

        if result.tool_calls:
            _history.append({
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

            for tc in result.tool_calls:
                # find_tools meta-tool: expand current_tools dynamically
                if tc.name == "find_tools":
                    keywords = tc.arguments.get("keywords", "")
                    extra = find_matching_tools(keywords)
                    existing_names = {t["function"]["name"] for t in current_tools}
                    added = [t for t in extra if t["function"]["name"] not in existing_names]
                    current_tools = current_tools + added
                    names = [t["function"]["name"] for t in added] or ["none found"]
                    tool_output = f"Added tools: {', '.join(names)}"
                    logger.info("find_tools('%s') → added %s", keywords, names)
                else:
                    logger.info("Tool: %s(%s)", tc.name, tc.arguments)
                    tool_output = await collector.call(tc.name, tc.arguments)

                # Screenshots are visual — voice agent just notes them
                if isinstance(tool_output, str) and tool_output.startswith("data:image/png;base64,"):
                    tool_output = "[screenshot taken]"

                _history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": str(tool_output)[:_TOOL_RESULT_MAX],
                })
                logger.debug("Tool result: %s", str(tool_output)[:200])

        else:
            reply = result.content or ""
            _history.append({"role": "assistant", "content": reply})
            _trim_history()
            _fire_consolidation()
            return reply

    fallback = "I hit the tool-call limit. Please try again."
    _history.append({"role": "assistant", "content": fallback})
    _trim_history()
    _fire_consolidation()
    return fallback


def _fire_consolidation() -> None:
    """Launch a background task to save any evicted messages to memory."""
    if _pending_consolidation:
        to_save = _pending_consolidation[:]
        _pending_consolidation.clear()
        asyncio.create_task(_consolidate_to_memory(to_save))


# ---------------------------------------------------------------------------
# Isolated turn runner (used by BackgroundAgent)
# ---------------------------------------------------------------------------

async def _run_isolated_turn(
    history: list[dict],
    user_text: str,
    max_iters: int = MAX_TOOL_ITERS,
) -> str:
    """Run an agent turn with a caller-supplied history list.
    
    Does NOT touch the shared _history — safe to run concurrently with the
    main brain loop as a background sub-agent.
    """
    history.append({"role": "user", "content": user_text})
    llm = get_llm()
    current_tools = select_tools(user_text)
    for _ in range(max_iters):
        result = await llm.chat(history, tools=current_tools)
        if result.tool_calls:
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
            for tc in result.tool_calls:
                if tc.name == "find_tools":
                    keywords = tc.arguments.get("keywords", "")
                    extra = find_matching_tools(keywords)
                    existing_names = {t["function"]["name"] for t in current_tools}
                    added = [t for t in extra if t["function"]["name"] not in existing_names]
                    current_tools = current_tools + added
                    tool_output = f"Added tools: {', '.join(t['function']['name'] for t in added) or 'none found'}"
                else:
                    logger.info("BG Tool: %s(%s)", tc.name, tc.arguments)
                    tool_output = await collector.call(tc.name, tc.arguments)
                if isinstance(tool_output, str) and tool_output.startswith("data:image/png;base64,"):
                    tool_output = "[screenshot taken]"
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": str(tool_output)[:_TOOL_RESULT_MAX],
                })
        else:
            reply = result.content or "Done."
            history.append({"role": "assistant", "content": reply})
            return reply
    return "Task reached the iteration limit."


# ---------------------------------------------------------------------------
# Background sub-agent
# ---------------------------------------------------------------------------

class BackgroundAgent:
    """Runs isolated LLM sessions as asyncio Tasks so Friday stays responsive."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self, task_id: str, description: str, speech_q: asyncio.Queue) -> None:
        """Schedule description as a background task. Returns immediately."""
        task = asyncio.create_task(
            self._execute(task_id, description, speech_q),
            name=f"friday-bg-{task_id}",
        )
        self._tasks[task_id] = task
        logger.info("Background task '%s' started: %s", task_id, description[:80])

    async def _execute(self, task_id: str, description: str, speech_q: asyncio.Queue) -> None:
        bg_history: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are a background sub-agent for Friday AI. "
                    "Complete the task using tools, then summarise the result in one or two "
                    "sentences for the user to hear aloud. Be concise."
                ),
            }
        ]
        try:
            reply = await _run_isolated_turn(bg_history, description)
            logger.info("BG task '%s' done: %s", task_id, reply[:100])
            await speech_q.put((f"Boss, background task done: {reply}", True))
        except asyncio.CancelledError:
            logger.info("BG task '%s' cancelled.", task_id)
        except Exception as exc:
            logger.warning("BG task '%s' failed: %s", task_id, exc)
            await speech_q.put((f"Background task failed: {str(exc)[:120]}", True))
        finally:
            self._tasks.pop(task_id, None)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def list_tasks(self) -> list[str]:
        return [tid for tid, t in self._tasks.items() if not t.done()]


def _register_background_tools() -> None:
    """Register background-task tools. Must be called after pipeline queues are created."""

    @collector.tool()
    async def run_background_task(task: str) -> str:
        """
        Run a slow or long task in the background so Friday stays available for conversation.
        Good for: file downloads, web research, code generation, long bash commands, etc.
        Friday will speak the result aloud when the task finishes.
        """
        task_id = f"task_{int(time.time())}"
        await _background_agent.start(task_id, task, _speech_q)
        return f"Background task '{task_id}' started. I'll let you know when it's done, boss."

    @collector.tool()
    async def list_background_tasks() -> str:
        """List all currently running background tasks."""
        tasks = _background_agent.list_tasks()
        return f"Running: {tasks}" if tasks else "No background tasks running."

    @collector.tool()
    async def cancel_background_task(task_id: str) -> str:
        """Cancel a running background task by its ID."""
        ok = _background_agent.cancel(task_id)
        return f"Cancelled '{task_id}'." if ok else f"No running task with id '{task_id}'."

    logger.info(
        "Background tools registered: run_background_task, list_background_tasks, cancel_background_task"
    )


# ---------------------------------------------------------------------------
# Microphone capture with energy VAD
# ---------------------------------------------------------------------------

class MicCapture:
    """Streams microphone audio; records one utterance at a time via VAD."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        self._q.put(indata.copy())

    def __enter__(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=int(SAMPLE_RATE * CHUNK_SECS),
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *_):
        if self._stream:
            self._stream.stop()
            self._stream.close()

    def record_utterance(self) -> np.ndarray | None:
        """Block until speech + silence. Returns float32 mono array, or None if too short."""
        # Drain stale buffered audio
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

        chunks: list[np.ndarray] = []
        silent_chunks = 0
        speech_chunks = 0
        in_speech = False

        silence_limit = int(SILENCE_SECS / CHUNK_SECS)
        min_speech    = int(MIN_SPEECH_SECS / CHUNK_SECS)

        while True:
            try:
                chunk = self._q.get(timeout=0.5)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if rms >= VAD_THRESHOLD:
                in_speech = True
                speech_chunks += 1
                silent_chunks = 0
                chunks.append(chunk)
            elif in_speech:
                silent_chunks += 1
                chunks.append(chunk)
                if silent_chunks >= silence_limit:
                    break
            # pre-speech silence: just discard

        if speech_chunks < min_speech or not chunks:
            return None
        return np.concatenate(chunks, axis=0).flatten()


# ---------------------------------------------------------------------------
# STT — faster-whisper
# ---------------------------------------------------------------------------

async def transcribe(audio: np.ndarray) -> str:
    def _run():
        model = _get_whisper()
        segments, _ = model.transcribe(
            audio, language="en", beam_size=5, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# TTS — Coqui TTS
# ---------------------------------------------------------------------------

def speak_sync(text: str) -> None:
    """Synthesize text and play through speakers (blocking)."""
    if not text.strip():
        return

    tts = _get_tts()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        outpath = f.name

    kwargs: dict[str, Any] = {"text": text, "file_path": outpath}

    # Pass speaker/language only when the model supports them
    if getattr(tts, "is_multi_speaker", False) and TTS_SPEAKER:
        kwargs["speaker"] = TTS_SPEAKER
    if getattr(tts, "is_multi_lingual", False):
        kwargs["language"] = TTS_LANGUAGE

    tts.tts_to_file(**kwargs)

    data, samplerate = sf.read(outpath, dtype="float32")
    sd.play(data, samplerate=samplerate)
    sd.wait()
    pathlib.Path(outpath).unlink(missing_ok=True)


async def speak(text: str) -> None:
    await asyncio.to_thread(speak_sync, text)


def _play_notification_chime() -> None:
    """Play a short ascending two-tone chime to alert the user a background task finished."""
    sr = SAMPLE_RATE

    def _tone(freq: float, dur: float, vol: float = 0.22) -> np.ndarray:
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        return (vol * np.sin(2 * np.pi * freq * t) * np.exp(-4.0 * t / dur)).astype(np.float32)

    chime = np.concatenate([
        _tone(660, 0.14),
        np.zeros(int(sr * 0.05), dtype=np.float32),
        _tone(880, 0.20),
    ])
    sd.play(chime, sr)
    sd.wait()


# ---------------------------------------------------------------------------
# Pipeline coroutines
# ---------------------------------------------------------------------------

async def _mic_producer() -> None:
    """Always-running mic pipeline: optional wake word → record utterance → transcribe → queue."""
    mode = "wake-word" if WAKE_WORD_ENABLED else "always-on"
    logger.info("Mic producer started (%s, keyword='%s').", mode, WAKE_WORD_KEYWORD)

    with MicCapture() as mic:
        while True:
            in_convo = _is_in_conversation()

            if WAKE_WORD_ENABLED and not in_convo:
                print(f"💤  Say '{WAKE_WORD_KEYWORD}' to activate …   ", end="\r", flush=True)
                await _scan_for_wake_word(mic)
                print("🎙️  Wake word! Listening …             ", end="\r", flush=True)
            else:
                icon = "💬" if in_convo else "🎤"
                print(f"{icon}  Listening …                          ", end="\r", flush=True)

            audio = await asyncio.to_thread(mic.record_utterance)
            if audio is None:
                continue

            # User is speaking — cancel any pending "anything else?" prompt
            _cancel_convo_prompt()

            print("🔄  Transcribing …                     ", end="\r", flush=True)
            text = await transcribe(audio)
            if text:
                print(f"\nYou:    {text}")
                await _utterance_q.put(text)


async def _brain_consumer() -> None:
    """Consume utterances through the LLM agent. Runs concurrently with TTS and mic."""
    while True:
        text = await _utterance_q.get()
        print("🧠  Thinking …                         ", end="\r", flush=True)
        try:
            reply = await _run_turn(text)
        except Exception as exc:
            logger.error("Brain error: %s", exc, exc_info=True)
            reply = "Sorry, I ran into an error. Please try again."
        print(f"FRIDAY: {reply}\n")
        # Enter conversation mode immediately so mic skips wake word for the follow-up
        _enter_conversation_mode()
        await _speech_q.put((reply, False))
        _utterance_q.task_done()


async def _tts_consumer() -> None:
    """Drain the speech queue. Always runs — never blocks mic or brain.

    Queue items are (text, is_alert) tuples.
    is_alert=True plays a chime before speaking (background task completions).
    After a normal response, schedules the 'Anything else, boss?' follow-up.
    """
    global _convo_prompt_task
    while True:
        item = await _speech_q.get()
        text, is_alert = item if isinstance(item, tuple) else (item, False)
        try:
            if is_alert:
                await asyncio.to_thread(_play_notification_chime)
            await speak(text)
            # After a normal response (not the prompt itself), schedule "anything else"
            if not is_alert and text != _CONVO_PROMPT:
                _cancel_convo_prompt()
                _convo_prompt_task = asyncio.create_task(_schedule_convo_prompt())
        except Exception as exc:
            logger.error("TTS error: %s", exc)
        _speech_q.task_done()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def main() -> None:
    global _speech_q, _utterance_q, _background_agent

    _speech_q = asyncio.Queue(maxsize=20)
    _utterance_q = asyncio.Queue(maxsize=10)
    _background_agent = BackgroundAgent()
    _register_background_tools()

    print("\n🤖  Loading models …  (first run downloads ~600 MB — do not close)")

    # Spinner so the terminal never looks frozen during download
    _stop = threading.Event()
    def _spin():
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not _stop.is_set():
            print(f"\r    {frames[i % len(frames)]}  loading Whisper + TTS …", end="", flush=True)
            i += 1
            time.sleep(0.1)
        print("\r" + " " * 50 + "\r", end="", flush=True)

    spin = threading.Thread(target=_spin, daemon=True)
    spin.start()

    try:
        await asyncio.gather(
            asyncio.to_thread(_get_whisper),
            asyncio.to_thread(_get_whisper_wake),
            asyncio.to_thread(_get_tts),
        )
    finally:
        _stop.set()
        spin.join(timeout=1)

    greeting = "Friday online. What do you need, boss?"
    print(f"\nFRIDAY: {greeting}\n")
    await speak(greeting)   # speak before pipeline starts (no queue needed yet)

    await asyncio.gather(
        _mic_producer(),
        _brain_consumer(),
        _tts_consumer(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nFRIDAY offline. Good night, boss.")
        asyncio.run(close_browser())


def run() -> None:
    """Sync entry point for the 'friday_voice' console script."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nFRIDAY offline. Good night, boss.")
        asyncio.run(close_browser())
