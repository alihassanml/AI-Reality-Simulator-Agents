"""Broadcast of simulation events to every connected dashboard."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any


class EventBus:
    """Fan-out to WebSocket clients, with a replay buffer for late joiners."""

    def __init__(self, buffer_size: int = 400) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._buffer: list[dict[str, Any]] = []
        self._buffer_size = buffer_size
        self._seq = 0

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def history(self) -> list[dict[str, Any]]:
        """Everything emitted since the last clear, so a refresh redraws the run."""
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()
        self._seq = 0

    async def emit(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        self._seq += 1
        event = {
            "seq": self._seq,
            "kind": kind,
            "at": datetime.now().strftime("%H:%M:%S"),
            **(payload or {}),
        }
        self._buffer.append(event)
        if len(self._buffer) > self._buffer_size:
            self._buffer.pop(0)

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled client must not block the simulation.
                self._subscribers.discard(queue)

    @staticmethod
    def encode(event: dict[str, Any]) -> str:
        return json.dumps(event, default=str)


bus = EventBus()
