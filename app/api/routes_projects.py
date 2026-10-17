"""
app/api/routes_projects.py — project and document management endpoints.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

import secrets

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel

from app.agents.planner import run_planner
from app.agents.schemas import PlanDraft
from app.api.auth import CurrentUser, current_user, visible_project
from app.api.sse import broadcaster
from app.config import settings
from app.core import invites
from app.core.taskview import load_view
from app.core.dependency_engine import validate_graph, recompute_all_readiness, compute_critical_path
from app.core.documents import (
    ensure_participants_from_spec,
    import_task_document,
    parse_task_table,
)
from app.core.notifications import render_template
from app.db import repo
from app.llm.gateway import LLMFailure

router = APIRouter(prefix="/projects", tags=["projects"])
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateProjectRequest(BaseModel):
    name: str
    timezone: str = "Asia/Kolkata"


@router.get("")
async def list_projects(user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        return await repo.list_projects(db, user_id=user.id)


@router.post("")
async def create_project(req: CreateProjectRequest, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        pid = await repo.create_project(
            db, name=req.name, timezone=req.timezone, owner_user_id=user.id,
        )
        project = await repo.get_project(db, pid)
    return project


@router.delete("/{pid}")
async def delete_project(pid: int, user: CurrentUser = Depends(current_user)):
    """
    Permanently delete one of your projects: its tasks, plan, history, messages and invite links.
    The shared sample project (no owner) cannot be deleted from here.
    """
    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        if project.get("owner_user_id") is None:
            raise HTTPException(403, "The shared sample project can't be deleted.")
        removed = await repo.delete_project(db, pid)

    # Forget anything still waiting in memory for those people (their ids can be reused later).
    from app.telegram import router as telegram_router

    for person_id in removed.pop("person_ids"):
        telegram_router._debounce_buffers.pop(person_id, None)
        task = telegram_router._debounce_tasks.pop(person_id, None)
        if task and not task.done():
            task.cancel()
    await broadcaster.publish("project.deleted", {"project_id": pid, "name": project["name"]})
    return {"status": "deleted", "name": project["name"], "removed": removed}


@router.get("/{pid}")
async def get_project(pid: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        view = await load_view(db, pid)
    by_status: dict[str, int] = {}
    for t in view.tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    return {
        "project": project,
        "task_counts": by_status,
        "total_tasks": len(view.tasks),
        "open_blockers": sum(len(b) for b in view.open_blockers.values()),
        "critical_path": view.critical_path,
        "risks": [r.as_dict() for r in view.risks],
        "progress": {"complete": by_status.get("complete", 0), "total": len(view.tasks)},
        "git_check": {"enabled": settings.git_check_enabled, "repo": settings.github_repo or None},
    }


@router.post("/{pid}/documents")
async def upload_document(
    pid: int,
    kind: Annotated[str, Form()],
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(current_user),
):
    """Upload a spec, task_doc, or roster. The original text is stored unchanged."""
    allowed_kinds = ("spec", "task_doc", "roster")
    if kind not in allowed_kinds:
        raise HTTPException(400, f"kind must be one of {allowed_kinds}")

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Only UTF-8 text files are supported.")

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    now = _now()
    imported = None

    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        doc_id = await repo.save_source_document(
            db,
            project_id=pid,
            kind=kind,
            filename=file.filename or "upload",
            mime_type=file.content_type or "text/plain",
            content=content,
            sha256=sha256,
            uploaded_at=now,
        )
        docs = await repo.list_source_documents(db, pid)
        spec_text = next((doc["content"] for doc in docs if doc["kind"] == "spec"), None)
        task_text = next(
            (doc["content"] for doc in docs if parse_task_table(doc["content"])),
            None,
        )
        if spec_text:
            await ensure_participants_from_spec(db, pid, spec_text)
        if task_text:
            imported = await import_task_document(db, pid, task_text, now)
            await repo.update_project_status(db, pid, "active")
        elif kind == "spec":
            participants = await repo.list_participants(db, pid)
            roster = [
                {"name": person["name"], "role": person["role"], "skills": person.get("skills", "")}
                for person in participants
            ]
            background_tasks.add_task(
                _run_planner_bg, pid, project["name"], content, None, roster
            )
    return {"document_id": doc_id, "kind": kind, "sha256": sha256, "imported": imported}


@router.post("/{pid}/plan")
async def run_plan(
    pid: int,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(current_user),
):
    """Run the Planner Agent asynchronously. Returns draft_id; SSE plan.ready when done."""
    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        docs = await repo.list_source_documents(db, pid)
        participants = await repo.list_participants(db, pid)

    spec_text = next((d["content"] for d in docs if d["kind"] == "spec"), None)
    if not spec_text:
        raise HTTPException(400, "No spec document uploaded yet. Upload a spec first.")

    task_doc_text = next((d["content"] for d in docs if d["kind"] == "task_doc"), None)
    roster = [{"name": p["name"], "role": p["role"], "skills": p.get("skills", "")} for p in participants]

    # Run in background
    background_tasks.add_task(_run_planner_bg, pid, project["name"], spec_text, task_doc_text, roster)
    return {"status": "planning", "message": "Planner is running. Listen to SSE plan.ready."}


async def _run_planner_bg(pid, project_name, spec_text, task_doc_text, roster):
    now = _now()
    try:
        async with repo.db_context() as db:
            draft = await run_planner(
                project_name=project_name,
                now=now,
                timezone=settings.timezone,
                roster=roster,
                spec_text=spec_text,
                task_doc_text=task_doc_text,
                db=db,
            )
            # Validate graph
            known_keys = {t.key for t in draft.tasks}
            result = validate_graph(draft.dependencies, known_keys)
            validation = {
                "accepted": len(result.accepted),
                "proposed": len(result.proposed),
                "dropped": len(result.dropped),
                "warnings": result.warnings,
            }
            draft_id = await repo.save_plan_draft(
                db,
                project_id=pid,
                plan_json=draft.model_dump_json(),
                validation_json=json.dumps(validation),
                llm_call_id=None,
                now=now,
            )
        await broadcaster.publish("plan.ready", {"project_id": pid, "draft_id": draft_id, "warnings_count": len(result.warnings)})
    except LLMFailure as e:
        log.error("Planner LLM failure: %s", e)
        if task_doc_text and parse_task_table(task_doc_text):
            async with repo.db_context() as db:
                if spec_text:
                    await ensure_participants_from_spec(db, pid, spec_text)
                imported = await import_task_document(db, pid, task_doc_text, now)
                await repo.update_project_status(db, pid, "active")
            await broadcaster.publish("plan.committed", {"project_id": pid, "imported": imported})
            return
        await broadcaster.publish("plan.error", {"project_id": pid, "error": str(e)})
    except Exception as e:
        log.exception("Planner background task failed")
        await broadcaster.publish("plan.error", {"project_id": pid, "error": f"Planner crashed: {e}"})


@router.get("/{pid}/plan/latest")
async def latest_plan_draft(pid: int, user: CurrentUser = Depends(current_user)):
    """The newest draft still waiting for review, so the page can resume after a reload."""
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        cur = await db.execute(
            "SELECT * FROM plan_drafts WHERE project_id = ? AND status = 'review' ORDER BY id DESC LIMIT 1",
            (pid,),
        )
        draft = await cur.fetchone()
    if not draft:
        raise HTTPException(404, "No draft waiting for review")
    return {
        "draft_id": draft["id"],
        "draft": json.loads(draft["plan_json"]),
        "validation": json.loads(draft["validation_json"]),
        "status": draft["status"],
    }


@router.get("/{pid}/plan/{draft_id}")
async def get_plan_draft(pid: int, draft_id: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        draft = await repo.get_plan_draft(db, draft_id)
    if not draft or draft["project_id"] != pid:
        raise HTTPException(404, "Draft not found")
    plan = json.loads(draft["plan_json"])
    validation = json.loads(draft["validation_json"])
    return {"draft": plan, "validation": validation, "status": draft["status"]}


class CommitPlanRequest(BaseModel):
    accepted_edge_pairs: list[list[str]] = []  # [[upstream, downstream], ...]
    rejected_edge_pairs: list[list[str]] = []
    owner_overrides: dict[str, str] = {}  # {task_key: participant_name}


@router.post("/{pid}/plan/{draft_id}/commit")
async def commit_plan(
    pid: int,
    draft_id: int,
    req: CommitPlanRequest,
    user: CurrentUser = Depends(current_user),
):
    now = _now()
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        draft_row = await repo.get_plan_draft(db, draft_id)
        if not draft_row or draft_row["project_id"] != pid:
            raise HTTPException(404, "Draft not found")
        if draft_row["status"] != "review":
            raise HTTPException(409, "Draft already committed or discarded")

        plan: PlanDraft = PlanDraft.model_validate(json.loads(draft_row["plan_json"]))
        participants = await repo.list_participants(db, pid)
        participant_map = {p["name"]: p for p in participants}

        # Create milestones
        milestone_ids: dict[str, int] = {}
        for m in plan.milestones:
            existing = await repo.get_milestone_by_key(db, pid, m.key)
            if existing:
                milestone_ids[m.key] = existing["id"]
            else:
                mid = await repo.create_milestone(db, project_id=pid, key=m.key, name=m.name, due=m.due)
                milestone_ids[m.key] = mid

        # Create tasks
        task_ids: dict[str, int] = {}
        for t in plan.tasks:
            owner_name = req.owner_overrides.get(t.key, t.owner_name)
            owner_id = participant_map.get(owner_name, {}).get("id") if owner_name else None
            mid = milestone_ids.get(t.milestone_key or "")
            existing = await repo.get_task_by_key(db, pid, t.key)
            if existing:
                task_ids[t.key] = existing["id"]
            else:
                tid = await repo.create_task(
                    db,
                    project_id=pid,
                    key=t.key,
                    title=t.title,
                    description=t.description,
                    acceptance=t.acceptance,
                    owner_id=owner_id,
                    deadline=t.deadline,
                    estimate_hours=t.estimate_hours,
                    requires_evidence=t.requires_evidence,
                    milestone_id=mid,
                    source="planner",
                    now=now,
                )
                task_ids[t.key] = tid

        # Create accepted dependencies
        accepted_set = {(u, d) for u, d in req.accepted_edge_pairs}
        rejected_set = {(u, d) for u, d in req.rejected_edge_pairs}
        all_accepted = validate_graph(plan.dependencies, set(task_ids.keys()))

        for dep in all_accepted.accepted:
            pair = (dep.upstream, dep.downstream)
            if pair in rejected_set:
                continue  # the lead rejected this edge in the review screen
            if req.accepted_edge_pairs and pair not in accepted_set:
                continue  # the lead reviewed the list and left this one out
            up_id = task_ids.get(dep.upstream)
            dn_id = task_ids.get(dep.downstream)
            if up_id and dn_id:
                await repo.create_dependency(
                    db,
                    project_id=pid,
                    upstream_task_id=up_id,
                    downstream_task_id=dn_id,
                    type=dep.type,
                    source="inferred" if dep.rule else "explicit",
                    state="active",
                    confidence=dep.confidence,
                    reason=dep.reason,
                    evidence=dep.evidence_quote or dep.rule,
                    now=now,
                )

        for dep in all_accepted.proposed:
            if (dep.upstream, dep.downstream) in accepted_set:
                state = "active"
            elif (dep.upstream, dep.downstream) in rejected_set:
                state = "rejected"
            else:
                state = "proposed"
            up_id = task_ids.get(dep.upstream)
            dn_id = task_ids.get(dep.downstream)
            if up_id and dn_id:
                await repo.create_dependency(
                    db,
                    project_id=pid,
                    upstream_task_id=up_id,
                    downstream_task_id=dn_id,
                    type=dep.type,
                    source="inferred",
                    state=state,
                    confidence=dep.confidence,
                    reason=dep.reason,
                    evidence=dep.evidence_quote or dep.rule,
                    now=now,
                )

        # Recompute readiness and critical path
        await recompute_all_readiness(pid, db, now)
        await compute_critical_path(pid, db, now)

        # Mark draft committed
        await repo.commit_plan_draft(db, draft_id, committed_at=now)
        await repo.update_project_status(db, pid, "active")

    await broadcaster.publish("plan.committed", {"project_id": pid, "draft_id": draft_id})
    return {"status": "committed", "tasks": len(task_ids)}


@router.get("/{pid}/stream")
async def stream_events(pid: int, user: CurrentUser = Depends(current_user)):
    """SSE endpoint for the dashboard. The browser passes ?token= because EventSource has no headers."""
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
    return StreamingResponse(
        broadcaster.stream(pid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class CreateParticipantRequest(BaseModel):
    name: str
    role: str = "member"
    skills: str | None = None
    telegram_username: str | None = None
    github_username: str | None = None


class UpdateParticipantRequest(BaseModel):
    github_username: str | None = None
    telegram_username: str | None = None


def _handle(value: str | None) -> str | None:
    return (value or "").strip().lstrip("@") or None


@router.post("/{pid}/participants")
async def add_participant(
    pid: int,
    req: CreateParticipantRequest,
    user: CurrentUser = Depends(current_user),
):
    if req.role not in ("lead", "member"):
        raise HTTPException(400, "role must be lead or member")
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        participant_id = await repo.create_participant(
            db,
            project_id=pid,
            name=req.name,
            role=req.role,
            skills=req.skills,
            invite_code=secrets.token_urlsafe(12),
            telegram_username=_handle(req.telegram_username),
            github_username=_handle(req.github_username),
        )
        participant = await repo.get_participant(db, participant_id)
    return _with_invite(participant)


@router.patch("/{pid}/participants/{participant_id}")
async def update_participant(
    pid: int,
    participant_id: int,
    req: UpdateParticipantRequest,
    user: CurrentUser = Depends(current_user),
):
    """
    Set the GitHub account (Git claim checker) or Telegram account (invite check), project owner only.
    Omitted fields stay as they are.
    """
    username = _handle(req.github_username)
    github_sent = "github_username" in req.model_fields_set
    telegram_sent = "telegram_username" in req.model_fields_set
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        participant = await repo.get_participant(db, participant_id)
        if not participant or participant["project_id"] != pid:
            raise HTTPException(404, "Participant not found")
        if telegram_sent:
            # Decide before changing anything, so a rejected request leaves no half-saved state.
            reason = invites.rejection_reason(participant, req.telegram_username)
            if reason:
                raise HTTPException(409, reason)
        changed = github_sent and username != participant.get("github_username")
        if github_sent:
            await repo.set_participant_github(db, participant_id, username)
        if telegram_sent:
            await repo.set_participant_telegram_username(db, participant_id, _handle(req.telegram_username))
        participant = await repo.get_participant(db, participant_id)
        if changed and username and participant.get("telegram_chat_id"):
            # Let them know, with a button to recheck what they already finished.
            from app.core.notifications import NotificationBatch

            batch = NotificationBatch()
            batch.add(
                participant_id=participant_id,
                template_key="GIT_LINKED",
                context={"github": username},
                static_buttons=[("Recheck my tasks", "git:recheck")],
            )
            await batch.flush(db, now=_now())
    if changed or telegram_sent:
        await broadcaster.publish("team.changed", {"project_id": pid, "participant": participant["name"]})
    return _with_invite(participant)


@router.post("/{pid}/participants/{participant_id}/reset-invite")
async def reset_invite(pid: int, participant_id: int, user: CurrentUser = Depends(current_user)):
    """Disconnect the Telegram account that joined as this person and issue a fresh invite link."""
    now = datetime.now(timezone.utc).isoformat()
    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        participant = await repo.get_participant(db, participant_id)
        if not participant or participant["project_id"] != pid:
            raise HTTPException(404, "Participant not found")
        old_chat = participant.get("telegram_chat_id")
        await repo.reset_participant_invite(db, participant_id, invite_code=secrets.token_urlsafe(12))
        if old_chat:
            await repo.enqueue_message(
                db,
                participant_id=None,
                project_id=pid,
                chat_id=old_chat,
                template_key="INVITE_UNLINKED",
                text=render_template("INVITE_UNLINKED", {"project": project["name"]}),
                now=now,
            )
        participant = await repo.get_participant(db, participant_id)
    await broadcaster.publish("team.changed", {"project_id": pid, "participant": participant["name"]})
    return _with_invite(participant)


@router.get("/{pid}/participants")
async def list_participants(pid: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        participants = await repo.list_participants(db, pid)
        tasks = await repo.list_tasks(db, pid)
    result = []
    for person in participants:
        mine = [t for t in tasks if t.get("owner_id") == person["id"]]
        person = _with_invite(person)
        person["task_count"] = len(mine)
        person["open_task_count"] = sum(t["status"] != "complete" for t in mine)
        result.append(person)
    return result


def _with_invite(person: dict | None) -> dict | None:
    if not person:
        return None
    username = settings.telegram_bot_username
    code = person.get("invite_code")
    person = dict(person)
    person["deep_link"] = f"https://t.me/{username}?start={code}" if code else None
    person["joined_username"] = invites.joined_handle(person)
    person["username_mismatch"] = invites.username_mismatch(person)
    return person


@router.get("/{pid}/graph")
async def get_graph(pid: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        view = await load_view(db, pid)
    keys = {t["id"]: t["key"] for t in view.tasks}
    nodes = [
        {
            "id": t["id"],
            "key": t["key"],
            "title": t["title"],
            "status": t["status"],
            "readiness": t["readiness"],
            "on_critical_path": bool(t["on_critical_path"]),
            "owner_name": t.get("owner_name"),
        }
        for t in view.tasks
    ]
    edges = [
        {
            "id": d["id"],
            "upstream": d["upstream_task_id"],
            "downstream": d["downstream_task_id"],
            "upstream_key": keys.get(d["upstream_task_id"]),
            "downstream_key": keys.get(d["downstream_task_id"]),
            "type": d["type"],
            "source": d["source"],
            "state": d["state"],
            "confidence": d["confidence"],
            "reason": d.get("reason"),
        }
        for d in view.deps
    ]
    return {"nodes": nodes, "edges": edges, "critical_path": view.critical_path}
