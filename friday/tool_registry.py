"""
Dynamic tool registry — SQLite-backed tool selection.

Tools are stored once at startup.  For each LLM request, only the most
relevant tools are sent (based on keyword overlap with the user's query),
plus a small set of always-on core tools.

This keeps every request well under the 8k-token cap even with 50+ tools
registered.
"""

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent / "memory" / "tools.db"
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

# These tools are always included regardless of query — they are the "hands"
# that almost every request needs.
ALWAYS_ON_TOOLS: frozenset[str] = frozenset({
    "run_bash",
    "search_web",
    "read_file",
    "write_file",
    "add_memory",
    "search_memory",
    "get_current_time",
    "find_tools",       # meta-tool: lets the LLM discover more tools
})

# Synonym / category mapping — expands query tokens so the scorer finds the
# right tools even when the user uses different words.
_SYNONYMS: dict[str, list[str]] = {
    "open":        ["navigate", "launch", "browser"],
    "browse":      ["navigate", "browser", "firefox", "url"],
    "website":     ["navigate", "browser", "url", "fetch"],
    "internet":    ["search", "web", "url", "fetch"],
    "file":        ["read", "write", "directory", "list", "move", "copy"],
    "folder":      ["directory", "list", "move"],
    "process":     ["kill", "list", "processes", "pid"],
    "app":         ["launch", "open", "application", "process"],
    "screenshot":  ["screen", "capture", "desktop", "image"],
    "clipboard":   ["copy", "paste", "clip"],
    "memory":      ["remember", "brain", "add", "search", "forget"],
    "smart":       ["home", "homeassistant", "light", "switch"],
    "home":        ["homeassistant", "light", "switch", "ha"],
    "news":        ["world", "rss", "headlines"],
    "download":    ["bash", "curl", "wget", "fetch"],
    "install":     ["bash", "pip", "apt", "brew"],
    "notification": ["notify", "desktop", "alert"],
    "disk":        ["storage", "space", "usage"],
    "ram":         ["memory", "usage", "free"],
    "system":      ["info", "disk", "ram", "memory", "process"],
    "firefox":     ["firefox", "navigate", "browser", "url"],
    "chrome":      ["browser", "navigate", "chromium"],
    "auto":        ["auto_browser", "session", "managed", "vnc", "docker"],
    "session":     ["auto_browser", "create", "browser", "managed"],
    "vnc":         ["auto_browser", "session", "takeover", "dashboard"],
    "managed":     ["auto_browser", "session", "browser"],
    "profile":     ["auto_browser", "auth", "session", "cookies"],
    "login":       ["auto_browser", "auth", "session", "cookies"],
}


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_registry (
                name        TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                keywords    TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                always_on   INTEGER NOT NULL DEFAULT 0
            )
        """)
        _conn.commit()
    return _conn


def _tokenize(text: str) -> set[str]:
    """Lower-case word tokens, ≥3 chars."""
    return {t for t in re.findall(r"[a-z][a-z0-9]*", text.lower()) if len(t) >= 3}


def _expand(tokens: set[str]) -> set[str]:
    """Add synonym/category expansions to a token set."""
    extra: set[str] = set()
    for t in tokens:
        for synonyms in _SYNONYMS.get(t, []):
            extra.update(_tokenize(synonyms))
    return tokens | extra


def register_tool(schema: dict) -> None:
    """Upsert a tool schema into the registry.  Called once at agent startup."""
    name: str = schema["function"]["name"]
    description: str = schema["function"]["description"]
    kw_tokens = _tokenize(name.replace("_", " ") + " " + description)
    keywords = " ".join(sorted(kw_tokens))
    always_on = 1 if name in ALWAYS_ON_TOOLS else 0
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO tool_registry VALUES (?, ?, ?, ?, ?)",
            (name, description, keywords, json.dumps(schema), always_on),
        )
        conn.commit()


def select_tools(query: str, top_k: int = 10) -> list[dict]:
    """
    Return tool schemas for the LLM request.

    Always includes ALWAYS_ON_TOOLS.  Then ranks remaining tools by how many
    expanded query tokens they match, returning the top_k best matches on top
    of the always-on set.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT name, keywords, schema_json, always_on FROM tool_registry"
    ).fetchall()

    query_tokens = _expand(_tokenize(query))

    always: list[dict] = []
    scored: list[tuple[int, dict]] = []

    for name, keywords, schema_json, always_on in rows:
        schema = json.loads(schema_json)
        if always_on:
            always.append(schema)
            continue
        tool_tokens = set(keywords.split())
        score = len(query_tokens & tool_tokens)
        if score > 0:
            scored.append((score, name, schema))

    scored.sort(key=lambda x: -x[0])
    limit = max(0, top_k - len(always))
    selected = always + [s for _, _, s in scored[:limit]]
    return selected


def find_matching_tools(keywords: str, top_k: int = 6) -> list[dict]:
    """
    Find tools by capability keywords.

    Called by the `find_tools` meta-tool so the LLM can discover tools that
    weren't included in the initial selection.  Returns full schemas.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT name, keywords, schema_json FROM tool_registry"
    ).fetchall()

    query_tokens = _expand(_tokenize(keywords))
    scored: list[tuple[int, dict]] = []
    for name, kw, schema_json in rows:
        tool_tokens = set(kw.split())
        score = len(query_tokens & tool_tokens)
        if score > 0:
            scored.append((score, json.loads(schema_json)))

    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:top_k]]


def all_tool_names() -> list[str]:
    conn = _get_conn()
    return [r[0] for r in conn.execute(
        "SELECT name FROM tool_registry ORDER BY name"
    ).fetchall()]


def total_tools() -> int:
    return len(_get_conn().execute("SELECT 1 FROM tool_registry").fetchall())
