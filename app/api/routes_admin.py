"""
app/api/routes_admin.py — admin and health endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import CurrentUser, current_user, visible_project
from app.db import repo
from app.llm import ollama as _ollama
from app.llm import openai_compat as _opencode

public_router = APIRouter(tags=["admin"])
router = APIRouter(tags=["admin"], dependencies=[Depends(current_user)])
log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@public_router.get("/health")
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

    result["llm_provider"] = settings.llm_provider
    if settings.llm_provider == "azure":
        configured = bool(settings.azure_ai_endpoint and settings.azure_ai_api_key)
        result["azure"] = {
            "status": "configured" if configured else "missing endpoint or key",
            "coordinator": settings.azure_coordinator_deployment or None,
            "planner": settings.azure_planner_deployment or None,
        }
    else:
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

    from app.telegram.gateway import telegram_status

    result["telegram"] = telegram_status()
    return result


class CheckinRequest(BaseModel):
    project_id: int
    task_keys: list[str] | None = None


@router.post("/admin/checkin")
async def run_checkin(req: CheckinRequest, user: CurrentUser = Depends(current_user)):
    """Manually trigger check-ins for a project. One message per owner."""
    from app.core.checkins import queue_checkins

    now = _now()
    async with repo.db_context() as db:
        await visible_project(db, req.project_id, user)
        sent = await queue_checkins(db, req.project_id, now, task_keys=req.task_keys)
    return {"status": "queued", "tasks_targeted": sent}


def _demo_only() -> None:
    from app.config import settings

    if not settings.demo_mode:
        raise HTTPException(403, "This is a demo-only action. Set DEMO_MODE=true to enable it.")


@router.post("/admin/tick")
async def tick():
    """Fast-forward scheduler (for demos)."""
    _demo_only()
    from app.scheduler.jobs import run_nudge_checks
    return {"status": "ticked", "escalations": await run_nudge_checks()}


@router.post("/admin/reset-demo")
async def reset_demo():
    """Drop and reseed the FestPass demo project. Keeps telegram_chat_ids."""
    _demo_only()
    from app.db.seed_demo import seed
    await seed(force=True)
    return {"status": "reset"}
