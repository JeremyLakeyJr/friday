"""
Friday All-in-One — Telegram + Voice agent in a single process.

Runs both the Telegram bot and the voice pipeline concurrently on the same
asyncio event loop.  Either interface can be disabled gracefully:

  • Telegram  → omit / blank TELEGRAM_TOKEN in .env
  • Voice     → run on a machine without a microphone / sound device

Run:
  uv run friday_all

Environment:
  TELEGRAM_TOKEN   — required for Telegram; skip to run voice-only
  LLM_PROVIDER     — copilot | openai | gemini | ollama (default: copilot)
  WAKE_WORD_ENABLED — 1 (default) or 0
  WAKE_WORD_KEYWORD — "friday" (default)
"""

import asyncio
import fcntl
import logging
import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv()

from friday.config import config

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("friday-all")

# ---------------------------------------------------------------------------
# Single-instance PID lock — prevents two Friday processes conflicting over
# the Telegram bot token (which causes recurring 409 getUpdates errors).
# ---------------------------------------------------------------------------

_PID_FILE = pathlib.Path(os.getenv("XDG_RUNTIME_DIR", "/tmp")) / "friday_all.pid"
_pid_lock_fh = None  # keep file handle open so the lock is held for the lifetime


def _acquire_pid_lock() -> bool:
    """Try to acquire an exclusive lock on the PID file. Returns True on success."""
    global _pid_lock_fh
    try:
        _pid_lock_fh = open(_PID_FILE, "w")
        fcntl.flock(_pid_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _pid_lock_fh.write(str(os.getpid()))
        _pid_lock_fh.flush()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Telegram coroutine (async, uses PTB v20+ native async polling)
# ---------------------------------------------------------------------------

async def run_telegram() -> None:
    """Start the Telegram bot using PTB's async polling API."""
    token = config.TELEGRAM_TOKEN
    if not token:
        logger.info("TELEGRAM_TOKEN not set — Telegram interface disabled.")
        return

    # Import heavy telegram deps inside the coroutine so that a missing
    # TELEGRAM_TOKEN doesn't cause import errors on voice-only machines.
    from telegram.error import Conflict, NetworkError, TimedOut
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    import agent as ag

    # Suppress the updater's own ERROR-level log for Conflict — it's already
    # handled by _error_handler below and is non-fatal noise.
    import logging as _logging

    class _SuppressConflict(_logging.Filter):
        def filter(self, record: _logging.LogRecord) -> bool:  # type: ignore[override]
            return "Conflict" not in record.getMessage()

    for _name in ("telegram.ext.Updater", "telegram.ext._utils.networkloop"):
        _logging.getLogger(_name).addFilter(_SuppressConflict())

    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, (TimedOut, NetworkError, Conflict)):
            logger.debug("Transient Telegram error (ignored): %s", err)
            return
        logger.error("Unhandled Telegram exception", exc_info=err)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", ag.cmd_start))
    app.add_handler(CommandHandler("reset", ag.cmd_reset))
    app.add_handler(CommandHandler("tools", ag.cmd_tools))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ag.handle_message))
    app.add_handler(MessageHandler(filters.VOICE, ag.handle_voice_message))
    app.add_error_handler(_error_handler)

    logger.info("Telegram bot starting…")
    async with app:
        await app.start()
        # Clear any leftover webhook so long-polling doesn't race with a prior instance
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception as exc:
            logger.debug("delete_webhook: %s", exc)
        await app.updater.start_polling(drop_pending_updates=True)
        # Yield control — voice pipeline runs concurrently alongside this.
        # The task is cancelled by asyncio.gather when the voice pipeline exits.
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


# ---------------------------------------------------------------------------
# Voice coroutine (delegates to voice_agent.main)
# ---------------------------------------------------------------------------

async def run_voice() -> None:
    """Start the voice pipeline.  Skips gracefully if audio is unavailable."""
    try:
        import sounddevice  # noqa: F401 — check availability before heavy imports
    except (ImportError, OSError) as exc:
        logger.info("Voice interface disabled (sounddevice unavailable: %s)", exc)
        return

    try:
        import voice_agent
        await voice_agent.main()
    except Exception as exc:
        logger.exception("Voice pipeline exited with error: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run_all() -> None:
    telegram_token = config.TELEGRAM_TOKEN
    has_voice = True
    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError):
        has_voice = False

    if not telegram_token and not has_voice:
        logger.error(
            "Neither TELEGRAM_TOKEN nor audio device available. Nothing to run."
        )
        sys.exit(1)

    if not _acquire_pid_lock():
        logger.error(
            "Another Friday instance is already running (PID file locked: %s). "
            "Stop it first with: kill $(cat %s)",
            _PID_FILE, _PID_FILE,
        )
        sys.exit(1)

    tasks = []
    if telegram_token:
        tasks.append(asyncio.create_task(run_telegram(), name="telegram"))
    if has_voice:
        tasks.append(asyncio.create_task(run_voice(), name="voice"))

    logger.info(
        "Friday starting — interfaces: %s",
        [t.get_name() for t in tasks],
    )

    # Run until the first task finishes (normally the voice pipeline, since
    # it exits on KeyboardInterrupt or EOF).  Cancel remaining tasks cleanly.
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    for task in done:
        if task.exception():
            raise task.exception()


def run() -> None:
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        logger.info("Friday shutting down.")


if __name__ == "__main__":
    run()
