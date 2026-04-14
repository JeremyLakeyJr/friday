"""
LLM factory — builds an async chat client based on LLM_PROVIDER env var.

Supported providers:
  gemini   — Google Gemini via google-generativeai (GOOGLE_API_KEY)
  openai   — OpenAI chat completions (OPENAI_API_KEY)
  copilot  — GitHub Copilot via GitHub Models API (GH_TOKEN)
  ollama   — Self-hosted Ollama (OLLAMA_URL, OLLAMA_MODEL, no API key)

All providers expose a single coroutine:
  chat(messages: list[dict], tools: list[dict] | None) -> ChatResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from friday.config import config

logger = logging.getLogger("friday.llm")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OpenAI-compatible helper (used by openai + copilot providers)
# ---------------------------------------------------------------------------

async def _openai_chat(
    client,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
) -> ChatResult:
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await client.chat.completions.create(**kwargs)
    msg = response.choices[0].message

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    return ChatResult(content=msg.content or "", tool_calls=tool_calls)


# ---------------------------------------------------------------------------
# Provider classes
# ---------------------------------------------------------------------------

class GeminiLLM:
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=config.GOOGLE_API_KEY)
        self._model_name = config.LLM_MODEL or "gemini-2.5-flash"
        self._genai = genai

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        import asyncio
        import google.generativeai as genai
        from google.generativeai import protos

        # Separate system prompt from conversation history
        system_text = ""
        gemini_history = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""

            if role == "system":
                system_text = content

            elif role == "user":
                gemini_history.append({"role": "user", "parts": [content]})

            elif role == "assistant":
                # May contain text and/or tool_calls
                parts = []
                if content:
                    parts.append(content)
                for tc in m.get("tool_calls") or []:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"])
                    except Exception:
                        args = {}
                    parts.append(protos.Part(
                        function_call=protos.FunctionCall(name=fn["name"], args=args)
                    ))
                if parts:
                    gemini_history.append({"role": "model", "parts": parts})

            elif role == "tool":
                # Tool response — emit as a user-role function_response turn
                gemini_history.append({
                    "role": "user",
                    "parts": [protos.Part(
                        function_response=protos.FunctionResponse(
                            name=m.get("name") or m.get("tool_call_id", "tool"),
                            response={"result": content},
                        )
                    )],
                })

        # Build tool declarations
        gemini_tools = None
        if tools:
            from google.generativeai.types import FunctionDeclaration, Tool as GeminiTool
            declarations = []
            for t in tools:
                fn = t.get("function", {})
                declarations.append(FunctionDeclaration(
                    name=fn.get("name", ""),
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                ))
            gemini_tools = [GeminiTool(function_declarations=declarations)]

        # Rebuild model with system instruction (stateless per call)
        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=system_text or None,
        )

        if gemini_history:
            chat = model.start_chat(history=gemini_history[:-1])
            last_parts = gemini_history[-1]["parts"]
        else:
            chat = model.start_chat(history=[])
            last_parts = ["Hello"]

        send_kwargs: dict[str, Any] = {"message": last_parts}
        if gemini_tools:
            send_kwargs["tools"] = gemini_tools

        response = await asyncio.to_thread(chat.send_message, **send_kwargs)

        tool_calls = []
        text = ""
        for part in response.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=f"{fc.name}-{id(fc)}",
                    name=fc.name,
                    arguments=dict(fc.args),
                ))
            elif hasattr(part, "text") and part.text:
                text += part.text

        return ChatResult(content=text, tool_calls=tool_calls)


class OpenAILLM:
    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self._model = config.LLM_MODEL or "gpt-4o"

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        return await _openai_chat(self._client, self._model, messages, tools)


class CopilotLLM:
    """GitHub Copilot via the GitHub Models API (Azure OpenAI-compatible endpoint)."""

    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=config.GH_TOKEN,
        )
        self._model = config.LLM_MODEL or config.COPILOT_MODEL

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        return await _openai_chat(self._client, self._model, messages, tools)


class OllamaLLM:
    """Self-hosted Ollama — no API key required."""

    def __init__(self):
        import ollama as _ollama
        self._client = _ollama.AsyncClient(host=config.OLLAMA_URL)
        self._model = config.LLM_MODEL or config.OLLAMA_MODEL

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat(**kwargs)
        msg = response.message

        tool_calls = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for i, tc in enumerate(msg.tool_calls):
                tool_calls.append(ToolCall(
                    id=f"{tc.function.name}-{i}",
                    name=tc.function.name,
                    arguments=tc.function.arguments or {},
                ))

        return ChatResult(content=msg.content or "", tool_calls=tool_calls)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_llm():
    provider = config.LLM_PROVIDER.lower()
    logger.info("LLM provider: %s", provider)
    if provider == "gemini":
        return GeminiLLM()
    elif provider == "openai":
        return OpenAILLM()
    elif provider == "copilot":
        return CopilotLLM()
    elif provider == "ollama":
        return OllamaLLM()
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Choose: gemini, openai, copilot, ollama")


_llm_singleton = None


def get_llm():
    """Return a cached LLM instance (created once on first call)."""
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = build_llm()
    return _llm_singleton
