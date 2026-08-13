"""Short-term memory: what an agent has seen during the current run (§8).

Lives in the run, not the database. Cleared when the simulation resets.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShortTermMemory:
    """Per-run working memory, keyed by agent."""

    inbox: dict[str, list[str]] = field(default_factory=dict)
    notes: dict[str, list[str]] = field(default_factory=dict)

    def deliver(self, agent: str, line: str) -> None:
        """Record a message that arrived for an agent."""
        self.inbox.setdefault(agent, []).append(line)

    def note(self, agent: str, line: str) -> None:
        """Record something the agent itself concluded."""
        self.notes.setdefault(agent, []).append(line)

    def recall(self, agent: str, limit: int = 8) -> str:
        """Render this agent's working memory as prompt text."""
        parts: list[str] = []
        inbox = self.inbox.get(agent, [])[-limit:]
        if inbox:
            parts.append("Messages you have received during this event:\n" +
                         "\n".join(f"- {line}" for line in inbox))
        notes = self.notes.get(agent, [])[-limit:]
        if notes:
            parts.append("Your own earlier conclusions during this event:\n" +
                         "\n".join(f"- {line}" for line in notes))
        return "\n\n".join(parts) if parts else "This is your first action in this event."

    def clear(self) -> None:
        self.inbox.clear()
        self.notes.clear()
