"""Long-term memory: durable facts an agent carries between events (§8).

Retrieval is plain SQL over a small, structured set -- keyword matching on
subject is enough here, and it keeps the whole store inspectable in the UI.
"""
from __future__ import annotations

from backend.db import execute, query


def recall(agent: str, subjects: list[str] | None = None, limit: int = 6) -> list[dict]:
    """Fetch an agent's most important memories, optionally filtered by subject."""
    if subjects:
        placeholders = ",".join("?" for _ in subjects)
        sql = (f"SELECT * FROM agent_memory WHERE agent = ? AND subject IN ({placeholders}) "
               f"ORDER BY importance DESC, id DESC LIMIT ?")
        params = (agent, *subjects, limit)
    else:
        sql = "SELECT * FROM agent_memory WHERE agent = ? ORDER BY importance DESC, id DESC LIMIT ?"
        params = (agent, limit)
    return query(sql, params)


def recall_text(agent: str, subjects: list[str] | None = None, limit: int = 6) -> str:
    """Render an agent's long-term memory as prompt text."""
    rows = recall(agent, subjects, limit)
    if not rows:
        return "You have no relevant long-term memories."
    return "\n".join(f"- {r['content']}" for r in rows)


def remember(agent: str, subject: str, content: str, importance: int = 3) -> int:
    """Store a new durable fact, skipping exact duplicates."""
    existing = query(
        "SELECT id FROM agent_memory WHERE agent = ? AND content = ?", (agent, content)
    )
    if existing:
        return existing[0]["id"]
    return execute(
        """INSERT INTO agent_memory (agent, subject, content, importance, created_at)
           VALUES (?,?,?,?, datetime('now'))""",
        (agent, subject, content, importance),
    )


def all_for(agent: str) -> list[dict]:
    return query(
        "SELECT * FROM agent_memory WHERE agent = ? ORDER BY importance DESC, id DESC", (agent,)
    )
