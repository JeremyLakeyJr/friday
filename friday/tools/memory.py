"""
Memory tools — SQLite + FTS5 persistent memory store.

Each memory is a short fact/note with a category and importance level:
  importance 5 = pinned, always injected into every prompt
  importance 3 = normal, injected only when FTS-relevant to the current message
  importance 1 = archived, never auto-injected

Legacy brain.md / user_profile.md are imported on first run then renamed.
"""

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent.parent
DB_PATH = _ROOT / "memory" / "friday.db"
_LEGACY = {
    "brain": _ROOT / "memory" / "brain.md",
    "user_profile": _ROOT / "memory" / "user_profile.md",
}

PINNED_THRESHOLD = 5  # importance >= this → always shown


# ---------------------------------------------------------------------------
# DB init
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            category  TEXT NOT NULL DEFAULT 'general',
            key       TEXT UNIQUE,
            content   TEXT NOT NULL,
            importance INTEGER DEFAULT 3,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content, key, category,
            content=memories,
            content_rowid=id
        );
        CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, key, category)
            VALUES (new.id, new.content, COALESCE(new.key,''), new.category);
        END;
        CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, key, category)
            VALUES ('delete', old.id, old.content, COALESCE(old.key,''), old.category);
        END;
        CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, key, category)
            VALUES ('delete', old.id, old.content, COALESCE(old.key,''), old.category);
            INSERT INTO memories_fts(rowid, content, key, category)
            VALUES (new.id, new.content, COALESCE(new.key,''), new.category);
        END;
    """)
    c.commit()
    _migrate_legacy(c)
    c.close()


def _migrate_legacy(c: sqlite3.Connection):
    """Import brain.md / user_profile.md into DB once, then rename them."""
    for category, path in _LEGACY.items():
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        key = f"legacy_{category}"
        if c.execute("SELECT 1 FROM memories WHERE key=?", (key,)).fetchone():
            continue
        c.execute(
            "INSERT INTO memories (category, key, content, importance) VALUES (?,?,?,?)",
            (category, key, content, 4),
        )
        c.commit()
        path.rename(path.with_suffix(".md.imported"))


# ---------------------------------------------------------------------------
# Sync helpers (wrapped in asyncio.to_thread for public tools)
# ---------------------------------------------------------------------------

def _sync_add(content: str, category: str, key: Optional[str], importance: int) -> str:
    c = _conn()
    try:
        if key and c.execute("SELECT 1 FROM memories WHERE key=?", (key,)).fetchone():
            c.execute(
                "UPDATE memories SET content=?,category=?,importance=?,updated_at=datetime('now') WHERE key=?",
                (content, category, importance, key),
            )
            c.commit()
            return f"Memory updated (key={key!r})."
        cur = c.execute(
            "INSERT INTO memories (category, key, content, importance) VALUES (?,?,?,?)",
            (category, key, content, importance),
        )
        c.commit()
        return f"Memory saved (id={cur.lastrowid}, category={category!r})."
    finally:
        c.close()


def _sync_search(query: str, limit: int) -> list[dict]:
    c = _conn()
    try:
        rows = c.execute(
            """SELECT m.id, m.category, m.key, m.content, m.importance
               FROM memories_fts f JOIN memories m ON m.id=f.rowid
               WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def _sync_forget(identifier: str) -> str:
    c = _conn()
    try:
        row = c.execute("SELECT id FROM memories WHERE key=?", (identifier,)).fetchone()
        if not row and identifier.isdigit():
            row = c.execute("SELECT id FROM memories WHERE id=?", (int(identifier),)).fetchone()
        if not row:
            return f"No memory found for {identifier!r}."
        c.execute("DELETE FROM memories WHERE id=?", (row["id"],))
        c.commit()
        return f"Memory {identifier!r} deleted."
    finally:
        c.close()


def _sync_list(category: Optional[str]) -> list[dict]:
    c = _conn()
    try:
        q = ("SELECT id, category, key, importance, substr(content,1,120) AS preview "
             "FROM memories {} ORDER BY importance DESC, updated_at DESC")
        if category:
            rows = c.execute(q.format("WHERE category=?"), (category,)).fetchall()
        else:
            rows = c.execute(q.format("")).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def _sync_get_context(user_text: str) -> str:
    """Return pinned memories + FTS-relevant memories as a formatted string."""
    c = _conn()
    try:
        pinned = c.execute(
            "SELECT content FROM memories WHERE importance>=? ORDER BY importance DESC",
            (PINNED_THRESHOLD,),
        ).fetchall()

        relevant = []
        tokens = [w for w in user_text.split() if len(w) > 3]
        if tokens:
            fts_q = " OR ".join(tokens[:8])
            try:
                relevant = c.execute(
                    """SELECT m.content FROM memories_fts f JOIN memories m ON m.id=f.rowid
                       WHERE memories_fts MATCH ? AND m.importance<? ORDER BY rank LIMIT 5""",
                    (fts_q, PINNED_THRESHOLD),
                ).fetchall()
            except sqlite3.OperationalError:
                pass

        parts = []
        if pinned:
            parts.append("### Pinned\n" + "\n---\n".join(r["content"] for r in pinned))
        if relevant:
            parts.append("### Relevant\n" + "\n---\n".join(r["content"] for r in relevant))
        if not parts:
            return ""
        return "\n\n## Memory\n\n" + "\n\n".join(parts)
    finally:
        c.close()


def get_memory_context(user_text: str = "") -> str:
    """Called from agent.py — sync, returns string for system prompt."""
    return _sync_get_context(user_text)


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------

def register(mcp):

    @mcp.tool()
    async def add_memory(content: str, category: str, importance: int) -> str:
        """
        Save a new fact to persistent memory (SQLite).
        category: 'user_profile', 'brain', 'project', or any label.
        importance: 1-5. 5=always injected into every prompt, 3=injected when relevant, 1=archived.
        """
        return await asyncio.to_thread(_sync_add, content, category, None, importance)

    @mcp.tool()
    async def update_memory(key: str, content: str, category: str, importance: int) -> str:
        """
        Upsert a named memory entry by key. Use to correct or replace a specific fact.
        """
        return await asyncio.to_thread(_sync_add, content, category, key, importance)

    @mcp.tool()
    async def search_memory(query: str) -> str:
        """Full-text search across all memories. Returns up to 5 matching entries."""
        results = await asyncio.to_thread(_sync_search, query, 5)
        if not results:
            return "No memories found."
        return "\n\n".join(
            f"[id={r['id']} cat={r['category']} imp={r['importance']}] {r['content'][:300]}"
            for r in results
        )

    @mcp.tool()
    async def forget_memory(identifier: str) -> str:
        """Delete a memory by its key name or numeric id."""
        return await asyncio.to_thread(_sync_forget, identifier)

    @mcp.tool()
    async def list_memories(category: str) -> str:
        """
        List all memory entries, optionally filtered by category.
        Pass empty string to list all.
        """
        results = await asyncio.to_thread(_sync_list, category.strip() or None)
        if not results:
            return "No memories found."
        return "\n".join(
            f"[id={r['id']} cat={r['category']} imp={r['importance']}] ({r['key'] or '—'}) {r['preview']}…"
            for r in results
        )


_init_db()
