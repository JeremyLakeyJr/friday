"""
Memory tools — read/write the AI brain and user profile markdown files.

Memory files are stored in the `memory/` directory next to agent.py.
- brain.md        : Friday's general knowledge and learned facts
- user_profile.md : Persistent profile of the user, updated over time
"""

import datetime
from pathlib import Path

# Resolve memory directory relative to this file (friday/tools/memory.py → memory/)
MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"


_ALLOWED_FILES = {"brain", "user_profile"}


def _safe_filename(filename: str) -> str:
    """
    Return just the base name (no directory components) with .md stripped.
    Validates against the allowed set to prevent path traversal.
    """
    # Use Path.name to strip any directory components, including absolute paths
    name = Path(filename).name
    # Remove .md extension if present
    if name.endswith(".md"):
        name = name[:-3]
    return name


def _memory_path(filename: str) -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(filename)
    return MEMORY_DIR / f"{name}.md"


def register(mcp):

    @mcp.tool()
    def read_memory(filename: str) -> str:
        """Read an AI memory file. Use 'brain' for general knowledge or 'user_profile' for the user's profile."""
        name = _safe_filename(filename)
        if name not in _ALLOWED_FILES:
            return f"Invalid memory file '{filename}'. Allowed: {', '.join(sorted(_ALLOWED_FILES))}."
        path = _memory_path(name)
        if not path.exists():
            return f"Memory file '{filename}' not found."
        return path.read_text(encoding="utf-8")

    @mcp.tool()
    def write_memory(filename: str, content: str) -> str:
        """
        Overwrite an AI memory file with new content (markdown).
        Use 'brain' to update general knowledge or 'user_profile' to update the user profile.
        Always include the full updated content — this replaces the file entirely.
        """
        name = _safe_filename(filename)
        if name not in _ALLOWED_FILES:
            return f"Invalid memory file '{filename}'. Allowed: {', '.join(sorted(_ALLOWED_FILES))}."
        path = _memory_path(name)
        path.write_text(content, encoding="utf-8")
        return f"Memory file '{name}.md' updated ({len(content)} chars)."

    @mcp.tool()
    def append_to_memory(filename: str, entry: str) -> str:
        """
        Append a timestamped entry to an AI memory file.
        Use 'brain' for general facts or 'user_profile' for new user information.
        """
        name = _safe_filename(filename)
        if name not in _ALLOWED_FILES:
            return f"Invalid memory file '{filename}'. Allowed: {', '.join(sorted(_ALLOWED_FILES))}."
        path = _memory_path(name)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        new_entry = f"\n\n<!-- {timestamp} -->\n{entry.strip()}"
        path.write_text(existing + new_entry, encoding="utf-8")
        return f"Entry appended to '{name}.md'."
