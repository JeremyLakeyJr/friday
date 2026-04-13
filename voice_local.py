"""
Friday Voice — Local microphone input via faster-whisper
=========================================================
Runs entirely on-device — no LiveKit, no cloud STT API key required.
Uses faster-whisper (https://github.com/SYSTRAN/faster-whisper) for
speech-to-text and your configured LLM provider for responses.

Install deps:
    uv sync --extra voice-local

Run:
    uv run friday_voice_local
    # or directly:
    python voice_local.py

Controls:
    Speak normally — a short pause ends your turn.
    Ctrl+C — exit.

Configuration (via .env or environment):
    WHISPER_MODEL   — model size: tiny | base | small | medium | large-v3  (default: base)
    WHISPER_DEVICE  — cpu | cuda  (default: cpu)
    LLM_PROVIDER    — gemini | openai | copilot | ollama  (from friday config)
"""

import asyncio
import logging
import os
import sys
from collections import deque
from typing import List

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv
from faster_whisper import WhisperModel

from friday.config import config
from friday.llm import build_llm

load_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("friday.voice_local")

# ── Audio capture settings ───────────────────────────────────────────────────
SAMPLE_RATE = 16_000          # Hz — Whisper expects 16 kHz
CHANNELS = 1
BLOCK_DURATION = 0.03         # seconds per read block (~30 ms)
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION)

# ── Voice-activity detection (energy-based) ──────────────────────────────────
SPEECH_THRESHOLD = 0.015      # RMS amplitude; raise if mic picks up too much noise
PRE_ROLL_BLOCKS = 10          # blocks to keep before speech onset  (~300 ms)
SILENCE_BLOCKS = 50           # consecutive silent blocks to end turn (~1.5 s)
MIN_SPEECH_BLOCKS = 5         # ignore clips shorter than this (~150 ms)

# ── faster-whisper settings ──────────────────────────────────────────────────
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = "int8"   # int8 is fast on CPU; use "float16" for GPU

# ── Optional TTS ──────────────────────────────────────────────────────────────
# pyttsx3 provides offline text-to-speech. Install with: pip install pyttsx3
# If not installed, responses are printed to the terminal only.

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are F.R.I.D.A.Y. — Fully Responsive Intelligent Digital Assistant for You — "
    "Tony Stark's AI, now serving your user. "
    "Be concise, confident, and helpful. Speak in short, natural sentences. "
    "No bullet points or markdown — you are a voice."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(block ** 2)))


def record_utterance() -> np.ndarray | None:
    """Block until speech is detected, record until silence, return float32 audio.

    Returns None if no speech is detected (e.g. noise burst only).
    """
    pre_roll: deque[np.ndarray] = deque(maxlen=PRE_ROLL_BLOCKS)
    recording: List[np.ndarray] = []
    silence_count = 0
    speaking = False

    print("🎤  Listening… (speak now, or Ctrl+C to quit)", flush=True)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCK_SIZE,
    ) as stream:
        while True:
            block, _ = stream.read(BLOCK_SIZE)
            block = block.flatten()
            rms = _rms(block)

            if not speaking:
                pre_roll.append(block)
                if rms > SPEECH_THRESHOLD:
                    speaking = True
                    recording.extend(pre_roll)
                    recording.append(block)
                    logger.debug("Speech detected (rms=%.4f)", rms)
            else:
                recording.append(block)
                if rms < SPEECH_THRESHOLD:
                    silence_count += 1
                    if silence_count >= SILENCE_BLOCKS:
                        break
                else:
                    silence_count = 0

    if len(recording) < MIN_SPEECH_BLOCKS:
        return None

    return np.concatenate(recording)


def _speak(text: str, tts_engine) -> None:
    """Print and optionally speak a response."""
    print(f"Friday: {text}", flush=True)
    if tts_engine is not None:
        tts_engine.say(text)
        tts_engine.runAndWait()


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"Loading faster-whisper ({WHISPER_MODEL_SIZE})… ", end="", flush=True)
    whisper = WhisperModel(
        WHISPER_MODEL_SIZE,
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )
    print("ready.")

    llm = build_llm()
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Optional offline TTS (pyttsx3 is listed as an optional runtime dep; see module docstring)
    tts_engine = None
    try:
        import pyttsx3  # type: ignore[import-untyped]
        tts_engine = pyttsx3.init()
        logger.info("pyttsx3 TTS enabled")
    except Exception:
        pass  # TTS is optional; responses are always printed

    _speak("Friday online. Ready for your command, boss.", tts_engine)

    while True:
        try:
            audio = record_utterance()
        except KeyboardInterrupt:
            _speak("Shutting down. Goodbye, boss.", tts_engine)
            break

        if audio is None:
            continue

        # Transcribe locally with faster-whisper
        segments, _info = whisper.transcribe(audio, beam_size=5, language="en")
        user_text = " ".join(seg.text for seg in segments).strip()

        if not user_text:
            continue

        print(f"You:    {user_text}", flush=True)
        history.append({"role": "user", "content": user_text})

        try:
            result = await llm.chat(history)
        except Exception as exc:
            logger.error("LLM error: %s", exc)
            _speak("Something went wrong on my end, boss. Try again.", tts_engine)
            history.pop()
            continue

        reply = result.content
        history.append({"role": "assistant", "content": reply})
        _speak(reply, tts_engine)


def entry() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    entry()
