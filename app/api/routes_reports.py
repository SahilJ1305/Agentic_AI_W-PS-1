"""
app/api/routes_reports.py — reports, the living task doc, the message log and
manual dependency edits (spec §12.1).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.api.auth import CurrentUser, current_user, visible_project
from app.api.sse import broadcaster
from app.core.dependency_engine import compute_critical_path, recompute_all_readiness
from app.core.reports import build_export_md, generate_report
from app.db import repo

router = APIRouter(tags=["reports"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── reports ───────────────────────────────────────────────────────────────────

@router.post("/projects/{pid}/reports/{kind}")
async def create_report(pid: int, kind: str, post: bool = False, user: CurrentUser = Depends(current_user)):
    """Generate a digest or risk report. With ?post=true it also goes to Telegram."""
    if kind not in ("digest", "risk"):
        raise HTTPException(400, "kind must be 'digest' or 'risk'")
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        return await generate_report(db, pid, kind, post=post)


@router.get("/projects/{pid}/reports/latest")
async def latest_report(pid: int, kind: str = "digest", user: CurrentUser = Depends(current_user)):
    if kind not in ("digest", "risk"):
        raise HTTPException(400, "kind must be 'digest' or 'risk'")
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        row = await repo.get_latest_report(db, pid, kind)
    if not row:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "content_md": row["content_md"],
        "posted": bool(row.get("posted_message_id")),
        "created_at": row["created_at"],
    }


@router.get("/projects/{pid}/export.md", response_class=PlainTextResponse)
async def export_markdown(pid: int, user: CurrentUser = Depends(current_user)):
    async with repo.db_context() as db:
        project = await visible_project(db, pid, user)
        body = await build_export_md(db, pid)
    filename = "".join(c if c.isalnum() else "-" for c in project["name"]).strip("-").lower() or "project"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}-status.md"'},
    )


# ── conversation log ──────────────────────────────────────────────────────────

@router.get("/projects/{pid}/messages")
async def list_messages(
    pid: int,
    participant_id: int | None = None,
    limit: int = 100,
    user: CurrentUser = Depends(current_user),
):
    async with repo.db_context() as db:
        await visible_project(db, pid, user)
        sql = (
            "SELECT m.*, p.name AS participant_name FROM messages m "
            "LEFT JOIN participants p ON p.id = m.participant_id WHERE m.project_id = ?"
        )
        params: list = [pid]
        if participant_id is not None:
            sql += " AND m.participant_id = ?"
            params.append(participant_id)
        sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = [dict(r) for r in await (await db.execute(sql, params)).fetchall()]
    result = []
    for m in rows:
        try:
            interpretation = json.loads(m["interpretation_json"]) if m.get("interpretation_json") else None
        except json.JSONDecodeError:
            interpretation = None
        result.append({
            "id": m["id"],
            "direction": m["direction"],
            "participant_id": m["participant_id"],
            "participant_name": m.get("participant_name"),
            "text": m["text"],
            "template_key": m.get("template_key"),
            "interpretation": interpretation,
            "created_at": m["created_at"],
        })
    return result


# ── dependency editing ────────────────────────────────────────────────────────

class CreateDependencyRequest(BaseModel):
    project_id: int
    upstream_key: str
    downstream_key: str
    type: str = "hard"
    reason: str | None = None


class PatchDependencyRequest(BaseModel):
    state: str | None = None
    type: str | None = None


def _reaches(edges: list[tuple[int, int]], start: int, goal: int) -> bool:
    graph: dict[int, list[int]] = defaultdict(list)
    for up, down in edges:
        graph[up].append(down)
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(graph[node])
    return False


async def _edge_payload(db, dep: dict) -> dict:
    up, down = await repo.get_task(db, dep["upstream_task_id"]), await repo.get_task(db, dep["downstream_task_id"])
    return {
        "id": dep["id"],
        "upstream": dep["upstream_task_id"],
        "downstream": dep["downstream_task_id"],
        "upstream_key": up["key"] if up else None,
        "downstream_key": down["key"] if down else None,
        "type": dep["type"],
        "source": dep["source"],
        "state": dep["state"],
        "confidence": dep["confidence"],
        "reason": dep.get("reason"),
    }


async def _refresh_graph(db, project_id: int, now: str) -> None:
    await recompute_all_readiness(project_id, db, now)
    await compute_critical_path(project_id, db, now)


async def _publish_edge(project_id: int, edge: dict) -> None:
    await broadcaster.publish("dependency.changed", {
        "project_id": project_id,
        "edge_id": edge["id"],
        "upstream_key": edge["upstream_key"],
        "downstream_key": edge["downstream_key"],
        "state": edge["state"],
        "source": edge["source"],
    })
    await broadcaster.publish("task.updated", {
        "project_id": project_id, "task_key": edge["downstream_key"], "reason": "dependency changed",
    })


@router.post("/dependencies")
async def create_dependency(req: CreateDependencyRequest, user: CurrentUser = Depends(current_user)):
    if req.type not in ("hard", "soft"):
        raise HTTPException(400, "type must be hard or soft")
    now = _now()
    async with repo.db_context() as db:
        await visible_project(db, req.project_id, user)
        up = await repo.get_task_by_key(db, req.project_id, req.upstream_key)
        down = await repo.get_task_by_key(db, req.project_id, req.downstream_key)
        if not up or not down:
            raise HTTPException(404, "Unknown task key")
        if up["id"] == down["id"]:
            raise HTTPException(400, "A task cannot depend on itself")
        existing = [
            (d["upstream_task_id"], d["downstream_task_id"])
            for d in await repo.list_all_dependencies(db, req.project_id) if d["state"] == "active"
        ]
        if _reaches(existing, down["id"], up["id"]):
            raise HTTPException(409, f"{req.downstream_key} already leads to {req.upstream_key}; that edge would create a cycle")
        await repo.create_dependency(
            db, project_id=req.project_id, upstream_task_id=up["id"], downstream_task_id=down["id"],
            type=req.type, source="manual", state="active", confidence=1.0,
            reason=req.reason or "Added by the lead", now=now,
        )
        dep = next(
            d for d in await repo.list_all_dependencies(db, req.project_id)
            if d["upstream_task_id"] == up["id"] and d["downstream_task_id"] == down["id"]
        )
        if dep["state"] != "active" or dep["type"] != req.type:
            await db.execute("UPDATE dependencies SET state = 'active', type = ? WHERE id = ?", (req.type, dep["id"]))
            dep = {**dep, "state": "active", "type": req.type}
        await repo.append_task_event(
            db, task_id=down["id"], event_type="dependency_added", new_value=up["key"],
            reason=req.reason or f"{user.email} added {up['key']} → {down['key']}", actor="lead", now=now,
        )
        await _refresh_graph(db, req.project_id, now)
        edge = await _edge_payload(db, dep)
    await _publish_edge(req.project_id, edge)
    return edge


async def _load_dep(db, dep_id: int, user: CurrentUser) -> dict:
    cur = await db.execute("SELECT * FROM dependencies WHERE id = ?", (dep_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Dependency not found")
    dep = dict(row)
    await visible_project(db, dep["project_id"], user)
    return dep


@router.patch("/dependencies/{dep_id}")
async def patch_dependency(dep_id: int, req: PatchDependencyRequest, user: CurrentUser = Depends(current_user)):
    if req.state not in (None, "proposed", "active", "rejected"):
        raise HTTPException(400, "state must be proposed, active or rejected")
    if req.type not in (None, "hard", "soft"):
        raise HTTPException(400, "type must be hard or soft")
    now = _now()
    async with repo.db_context() as db:
        dep = await _load_dep(db, dep_id, user)
        if req.state:
            await repo.update_dependency_state(db, dep_id, req.state)
        if req.type:
            await db.execute("UPDATE dependencies SET type = ? WHERE id = ?", (req.type, dep_id))
        dep = await _load_dep(db, dep_id, user)
        await _refresh_graph(db, dep["project_id"], now)
        edge = await _edge_payload(db, dep)
    await _publish_edge(dep["project_id"], edge)
    return edge


@router.delete("/dependencies/{dep_id}")
async def delete_dependency(dep_id: int, user: CurrentUser = Depends(current_user)):
    now = _now()
    async with repo.db_context() as db:
        dep = await _load_dep(db, dep_id, user)
        edge = await _edge_payload(db, dep)
        await db.execute("DELETE FROM dependencies WHERE id = ?", (dep_id,))
        await _refresh_graph(db, dep["project_id"], now)
    edge["state"] = "removed"
    await _publish_edge(dep["project_id"], edge)
    return {"status": "deleted", "id": dep_id}
