"""Tier 1: spec import and the Kabir pending → blocked → complete loop."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.schemas import BlockerOut, Interpretation, TaskUpdate
from app.config import settings
from app.core.documents import parse_task_table, parse_team
from app.core.policy import apply as policy_apply
from app.db import repo
from app.db.seed_demo import seed
from app.telegram.router import _execute_update

ROOT = Path(__file__).resolve().parents[1]


def test_demo_spec_parses_team_and_tasks():
    spec = (ROOT / "docs" / "demo-spec.md").read_text()
    people = parse_team(spec)
    tasks = parse_task_table(spec)
    assert [person["name"] for person in people] == ["Aanya", "Kabir", "Meera", "Rohan"]
    assert people[0]["role"] == "lead"
    keys = [task["key"] for task in tasks]
    assert keys == ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
    kabir = next(task for task in tasks if task["key"] == "T3")
    assert kabir["owner"] == "Kabir"
    assert kabir["status"] == "pending"
    assert kabir["depends_on"] == [("T1", "hard")]
    video = next(task for task in tasks if task["key"] == "T7")
    assert ("T6", "soft") in video["depends_on"]


def test_upload_stores_spec_and_creates_tasks(tmp_path):
    settings.database_path = str(tmp_path / "upload.db")
    settings.telegram_bot_token = ""

    from app.main import app

    spec = (ROOT / "docs" / "demo-spec.md").read_bytes()
    with TestClient(app) as client:
        created = client.post("/api/projects", json={"name": "FestPass", "timezone": "Asia/Kolkata"})
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]
        uploaded = client.post(
            f"/api/projects/{project_id}/documents",
            data={"kind": "spec"},
            files={"file": ("demo-spec.md", spec, "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        body = uploaded.json()
        assert body["imported"]["tasks"] == 8
        tasks = client.get(f"/api/projects/{project_id}/tasks").json()
        by_key = {task["key"]: task for task in tasks}
        assert by_key["T3"]["owner_name"] == "Kabir"
        assert by_key["T3"]["status"] == "pending"
        assert by_key["T5"]["readiness"] == "waiting"
        assert by_key["T2"]["readiness"] == "ready"
        page = client.get("/")
        assert page.status_code == 200
        assert "Check in with everyone" in page.text

    async def originals():
        async with repo.db_context() as db:
            docs = await repo.list_source_documents(db, project_id)
        assert docs[0]["content"] == spec.decode()
        assert docs[0]["sha256"]

    asyncio.run(originals())


def test_kabir_loop_records_blocker_then_completes(tmp_path):
    settings.database_path = str(tmp_path / "kabir.db")
    asyncio.run(_kabir_loop())


async def _kabir_loop():
    await seed(force=True)

    async def publish(event, payload):
        return None

    async with repo.db_context() as db:
        cursor = await db.execute("SELECT id FROM projects WHERE name = 'FestPass'")
        project_id = (await cursor.fetchone())["id"]
        kabir = next(p for p in await repo.list_participants(db, project_id) if p["name"] == "Kabir")
        docs = await repo.list_source_documents(db, project_id)
        assert any(doc["kind"] == "spec" for doc in docs)

        blocked = Interpretation(
            intent="blocker_report",
            raw_message="The API is connected, but I am waiting for test credentials.",
            updates=[TaskUpdate(
                task_key="T3",
                task_match_confidence=0.95,
                status="complete",
                status_confidence=0.9,
                blocker=BlockerOut(description="test credentials", kind="external"),
                evidence="waiting for test credentials",
            )],
        )
        message_id = await repo.save_message(
            db,
            project_id=project_id,
            participant_id=kabir["id"],
            direction="in",
            text=blocked.raw_message,
            now="2026-10-16T12:00:00+00:00",
        )
        decision = await policy_apply(
            interpretation=blocked,
            sender=kabir,
            project_id=project_id,
            source_message_id=message_id,
            db=db,
            now="2026-10-16T12:00:00+00:00",
        )
        assert decision.approved[0].new_status == "blocked"
        assert decision.approved[0].blocker_description == "test credentials"
        assert any("R4" in line for line in decision.rule_log)
        for update in decision.approved:
            await _execute_update(
                update, project_id, kabir["id"], message_id, db,
                "2026-10-16T12:00:00+00:00", publish,
            )

        task = await repo.get_task_by_key(db, project_id, "T3")
        assert task["status"] == "blocked"
        blockers = await repo.list_open_blockers_for_task(db, task["id"])
        assert blockers[0]["description"] == "test credentials"
        events = await repo.list_task_events(db, task["id"])
        assert any(
            event["event_type"] == "status_changed"
            and event["new_value"] == "blocked"
            and event["source_message_id"] == message_id
            for event in events
        )

        finished = Interpretation(
            intent="status_update",
            raw_message="tested, done",
            updates=[TaskUpdate(
                task_key="T3",
                task_match_confidence=1.0,
                status="complete",
                status_confidence=0.95,
                evidence="tested, done",
            )],
        )
        done_id = await repo.save_message(
            db,
            project_id=project_id,
            participant_id=kabir["id"],
            direction="in",
            text=finished.raw_message,
            now="2026-10-16T13:00:00+00:00",
        )
        done = await policy_apply(
            interpretation=finished,
            sender=kabir,
            project_id=project_id,
            source_message_id=done_id,
            db=db,
            now="2026-10-16T13:00:00+00:00",
        )
        assert done.approved[0].new_status == "complete"
        for update in done.approved:
            await _execute_update(
                update, project_id, kabir["id"], done_id, db,
                "2026-10-16T13:00:00+00:00", publish,
            )
        task = await repo.get_task_by_key(db, project_id, "T3")
        assert task["status"] == "complete"
        assert await repo.list_open_blockers_for_task(db, task["id"]) == []
