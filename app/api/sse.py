"""
app/api/sse.py — Server-Sent Events broadcaster.

One shared broadcaster instance handles all open /stream connections.
publish() sends an event to every connected dashboard.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

log = logging.getLogger(__name__)


class SSEBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    async def publish(self, event: str, payload: dict) -> None:
        """Broadcast an event to all connected dashboards."""
        data = json.dumps(payload)
        dead: list[asyncio.Queue] = []
        for q in self._queues:
            try:
                q.put_nowait(f"event: {event}\ndata: {data}\n\n")
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._queues.remove(q)

    async def stream(self, project_id: int) -> AsyncGenerator[str, None]:
        """Yield SSE strings; blocks until the client disconnects."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.append(q)
        try:
            # Initial ping to confirm connection
            yield "event: connected\ndata: {}\n\n"
            while True:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                yield msg
        except (asyncio.TimeoutError, asyncio.CancelledError):
            yield "event: ping\ndata: {}\n\n"
        finally:
            if q in self._queues:
                self._queues.remove(q)


# Singleton
broadcaster = SSEBroadcaster()
