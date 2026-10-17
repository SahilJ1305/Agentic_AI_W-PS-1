"""Scheduler: check-ins, the escalation ladder, and the daily digest."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.core.checkins import queue_checkins
from app.core.escalation import run_escalations
from app.core.reports import generate_report
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
    try:
        scheduler.add_job(
            run_digests_all,
            CronTrigger.from_crontab(settings.digest_cron, timezone=settings.timezone),
            id="digest",
            replace_existing=True,
        )
    except Exception:
        log.exception("Digest cron %r was not scheduled", settings.digest_cron)
    scheduler.add_job(
        run_escalation_pass,
        IntervalTrigger(seconds=15 if settings.demo_mode else 60),
        id="escalations",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_lead_summaries,
        IntervalTrigger(seconds=15 if settings.demo_mode else 60),
        id="lead_summaries",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("Scheduler started (follow-ups: %s, digest: %s)", settings.followup_cron, settings.digest_cron)
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


async def run_escalation_pass() -> dict:
    """Nudge silent people and escalate stale blockers across active projects."""
    totals = {"nudges": 0, "silence_alerts": 0, "blocker_reminders": 0, "blocker_alerts": 0}
    try:
        async with repo.db_context() as db:
            totals = await run_escalations(db)
    except Exception:
        log.exception("Escalation pass failed")
    if any(totals.values()):
        log.info("Escalations: %s", totals)
    return totals


async def run_digests_all() -> int:
    """Post the digest for every active project (to the group chat and the lead)."""
    async with repo.db_context() as db:
        cursor = await db.execute("SELECT id FROM projects WHERE status = 'active' ORDER BY id")
        project_ids = [row["id"] for row in await cursor.fetchall()]
    posted = 0
    for project_id in project_ids:
        try:
            async with repo.db_context() as db:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                report = await generate_report(db, project_id, "digest", post=True, dedupe=today)
            posted += report["posted"]
        except Exception:
            log.exception("Digest failed for project %s", project_id)
    log.info("Digests posted for %d project(s)", posted)
    return posted


async def run_lead_summaries() -> int:
    """Send each lead their team summary once their /update_every interval has passed. Returns summaries queued."""
    from datetime import timedelta

    from app.core.reports import lead_summary
    from app.core.timeutil import parse_ts

    now = datetime.now(timezone.utc)
    queued = 0
    async with repo.db_context() as db:
        cursor = await db.execute("SELECT id FROM projects WHERE status = 'active' ORDER BY id")
        project_ids = [row["id"] for row in await cursor.fetchall()]
    for project_id in project_ids:
        try:
            async with repo.db_context() as db:
                saved = await repo.get_project_settings(db, project_id)
                every = float(saved.get("lead_summary_every_h", settings.lead_summary_every_h) or 0)
                leads = [
                    p for p in await repo.list_participants(db, project_id)
                    if p.get("role") == "lead" and p.get("telegram_chat_id")
                    and not ((parse_ts(p.get("paused_until")) or now) > now)        # /pause holds the summary too
                ]
                if not every or not leads:
                    continue
                last = parse_ts(saved.get("lead_summary_at"))
                if last is None:
                    await repo.update_project_settings(db, project_id, lead_summary_at=now.isoformat())
                    continue
                if now - last < timedelta(hours=every):
                    continue
                text = await lead_summary(db, project_id, now)
                for lead in leads if text else []:
                    await repo.enqueue_message(
                        db, participant_id=lead["id"], project_id=project_id, chat_id=lead["telegram_chat_id"],
                        template_key="LEAD_SUMMARY", text=text[:4000], now=now.isoformat(),
                    )
                    queued += 1
        except Exception:
            log.exception("Lead summary failed for project %s", project_id)
    return queued


async def run_nudge_checks() -> dict:
    """Fast-forward hook used by POST /api/admin/tick: run due check-ins and escalations now."""
    await run_checkins_all()
    return await run_escalation_pass()
