"""
Configuration — load environment variables and app-wide settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Server identity
    SERVER_NAME: str = os.getenv("SERVER_NAME", "Friday")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # LLM provider: "gemini" | "openai" | "copilot" | "ollama"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")  # override default model for provider

    # LLM API keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

    # GitHub Copilot LLM (uses GitHub Models API, no extra cost beyond Copilot subscription)
    GH_TOKEN: str = os.getenv("GH_TOKEN", "")
    COPILOT_MODEL: str = os.getenv("COPILOT_MODEL", "gpt-4o")

    # Ollama (self-hosted, no API key)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")

    # Telegram bot
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    ALLOWED_USER_IDS: str = os.getenv("ALLOWED_USER_IDS", "")

    # Home Assistant
    HA_URL: str = os.getenv("HA_URL", "http://homeassistant.local:8123")
    HA_TOKEN: str = os.getenv("HA_TOKEN", "")


config = Config()
