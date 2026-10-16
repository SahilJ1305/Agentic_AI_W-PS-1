"""
Shared setup for the end-to-end tests: a seeded FestPass project, the real bot
wired to FakeBot, the real HTTP API, and a recorder for the live event stream.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Callable

import httpx
import jwt

from app.agents.schemas import BlockerOut, Interpretation, TaskUpdate
from app.api.sse import broadcaster
from app.config import settings
from app.db import repo
from app.db.seed_demo import seed
from tests.fake_telegram import Chat, FakeBot, settle

PEOPLE = {"Aanya": 101, "Kabir": 102, "Meera": 103, "Rohan": 104}   # name -> Telegram chat id
SECRET = "e2e-test-secret-e2e-test-secret-0000"
OVERRIDES = dict(
    demo_mode=False, quiet_min=0.0, debounce_s=0.01, nudge_after_min=1.0, blocker_escalate_min=1.0,
    secret_key=SECRET, github_repo="", github_token="", telegram_group_chat_id=None,
)


def update(key: str, status: str | None = None, **kw) -> TaskUpdate:
    return TaskUpdate(task_key=key, status=status, task_match_confidence=0.97, status_confidence=0.93, **kw)


class World:
    """`async with World(tmp_path) as w:` gives people, a bot, an API client and recorded events."""

    def __init__(self, tmp_path) -> None:
        self.db_file = str(tmp_path / "e2e.db")
        self.script: list[tuple[str, Callable[[], Interpretation]]] = []
        self.events: list[tuple[str, dict]] = []
        self._saved: dict = {}

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def __aenter__(self) -> "World":
        from app.main import app as api_app
        from app.telegram import gateway, router

        self._saved = {k: getattr(settings, k) for k in [*OVERRIDES, "database_path"]}
        for key, value in OVERRIDES.items():
            setattr(settings, key, value)
        settings.database_path = self.db_file

        router._user_locks.clear()
        router._debounce_buffers.clear()
        router._debounce_tasks.clear()
        broadcaster._subs.clear()

        await repo.init_db()
        await seed(force=True)
        async with repo.db_context() as db:
            self.project_id = (await (await db.execute("SELECT id FROM projects LIMIT 1")).fetchone())["id"]

        self.bot = FakeBot()
        self.app = gateway.build_application(bot=self.bot)
        await self.app.initialize()
        gateway.set_sse_publish(broadcaster.publish)

        self._orig_coordinator = router.run_coordinator
        router.run_coordinator = self._coordinator

        self.chat = {name: Chat(self.app, self.bot, cid, name) for name, cid in PEOPLE.items()}
        token = jwt.encode({"user_id": 1, "sub": "lead@example.com"}, SECRET, algorithm="HS256")
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://cadence.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        self._recorder = asyncio.create_task(self._record())
        await asyncio.sleep(0)      # let the recorder subscribe before anything is published
        return self

    async def __aexit__(self, *exc) -> None:
        from app.telegram import router

        self._recorder.cancel()
        await asyncio.gather(self._recorder, return_exceptions=True)
        await self.http.aclose()
        await self.app.shutdown()
        router.run_coordinator = self._orig_coordinator
        for key, value in self._saved.items():
            setattr(settings, key, value)

    async def _record(self) -> None:
        async for chunk in broadcaster.stream(self.project_id):
            match = re.match(r"(?:retry: \d+\n)?event: (\S+)\ndata: (.*)\n\n", chunk, re.S)
            if match and match.group(1) not in ("connected", "ping"):
                import json
                self.events.append((match.group(1), json.loads(match.group(2))))

    # ── scripted Coordinator (the LLM is the only thing that is not real) ─────
    def understands(self, phrase: str, build: Callable[[], Interpretation]) -> None:
        self.script.append((phrase.lower(), build))

    async def _coordinator(self, *, message_text: str, **_) -> Interpretation:
        lowered = message_text.lower()
        for phrase, build in self.script:
            if phrase in lowered:
                interpretation = build()
                interpretation.raw_message = message_text
                return interpretation
        return Interpretation(intent="off_topic", raw_message=message_text)

    # ── helpers ───────────────────────────────────────────────────────────────
    async def onboard_everyone(self) -> None:
        async with repo.db_context() as db:
            codes = {p["name"]: p["invite_code"] for p in await repo.list_participants(db, self.project_id)}
        for name, chat in self.chat.items():
            await chat.say(f"/start {codes[name]}")

    async def deliver(self) -> None:
        """Run the outbox worker until everything queued has been sent."""
        from app.telegram import outbox

        for _ in range(10):
            await outbox._tick(self.bot)
            async with repo.db_context() as db:
                waiting = await (await db.execute(
                    "SELECT COUNT(*) AS n FROM outbox WHERE status = 'queued' "
                    "AND (not_before IS NULL OR not_before <= ?)",
                    (datetime.now(timezone.utc).isoformat(),))).fetchone()
            if not waiting["n"]:
                return

    async def say(self, who: str, text: str) -> None:
        await self.chat[who].say(text)
        await self.deliver()
        await asyncio.sleep(0)

    async def tasks(self) -> dict[str, dict]:
        response = await self.http.get(f"/api/projects/{self.project_id}/tasks")
        assert response.status_code == 200, response.text
        return {t["key"]: t for t in response.json()}

    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]

    def events_of(self, name: str) -> list[dict]:
        return [payload for n, payload in self.events if n == name]
