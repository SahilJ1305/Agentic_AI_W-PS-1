"""
app/api/sse.py — Server-Sent Events broadcaster.

One shared broadcaster fans events out to every open /stream connection.
Each connection belongs to one project and only receives that project's
events (payloads carry `project_id`). Events without a project_id go to
everyone, which only the health/admin paths use.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

log = logging.getLogger(__name__)

KEEPALIVE_S = 20.0       # proxies and browsers drop silent connections; ping before that
MAX_LIFETIME_S = 600.0   # then close; the browser reconnects, which re-checks the login token


class SSEBroadcaster:
    def __init__(self) -> None:
        self._subs: list[tuple[int | None, asyncio.Queue]] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def publish(self, event: str, payload: dict, project_id: int | None = None) -> None:
        """Send an event to the dashboards watching this project."""
        if project_id is None:
            project_id = payload.get("project_id")
        elif "project_id" not in payload:
            payload = {**payload, "project_id": project_id}
        message = f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
        for watching, queue in list(self._subs):
            if project_id is not None and watching is not None and watching != project_id:
                continue
            if queue.full():
                # A slow client loses its oldest event rather than its connection.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    async def stream(self, project_id: int) -> AsyncGenerator[str, None]:
        """Yield SSE strings until the client disconnects."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        entry = (project_id, queue)
        self._subs.append(entry)
        deadline = asyncio.get_running_loop().time() + MAX_LIFETIME_S
        try:
            yield "event: connected\ndata: {}\n\n"
            while asyncio.get_running_loop().time() < deadline:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            if entry in self._subs:
                self._subs.remove(entry)


# Singleton
broadcaster = SSEBroadcaster()
