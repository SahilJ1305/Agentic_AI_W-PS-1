"""
app/api/routes_tasks.py — task management and override endpoints.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import CurrentUser, can_see, current_user, visible_project, visible_task
from app.api.sse import broadcaster
from app.config import settings
from app.db import repo
from app.core.dependency_engine import recompute_all_readiness, compute_critical_path

router = APIRouter(tags=["tasks"])
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/projects/{pid}/tasks")
async def list_tasks(
    pid: int,
    status: str | None = None,
    owner_id: int | None = None,
    readiness: str | None = None,
    user: CurrentUser = Depends(current_user),
):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        tasks = await repo.list_tasks(db, pid, status=status, owner_id=owner_id, readiness=readiness)
        names = {
            person["id"]: person["name"]
            for person in await repo.list_participants(db, pid)
        }
        for task in tasks:
            task["owner_name"] = names.get(task.get("owner_id"))
            blockers = await repo.list_open_blockers_for_task(db, task["id"])
            task["blocker"] = blockers[0]["description"] if blockers else None
    return tasks


@router.get("/tasks/{tid}")
async def get_task(tid: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        task = await visible_task(db, tid, user)
        events = await repo.list_task_events(db, tid)
        blockers = await repo.list_open_blockers_for_task(db, tid)
        deps_up = await repo.list_dependencies_upstream(db, tid)
        deps_dn = await repo.list_dependencies_downstream(db, tid)
    return {
        "task": task,
        "events": events,
        "blockers": blockers,
        "upstream_deps": deps_dn,  # what this task waits for
        "downstream_deps": deps_up,  # what waits for this task
    }


class PatchTaskRequest(BaseModel):
    status: str | None = None
    owner_id: int | None = None
    deadline: str | None = None
    reason: str
    expected_version: int


@router.patch("/tasks/{tid}")
async def patch_task(tid: int, req: PatchTaskRequest, user: CurrentUser = Depends(current_user)):
    """Manual override from the dashboard. Requires reason and expected_version."""
    now = _now()
    async with repo.db_context() as db:
        task = await visible_task(db, tid, user)

        if task["version"] != req.expected_version:
            raise HTTPException(409, f"Version conflict. Current version: {task['version']}")

        ok = await repo.update_task_status(
            db,
            tid,
            status=req.status or task["status"],
            owner_id=req.owner_id,
            deadline=req.deadline,
            updated_at=now,
            expected_version=req.expected_version,
        )
        if not ok:
            raise HTTPException(409, "Version conflict (race condition).")

        await repo.append_task_event(
            db,
            task_id=tid,
            event_type="owner_changed" if req.owner_id and req.owner_id != task.get("owner_id") else "override",
            old_value=task["status"],
            new_value=req.status or task["status"],
            reason=f"{req.reason} ({user.email})",
            actor="lead",
            now=now,
        )
        owner_id = req.owner_id or task.get("owner_id")
        if owner_id:
            from app.core.notifications import NotificationBatch
            batch = NotificationBatch()
            batch.add(
                participant_id=owner_id,
                template_key="OVERRIDE_NOTICE",
                context={
                    "task": {**task, "key": task["key"], "title": task["title"]},
                    "status": req.status or task["status"],
                    "reason": req.reason,
                    "lead": "The lead",
                },
            )
            await batch.flush(db, now=now)

        if req.status == "complete" and task["status"] != "complete":
            from app.core.dependency_engine import on_task_completed
            batch = await on_task_completed(tid, None, db, now)
            await batch.flush(db, now=now)
        else:
            await recompute_all_readiness(task["project_id"], db, now)

    await broadcaster.publish("task.updated", {
        "task_key": task["key"],
        "status": req.status or task["status"],
        "reason": req.reason,
        "rule_fired": "lead override",
    })
    return {"status": "updated"}


@router.post("/tasks/{tid}/follow-up")
async def send_followup(tid: int, user: CurrentUser = Depends(current_user)):
    """Send a follow-up now for this task."""
    now = _now()
    async with repo.db_context() as db:
        task = await visible_task(db, tid, user)
        if not task.get("owner_id"):
            raise HTTPException(400, "Task has no owner")

        participant = await repo.get_participant(db, task["owner_id"])
        if not participant or not participant.get("telegram_chat_id"):
            raise HTTPException(400, "Owner not onboarded on Telegram")

        from app.core.notifications import NotificationBatch
        batch = NotificationBatch()
        batch.add(
            participant_id=task["owner_id"],
            template_key="FOLLOWUP_SINGLE",
            context={"task": task},
            question_kind="status_check",
            question_task_id=task["id"],
        )
        await batch.flush(db, now=now)
        await repo.set_last_followup(db, tid, at=now)

    return {"status": "queued"}


@router.post("/tasks/{tid}/events/{event_id}/revert")
async def revert_event(tid: int, event_id: int, user: CurrentUser = Depends(current_user)):
    now = _now()
    async with repo.db_context() as db:
        task = await visible_task(db, tid, user)
        event = await repo.list_task_events(db, tid)
        target = next((e for e in event if e["id"] == event_id), None)
        if not target:
            raise HTTPException(404, "Event not found")
        if target.get("reverted_by_event_id"):
            raise HTTPException(409, "Event already reverted")

        await repo.update_task_status(db, tid, status=target["old_value"], updated_at=now)
        revert_id = await repo.append_task_event(
            db,
            task_id=tid,
            event_type="reverted",
            old_value=target["new_value"],
            new_value=target["old_value"],
            reason=f"Reverted by {user.email}",
            actor="lead",
            now=now,
        )
        await repo.mark_event_reverted(db, event_id, revert_event_id=revert_id)

    await broadcaster.publish("task.updated", {"task_key": task["key"], "reason": "reverted"})
    return {"status": "reverted"}


@router.get("/participants/{participant_id}/invite")
async def participant_invite(participant_id: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        person = await repo.get_participant(db, participant_id)
        project = await repo.get_project(db, person["project_id"]) if person else None
    if not person or not can_see(project, user):
        raise HTTPException(404, "Participant not found")
    code = person["invite_code"]
    return {
        "name": person["name"],
        "invite_code": code,
        "deep_link": f"https://t.me/{settings.telegram_bot_username}?start={code}",
    }


@router.get("/projects/{pid}/blockers")
async def list_blockers(pid: int, status: str = "open", user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        tasks = await repo.list_tasks(db, pid)
        result = []
        for t in tasks:
            if status == "open":
                result.extend(await repo.list_open_blockers_for_task(db, t["id"]))
    return result


@router.post("/blockers/{bid}/resolve")
async def resolve_blocker(bid: int, body: dict, user: CurrentUser = Depends(current_user)):
    now = _now()
    async with repo.db_context() as db:
        blocker = await repo.get_blocker(db, bid)
        if not blocker:
            raise HTTPException(404, "Blocker not found")
        await visible_task(db, blocker["task_id"], user)
        await repo.resolve_blocker(db, bid, resolved_message_id=None, resolved_at=now)
        await repo.append_task_event(
            db,
            task_id=blocker["task_id"],
            event_type="blocker_resolved",
            old_value=blocker["description"],
            reason=body.get("reason", f"Resolved from the dashboard by {user.email}"),
            actor="lead",
            now=now,
        )
    await broadcaster.publish("blocker.resolved", {"blocker_id": bid})
    return {"status": "resolved"}


@router.get("/projects/{pid}/events")
async def list_events(pid: int, since: str | None = None, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        tasks = await repo.list_tasks(db, pid)
        events = []
        for t in tasks:
            evs = await repo.list_task_events(db, t["id"])
            for e in evs:
                if since is None or e["created_at"] >= since:
                    events.append({**e, "task_key": t["key"], "task_title": t["title"]})
    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events[:100]
