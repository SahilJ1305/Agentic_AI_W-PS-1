"""Tier 2 policy: clarify, peer claims, undo flag, and lead override."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.agents.schemas import Interpretation, TaskUpdate
from app.config import settings
from app.core.notifications import buttons_for
from app.core.policy import apply as policy_apply
from app.db import repo
from app.db.seed_demo import seed
from app.telegram.outbox import _within_quiet_window
from app.telegram.router import _BARE_DONE


def test_bare_done_and_clarify_buttons():
    assert _BARE_DONE.match("done")
    assert _BARE_DONE.match("hogaya")
    assert not _BARE_DONE.match("slides done, video still left")
    labels = buttons_for("CLARIFY_TASK", {"tasks": [
        {"key": "T7", "title": "Record demo video", "status": "pending"},
        {"key": "T6", "title": "Prepare pitch slides", "status": "complete"},
    ]})
    assert labels[0].startswith("T7")
    assert labels[-1] == "None of these"
    assert _within_quiet_window(datetime.now(timezone.utc).isoformat())
    assert not _within_quiet_window((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())


def test_tier2_rules(tmp_path):
    settings.database_path = str(tmp_path / "tier2.db")
    asyncio.run(_rules())


async def _rules():
    await seed(force=True)
    now = "2026-10-16T15:00:00+00:00"
    async with repo.db_context() as db:
        project_id = (await (await db.execute(
            "SELECT id FROM projects WHERE name = 'FestPass'"
        )).fetchone())["id"]
        people = {p["name"]: p for p in await repo.list_participants(db, project_id)}

        peer = await policy_apply(
            interpretation=Interpretation(
                intent="status_update",
                raw_message="Kabir's API is done btw",
                updates=[TaskUpdate(task_key="T3", status="complete", status_confidence=0.9)],
            ),
            sender=people["Meera"],
            project_id=project_id,
            source_message_id=None,
            db=db,
            now=now,
        )
        assert peer.approved == []
        assert any(item.template_key == "PEER_CLAIM_CONFIRM" for item in peer.notifications._messages)
        assert any("R5" in line for line in peer.rule_log)
        kabir_task = await repo.get_task_by_key(db, project_id, "T3")
        assert kabir_task["status"] == "pending"

        conflict = await policy_apply(
            interpretation=Interpretation(
                intent="status_update",
                updates=[TaskUpdate(task_key="T5", status="complete", status_confidence=0.95)],
            ),
            sender=people["Meera"],
            project_id=project_id,
            source_message_id=None,
            db=db,
            now=now,
        )
        assert conflict.approved == []
        assert conflict.clarifications[0]["kind"] == "dependency_conflict"

        undo = await policy_apply(
            interpretation=Interpretation(intent="correction", raw_message="actually ignore that, not done"),
            sender=people["Aanya"],
            project_id=project_id,
            source_message_id=None,
            db=db,
            now=now,
        )
        assert undo.revert is True
        assert undo.approved == []

        both = await policy_apply(
            interpretation=Interpretation(
                intent="status_update",
                raw_message="slides final, video shoot at 9",
                updates=[
                    TaskUpdate(task_key="T7", status="in_progress", status_confidence=0.9, progress_note="shoot at 9"),
                    TaskUpdate(task_key="T8", status="pending", status_confidence=0.8, progress_note="after Meera"),
                ],
            ),
            sender=people["Aanya"],
            project_id=project_id,
            source_message_id=None,
            db=db,
            now=now,
        )
        assert [item.task_key for item in both.approved] == ["T7", "T8"]


def test_lead_override_changes_owner_and_status(tmp_path):
    settings.database_path = str(tmp_path / "override.db")
    settings.telegram_bot_token = ""
    settings.coordinator_model = ""
    asyncio.run(seed(force=True))

    from app.main import app

    with TestClient(app) as client:
        tasks = client.get("/api/projects/1/tasks").json()
        people = client.get("/api/projects/1/participants").json()
        video = next(task for task in tasks if task["key"] == "T7")
        meera = next(person for person in people if person["name"] == "Meera")
        page = client.get("/")
        assert "Lead override" in page.text
        saved = client.patch(f"/api/tasks/{video['id']}", json={
            "status": "in_progress",
            "owner_id": meera["id"],
            "reason": "Aanya asked Meera to cover the video",
            "expected_version": video["version"],
        })
        assert saved.status_code == 200, saved.text
        again = client.get("/api/projects/1/tasks").json()
        moved = next(task for task in again if task["key"] == "T7")
        assert moved["status"] == "in_progress"
        assert moved["owner_name"] == "Meera"
