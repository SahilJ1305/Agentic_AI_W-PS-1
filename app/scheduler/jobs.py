"""Check-in schedule. Nudges, escalations and digests are Tier 3."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.core.checkins import queue_checkins
from app.db import repo

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    try:
        scheduler.add_job(
            run_checkins_all,
            CronTrigger.from_crontab(settings.followup_cron, timezone=settings.timezone),
            id="followups",
            replace_existing=True,
        )
    except Exception:
        log.exception("Follow-up cron %r was not scheduled", settings.followup_cron)
    scheduler.start()
    _scheduler = scheduler
    log.info("Scheduler started (follow-ups: %s)", settings.followup_cron)
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


async def run_checkins_all() -> int:
    """Send check-ins for every active project. Returns tasks covered."""
    now = datetime.now(timezone.utc).isoformat()
    async with repo.db_context() as db:
        cursor = await db.execute(
            "SELECT id FROM projects WHERE status = 'active' ORDER BY id"
        )
        project_ids = [row["id"] for row in await cursor.fetchall()]

    targeted = 0
    for project_id in project_ids:
        async with repo.db_context() as db:
            targeted += await queue_checkins(db, project_id, now)
    log.info("Check-ins queued for %d task(s)", targeted)
    return targeted


async def run_nudge_checks() -> None:
    """Fast-forward hook used by POST /api/admin/tick. Runs check-ins now."""
    await run_checkins_all()
