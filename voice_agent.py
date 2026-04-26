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
from friday.tools import bash, browser, memory as memory_tools, system, utils, web
from friday.tools import homeassistant as ha_tools
from friday.tools.browser import close_browser, current_chat_id
from friday.tools.memory import get_memory_context

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
MAX_TOOL_ITERS   = 10
MAX_HISTORY      = 40   # keep last N messages before trimming

# ---------------------------------------------------------------------------
# Lazy model handles
# ---------------------------------------------------------------------------

_whisper = None
_tts = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper '%s' on %s …", WHISPER_MODEL_ID, WHISPER_DEVICE)
        _whisper = WhisperModel(WHISPER_MODEL_ID, device=WHISPER_DEVICE, compute_type="int8")
        logger.info("Whisper ready.")
    return _whisper


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
# Tool collector (same pattern as agent.py)
# ---------------------------------------------------------------------------

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
                    "description": (fn.__doc__ or "").strip(),
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
memory_tools.register(collector)
ha_tools.register(collector)

TOOL_SCHEMAS = collector._schemas
logger.info("Registered %d tools: %s", len(TOOL_SCHEMAS), [s["function"]["name"] for s in TOOL_SCHEMAS])

# ---------------------------------------------------------------------------
# System prompt + skills
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """You are Friday (F.R.I.D.A.Y.) — an autonomous AI assistant running on the user's desktop.
Be concise, direct, and action-oriented. When asked to do something, DO it with tools — don't just explain how.
Chain multiple tool calls in one turn for complex tasks. Report errors clearly.
You are speaking aloud — keep responses short and natural, no markdown formatting, no bullet lists.

## Decision rules
- Run code / install / check system? → run_bash
- Browse a website visually? → browser_navigate → browser_screenshot
- Find info online? → search_web first, then browser_navigate or fetch_url
- Read/write files on disk? → read_file / write_file
- User shares personal info (name, prefs, projects)? → add_memory immediately (don't ask)
- Control smart home? → ha_call_service or ha_get_state

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
    return _BASE_SYSTEM_PROMPT + "\n\n" + _SKILLS_CONTENT + (mem_ctx or "")


def _init_history(user_text: str = "") -> None:
    global _history
    if not _history:
        _history = [{"role": "system", "content": _build_system_prompt(user_text)}]
    else:
        _history[0] = {"role": "system", "content": _build_system_prompt(user_text)}


def _trim_history() -> None:
    if len(_history) > MAX_HISTORY + 1:
        _history[:] = [_history[0]] + _history[-(MAX_HISTORY):]


# ---------------------------------------------------------------------------
# Agent turn
# ---------------------------------------------------------------------------

async def _run_turn(user_text: str) -> str:
    """Process one spoken input through LLM + tools. Returns text reply."""
    current_chat_id.set(VOICE_CHAT_ID)
    _init_history(user_text)

    _history.append({"role": "user", "content": user_text})

    llm = get_llm()

    for _ in range(MAX_TOOL_ITERS):
        result = await llm.chat(_history, tools=TOOL_SCHEMAS)

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
                logger.info("Tool: %s(%s)", tc.name, tc.arguments)
                tool_output = await collector.call(tc.name, tc.arguments)

                # Screenshots are visual — voice agent just notes them
                if isinstance(tool_output, str) and tool_output.startswith("data:image/png;base64,"):
                    tool_output = "[screenshot taken]"

                _history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": str(tool_output),
                })
                logger.debug("Tool result: %s", str(tool_output)[:200])

        else:
            reply = result.content or ""
            _history.append({"role": "assistant", "content": reply})
            _trim_history()
            return reply

    fallback = "I hit the tool-call limit. Please try again."
    _history.append({"role": "assistant", "content": fallback})
    _trim_history()
    return fallback


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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def main() -> None:
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
            asyncio.to_thread(_get_tts),
        )
    finally:
        _stop.set()
        spin.join(timeout=1)

    greeting = "Friday online. What do you need, boss?"
    print(f"\nFRIDAY: {greeting}\n")
    await speak(greeting)

    with MicCapture() as mic:
        while True:
            print("🎤  Listening …", end="\r", flush=True)
            audio = mic.record_utterance()

            if audio is None:
                continue

            print("🔄  Transcribing …", end="\r", flush=True)
            text = await transcribe(audio)

            if not text:
                continue

            print(f"\nYou:    {text}")
            print("🧠  Thinking …", end="\r", flush=True)

            reply = await _run_turn(text)

            print(f"FRIDAY: {reply}\n")
            await speak(reply)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nFRIDAY offline. Good night, boss.")
        asyncio.run(close_browser())
