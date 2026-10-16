"""
app/api/routes_admin.py — admin and health endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import repo
from app.llm import ollama as _ollama
from app.llm import openai_compat as _opencode

router = APIRouter(tags=["admin"])
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health")
async def health():
    """Check DB, Telegram polling, Ollama, and OpenCode."""
    from app.config import settings

    result = {}

    # DB
    try:
        async with repo.db_context() as db:
            await db.execute("SELECT 1")
        result["db"] = "ok"
    except Exception as e:
        result["db"] = f"error: {e}"

    # Ollama
    try:
        models = await _ollama.list_models()
        result["ollama"] = {"status": "ok", "models": models}
    except Exception as e:
        result["ollama"] = {"status": "error", "detail": str(e)}

    # OpenCode
    if settings.opencode_api_key:
        try:
            models = await _opencode.list_models()
            result["opencode"] = {"status": "ok", "model_count": len(models)}
        except Exception as e:
            result["opencode"] = {"status": "error", "detail": str(e)}
    else:
        result["opencode"] = {"status": "not configured"}

    result["telegram"] = "polling"
    return result


class CheckinRequest(BaseModel):
    project_id: int
    task_keys: list[str] | None = None


@router.post("/admin/checkin")
async def run_checkin(req: CheckinRequest):
    """Manually trigger check-ins for a project."""
    now = _now()
    from app.config import settings
    from app.core.notifications import NotificationBatch

    async with repo.db_context() as db:
        tasks = await repo.list_tasks(db, req.project_id)
        participants = await repo.list_participants(db, req.project_id)
        participant_map = {p["id"]: p for p in participants}

        # Select chaseable tasks
        chaseable = [
            t for t in tasks
            if t["status"] in ("in_progress", "blocked")
            or (t["status"] == "pending" and t["readiness"] == "ready")
        ]
        if req.task_keys:
            chaseable = [t for t in chaseable if t["key"] in req.task_keys]

        # Group by owner
        by_owner: dict[int, list] = {}
        for t in chaseable:
            if t.get("owner_id"):
                by_owner.setdefault(t["owner_id"], []).append(t)

        sent = 0
        for owner_id, owner_tasks in by_owner.items():
            p = participant_map.get(owner_id)
            if not p or not p.get("telegram_chat_id"):
                continue

            batch = NotificationBatch()
            if len(owner_tasks) == 1:
                t = owner_tasks[0]
                batch.add(
                    participant_id=owner_id,
                    template_key="FOLLOWUP_SINGLE",
                    context={"task": t, "name": p["name"]},
                    dedupe_key=f"followup:{t['id']}:{now[:10]}",
                    question_kind="status_check",
                    question_task_id=t["id"],
                )
            else:
                batch.add(
                    participant_id=owner_id,
                    template_key="FOLLOWUP_MULTI",
                    context={
                        "name": p["name"],
                        "numbered_task_list": "\n".join(
                            f"{i+1}. {t['key']} · {t['title']}"
                            for i, t in enumerate(owner_tasks)
                        ),
                    },
                )
            await batch.flush(db, now=now)
            sent += len(owner_tasks)

    return {"status": "queued", "tasks_targeted": sent}


@router.post("/admin/tick")
async def tick():
    """Fast-forward scheduler (for demos)."""
    from app.scheduler.jobs import run_nudge_checks
    await run_nudge_checks()
    return {"status": "ticked"}


@router.post("/admin/reset-demo")
async def reset_demo():
    """Drop and reseed the FestPass demo project. Keeps telegram_chat_ids."""
    from app.db.seed_demo import seed
    await seed(force=True)
    return {"status": "reset"}
