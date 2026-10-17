"""First start: the demo project appears only when asked for, and only into an empty database."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config import settings
from app.db import repo


def _projects(path: str) -> list[str]:
    async def read():
        async with repo.db_context() as db:
            return [p["name"] for p in await repo.list_projects(db)]
    settings.database_path = path
    return asyncio.run(read())


def _start(tmp_path, name: str, *, seed: bool):
    settings.database_path = str(tmp_path / name)
    settings.telegram_bot_token = ""
    settings.coordinator_model = ""
    settings.seed_demo_if_empty = seed
    from app.main import app
    with TestClient(app):          # runs the startup code
        pass


def test_demo_project_is_created_on_first_start_when_enabled(tmp_path):
    saved = settings.seed_demo_if_empty
    try:
        _start(tmp_path, "first.db", seed=True)
        assert _projects(str(tmp_path / "first.db")) == ["FestPass"]
        _start(tmp_path, "first.db", seed=True)                      # a second start must not duplicate it
        assert _projects(str(tmp_path / "first.db")) == ["FestPass"]
    finally:
        settings.seed_demo_if_empty = saved


def test_nothing_is_created_unless_enabled_or_when_projects_exist(tmp_path):
    saved = settings.seed_demo_if_empty
    try:
        _start(tmp_path, "off.db", seed=False)
        assert _projects(str(tmp_path / "off.db")) == []

        settings.database_path = str(tmp_path / "mine.db")
        async def make():
            await repo.init_db()
            async with repo.db_context() as db:
                await repo.create_project(db, name="My real project")
        asyncio.run(make())
        _start(tmp_path, "mine.db", seed=True)                       # enabled, but the team already has a project
        assert _projects(str(tmp_path / "mine.db")) == ["My real project"]
    finally:
        settings.seed_demo_if_empty = saved
