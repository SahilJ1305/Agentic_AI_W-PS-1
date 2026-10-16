"""
app/api/routes_projects.py — project and document management endpoints.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel

from app.agents.planner import run_planner
from app.agents.schemas import PlanDraft
from app.api.sse import broadcaster
from app.config import settings
from app.core.dependency_engine import validate_graph, recompute_all_readiness, compute_critical_path
from app.db import repo
from app.llm.gateway import LLMFailure

router = APIRouter(prefix="/projects", tags=["projects"])
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreateProjectRequest(BaseModel):
    name: str
    timezone: str = "Asia/Kolkata"


@router.post("")
async def create_project(req: CreateProjectRequest):
    async with repo.db_context() as db:
        pid = await repo.create_project(db, name=req.name, timezone=req.timezone)
        project = await repo.get_project(db, pid)
    return project


@router.get("/{pid}")
async def get_project(pid: int):
    async with repo.db_context() as db:
        project = await repo.get_project(db, pid)
        if not project:
            raise HTTPException(404, "Project not found")
        tasks = await repo.list_tasks(db, pid)
        by_status = {}
        for t in tasks:
            by_status.setdefault(t["status"], 0)
            by_status[t["status"]] += 1
        blockers = await repo.list_open_blockers(db, pid)
    return {
        "project": project,
        "task_counts": by_status,
        "total_tasks": len(tasks),
        "open_blockers": len(blockers),
    }


@router.post("/{pid}/documents")
async def upload_document(
    pid: int,
    kind: Annotated[str, Form()],
    file: UploadFile = File(...),
):
    """Upload a spec, task_doc, or roster document."""
    allowed_kinds = ("spec", "task_doc", "roster")
    if kind not in allowed_kinds:
        raise HTTPException(400, f"kind must be one of {allowed_kinds}")

    content_bytes = await file.read()
    # For PDF, extract text (basic: just decode as utf-8 for now)
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Only UTF-8 text files are supported. PDF requires pdfminer.")

    sha256 = hashlib.sha256(content_bytes).hexdigest()
    now = _now()

    async with repo.db_context() as db:
        project = await repo.get_project(db, pid)
        if not project:
            raise HTTPException(404, "Project not found")
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
    return {"document_id": doc_id, "kind": kind, "sha256": sha256}


@router.post("/{pid}/plan")
async def run_plan(pid: int, background_tasks: BackgroundTasks):
    """Run the Planner Agent asynchronously. Returns draft_id; SSE plan.ready when done."""
    async with repo.db_context() as db:
        project = await repo.get_project(db, pid)
        if not project:
            raise HTTPException(404, "Project not found")
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
        await broadcaster.publish("plan.ready", {"draft_id": draft_id, "warnings_count": len(result.warnings)})
    except LLMFailure as e:
        log.error("Planner LLM failure: %s", e)
        await broadcaster.publish("plan.error", {"error": str(e)})
    except Exception:
        log.exception("Planner background task failed")


@router.get("/{pid}/plan/{draft_id}")
async def get_plan_draft(pid: int, draft_id: int):
    async with repo.db_context() as db:
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
async def commit_plan(pid: int, draft_id: int, req: CommitPlanRequest):
    now = _now()
    async with repo.db_context() as db:
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
        all_accepted = validate_graph(plan.dependencies, set(task_ids.keys()))

        for dep in all_accepted.accepted:
            if req.accepted_edge_pairs and (dep.upstream, dep.downstream) not in accepted_set:
                continue  # skip if lead rejected it via UI
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
async def stream_events(pid: int):
    """SSE endpoint for the dashboard."""
    return StreamingResponse(
        broadcaster.stream(pid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{pid}/participants")
async def list_participants(pid: int):
    async with repo.db_context() as db:
        participants = await repo.list_participants(db, pid)
    return participants


@router.get("/{pid}/graph")
async def get_graph(pid: int):
    async with repo.db_context() as db:
        tasks = await repo.list_tasks(db, pid)
        deps = await repo.list_all_dependencies(db, pid)
    nodes = [
        {
            "id": t["id"],
            "key": t["key"],
            "title": t["title"],
            "status": t["status"],
            "readiness": t["readiness"],
            "on_critical_path": bool(t["on_critical_path"]),
        }
        for t in tasks
    ]
    edges = [
        {
            "id": d["id"],
            "upstream": d["upstream_task_id"],
            "downstream": d["downstream_task_id"],
            "type": d["type"],
            "source": d["source"],
            "state": d["state"],
            "confidence": d["confidence"],
            "reason": d.get("reason"),
        }
        for d in deps
    ]
    return {"nodes": nodes, "edges": edges}
