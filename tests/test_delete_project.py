"""Deleting a project removes all of it, and only it, and never leaves the database inconsistent."""
from __future__ import annotations

import asyncio
import pathlib

import jwt

from app.db import repo
from tests.e2e_world import SECRET, World

SPEC = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "shelfshare-spec.md").read_bytes()
PROJECT_TABLES = [
    "participants", "source_documents", "plan_drafts", "milestones", "tasks", "messages",
    "dependencies", "reports", "outbox",
]


def run(coro):
    return asyncio.run(coro)


async def counts(project_id: int) -> dict[str, int]:
    """Rows that belong to a project, per table, including the ones reachable only through tasks or people."""
    queries = {t: f"SELECT COUNT(*) FROM {t} WHERE project_id = ?" for t in PROJECT_TABLES}
    queries["task_events"] = "SELECT COUNT(*) FROM task_events WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)"
    queries["blockers"] = "SELECT COUNT(*) FROM blockers WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)"
    queries["pending_questions"] = (
        "SELECT COUNT(*) FROM pending_questions WHERE participant_id IN (SELECT id FROM participants WHERE project_id = ?)")
    queries["project"] = "SELECT COUNT(*) FROM projects WHERE id = ?"
    async with repo.db_context() as db:
        return {t: (await (await db.execute(q, (project_id,))).fetchone())[0] for t, q in queries.items()}


async def fill_with_linked_rows(project_id: int) -> None:
    """Rows that point at each other the way a real project's do, so a careless delete order fails."""
    now = "2026-10-17T10:00:00+00:00"
    async with repo.db_context() as db:
        people = await repo.list_participants(db, project_id)
        tasks = await repo.list_tasks(db, project_id)
        msg = await repo.save_message(db, project_id=project_id, participant_id=people[0]["id"],
                                      direction="in", text="stuck on the login", now=now)
        await repo.append_task_event(db, task_id=tasks[0]["id"], event_type="status_changed", new_value="blocked",
                                     actor="coordinator", source_message_id=msg, now=now)
        blocker = await repo.create_blocker(db, task_id=tasks[0]["id"], description="creds", kind="task",
                                            linked_task_id=tasks[1]["id"], raised_message_id=msg, now=now)
        await repo.create_pending_question(db, participant_id=people[0]["id"], task_id=tasks[0]["id"],
                                           kind="status_check", message_id=msg, now=now)
        await repo.create_dependency(db, project_id=project_id, upstream_task_id=tasks[1]["id"],
                                     downstream_task_id=tasks[2]["id"], created_by_message_id=msg, now=now)
        await repo.resolve_blocker(db, blocker, resolved_message_id=msg, resolved_at=now)
        sent = await repo.save_message(db, project_id=project_id, participant_id=None, direction="out",
                                       channel="telegram_group", text="digest", template_key="DIGEST", now=now)
        # a digest to the team group: belongs to the project, to no person, and points at a message
        outbox = await repo.enqueue_message(db, participant_id=None, project_id=project_id, chat_id=-100123,
                                            template_key="DIGEST", text="digest", now=now)
        await db.execute("UPDATE outbox SET status='sent', sent_message_id=? WHERE id=?", (sent, outbox))
        await repo.save_plan_draft(db, project_id=project_id, plan_json="{}", validation_json="{}",
                                   llm_call_id=None, now=now)
        report = await repo.save_report(db, project_id=project_id, kind="digest", content_md="# d", now=now)
        await db.execute("UPDATE reports SET posted_message_id=? WHERE id=?", (sent, report))


def token_for(user_id: int) -> dict:
    return {"Authorization": "Bearer " + jwt.encode({"user_id": user_id, "sub": f"u{user_id}@example.com"}, SECRET, algorithm="HS256")}


def test_deleting_a_project_removes_all_of_it_and_nothing_else(tmp_path):
    run(_delete_everything(tmp_path))


