"""Dependencies injected into every agent run."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.memory.short_term import ShortTermMemory

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class AgentDeps:
    """Context handed to tools during a run.

    `emit` pushes a live event to the dashboard so tool calls are visible as
    they happen rather than only in the final decision.
    """

    agent: str
    run_id: str
    stm: ShortTermMemory
    emit: EmitFn

    async def trace(self, tool: str, detail: str) -> None:
        await self.emit("tool_call", {"actor": self.agent, "tool": tool, "detail": detail})