async def _delete_everything(tmp_path):
    async with World(tmp_path) as w:
        festpass = w.project_id
        festpass_before = await counts(festpass)

        mine = (await w.http.post("/api/projects", json={"name": "ShelfShare"})).json()["id"]
        other = (await w.http.post("/api/projects", json={"name": "Keep me"})).json()["id"]
        for pid in (mine, other):
            up = await w.http.post(f"/api/projects/{pid}/documents", data={"kind": "spec"},
                                   files={"file": ("shelfshare-spec.md", SPEC, "text/markdown")})
            assert up.status_code == 200, up.text
        await fill_with_linked_rows(mine)
        await fill_with_linked_rows(other)
        before_mine, before_other = await counts(mine), await counts(other)
        assert all(before_mine[t] > 0 for t in before_mine), before_mine       # the fixture really covers every table

        # someone else's account cannot see, let alone delete, it
        stranger = await w.http.delete(f"/api/projects/{mine}", headers=token_for(2))
        assert stranger.status_code == 404
        assert (await counts(mine)) == before_mine

        done = await w.http.delete(f"/api/projects/{mine}")
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["status"] == "deleted" and body["name"] == "ShelfShare"
        assert body["removed"]["tasks"] == before_mine["tasks"] and body["removed"]["people"] == before_mine["participants"]
        assert "person_ids" not in body["removed"]

        gone = await counts(mine)
        assert not any(gone.values()), gone                                     # nothing left, in any table
        assert await counts(other) == before_other                              # a sibling project is untouched
        assert await counts(festpass) == festpass_before                        # so is the sample project
        async with repo.db_context() as db:
            assert await (await db.execute("PRAGMA foreign_key_check")).fetchall() == []   # no dangling references

        assert (await w.http.get(f"/api/projects/{mine}")).status_code == 404
        assert mine not in [p["id"] for p in (await w.http.get("/api/projects")).json()]
        assert (await w.http.delete(f"/api/projects/{mine}")).status_code == 404         # deleting twice is a clean 404


def test_the_shared_sample_project_cannot_be_deleted(tmp_path):
    run(_sample_is_protected(tmp_path))


async def _sample_is_protected(tmp_path):
    async with World(tmp_path) as w:
        before = await counts(w.project_id)
        refused = await w.http.delete(f"/api/projects/{w.project_id}")
        assert refused.status_code == 403 and "sample" in refused.json()["detail"]
        assert await counts(w.project_id) == before


def test_a_deleted_projects_people_can_no_longer_use_the_bot(tmp_path):
    run(_bot_forgets(tmp_path))


async def _bot_forgets(tmp_path):
    async with World(tmp_path) as w:
        pid = (await w.http.post("/api/projects", json={"name": "Short lived"})).json()["id"]
        person = (await w.http.post(f"/api/projects/{pid}/participants", json={"name": "Zoe"})).json()
        from tests.fake_telegram import Chat

        zoe = Chat(w.app, w.bot, 777, "Zoe", username="zoe")
        await zoe.say(f"/start {person['invite_code']}")
        async with repo.db_context() as db:
            assert (await repo.get_participant_by_chat_id(db, 777))["name"] == "Zoe"

        assert (await w.http.delete(f"/api/projects/{pid}")).status_code == 200
        async with repo.db_context() as db:
            assert await repo.get_participant_by_chat_id(db, 777) is None
        await zoe.say("/mytasks")
        assert "not in this project" in w.bot.last(777)["text"].lower()
        # and the same Telegram account can join a new project afterwards
        again = (await w.http.post("/api/projects", json={"name": "Next one"})).json()["id"]
        person2 = (await w.http.post(f"/api/projects/{again}/participants", json={"name": "Zoe"})).json()
        await zoe.say(f"/start {person2['invite_code']}")
        async with repo.db_context() as db:
            assert (await repo.get_participant_by_chat_id(db, 777))["project_id"] == again
