"""
app/core/escalation.py — silence and blocker escalation ladder (spec W10, G3.7).

Open question, no answer (N = NUDGE_AFTER_MIN; demo mode: 2 min):
    N    → NUDGE_1 to the person
    2N   → NUDGE_2 to the person, warning that the lead will be told
    3N   → ESCALATE_SILENCE to the lead; the question is marked escalated and
           the task is flagged `stale`

Open blocker (E = BLOCKER_ESCALATE_MIN; demo mode: 4 min):
    E    → BLOCKER_REMINDER to whoever can unblock it (owner of the linked task,
           or the named person); an external blocker goes straight to the lead
    2E   → BLOCKER_ESCALATED to the lead

Idempotent: each rung is guarded by a counter on the row and a dedupe key, so
running the pass every few seconds never repeats a message.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from app.api.sse import broadcaster
from app.config import settings
from app.core.notifications import NotificationBatch
from app.core.timeutil import parse_ts
from app.db import repo

log = logging.getLogger(__name__)


def _paused(person: dict, now: datetime) -> bool:
    until = parse_ts(person.get("paused_until"))
    return bool(until and until > now)


async def run_escalations(db: aiosqlite.Connection, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    result = {"nudges": 0, "silence_alerts": 0, "blocker_reminders": 0, "blocker_alerts": 0}
    await _silence_ladder(db, now, result)
    await _blocker_ladder(db, now, result)
    await db.commit()
    return result


# ── silence ───────────────────────────────────────────────────────────────────

async def _silence_ladder(db: aiosqlite.Connection, now: datetime, result: dict) -> None:
    step = settings.effective_nudge_after_min
    cur = await db.execute(
        """SELECT q.*, p.name AS person_name, p.project_id AS pid
           FROM pending_questions q
           JOIN participants p ON p.id = q.participant_id
           JOIN projects pr ON pr.id = p.project_id
           WHERE q.status = 'open' AND pr.status = 'active' AND p.telegram_chat_id IS NOT NULL
           ORDER BY q.created_at"""
    )
    for question in [dict(r) for r in await cur.fetchall()]:
        created = parse_ts(question["created_at"])
        person = await repo.get_participant(db, question["participant_id"])
        task = await repo.get_task(db, question["task_id"]) if question.get("task_id") else None
        if not created or not person or not task or task["status"] == "complete" or _paused(person, now):
            continue
        age_min = (now - created).total_seconds() / 60
        rung = question["nudge_count"]
        batch = NotificationBatch()
        ctx = {"task": task, "name": person["name"]}
        stamp = now.isoformat()

        if rung == 0 and age_min >= step:
            batch.add(participant_id=person["id"], template_key="NUDGE_1", context=ctx,
                      dedupe_key=f"nudge1:{question['id']}")
            await repo.increment_nudge_count(db, question["id"])
            result["nudges"] += 1
        elif rung == 1 and age_min >= 2 * step:
            lead = await repo.get_lead(db, question["pid"])
            batch.add(participant_id=person["id"], template_key="NUDGE_2",
                      context={**ctx, "lead": (lead or {}).get("name", "the lead"), "minutes": max(1, round(step))},
                      dedupe_key=f"nudge2:{question['id']}")
            await repo.increment_nudge_count(db, question["id"])
            result["nudges"] += 1
        elif rung >= 2 and age_min >= 3 * step:
            lead = await repo.get_lead(db, question["pid"])
            await repo.escalate_question(db, question["id"])
            await _flag(db, task, "stale", "No reply after 2 reminders", stamp)
            if lead and lead["id"] != person["id"]:
                batch.add(participant_id=lead["id"], template_key="ESCALATE_SILENCE",
                          context={**ctx, "lead": lead["name"]},
                          dedupe_key=f"escalate:{question['id']}")
            result["silence_alerts"] += 1
            await broadcaster.publish("task.updated", {
                "project_id": question["pid"], "task_key": task["key"], "status": task["status"],
                "flags": json.loads((await repo.get_task(db, task["id"]))["flags_json"] or "[]"),
                "reason": "No reply after 2 reminders", "rule_fired": "W10 escalation",
            })
        await batch.flush(db, now=stamp)


# ── blockers ──────────────────────────────────────────────────────────────────

async def _blocker_ladder(db: aiosqlite.Connection, now: datetime, result: dict) -> None:
    step = settings.effective_blocker_escalate_min
    cur = await db.execute(
        """SELECT b.*, t.project_id AS pid FROM blockers b
           JOIN tasks t ON t.id = b.task_id
           JOIN projects pr ON pr.id = t.project_id
           WHERE b.status = 'open' AND b.escalation_level < 2 AND pr.status = 'active'"""
    )
    for blocker in [dict(r) for r in await cur.fetchall()]:
        raised = parse_ts(blocker["raised_at"])
        if not raised:
            continue
        age_min = (now - raised).total_seconds() / 60
        level = blocker["escalation_level"]
        task = await repo.get_task(db, blocker["task_id"])
        owner = await repo.get_participant(db, task["owner_id"]) if task and task.get("owner_id") else None
        lead = await repo.get_lead(db, blocker["pid"])
        batch = NotificationBatch()
        stamp = now.isoformat()
        base = {"task": task, "blocker": blocker, "reporter": (owner or {}).get("name", "The owner")}

        if level == 0 and age_min >= step:
            unblocker = await _unblocker(db, blocker)
            if unblocker and unblocker["id"] != (owner or {}).get("id"):
                upstream = await repo.get_task(db, blocker["linked_task_id"]) if blocker.get("linked_task_id") else None
                batch.add(participant_id=unblocker["id"], template_key="BLOCKER_REMINDER",
                          context={**base, "unblocker": unblocker["name"], "upstream_task": upstream or {}},
                          dedupe_key=f"blocker-remind:{blocker['id']}")
                result["blocker_reminders"] += 1
            elif lead:
                batch.add(participant_id=lead["id"], template_key="BLOCKER_ESCALATED",
                          context={**base, "minutes": round(age_min)},
                          dedupe_key=f"blocker-escalate:{blocker['id']}:1")
                result["blocker_alerts"] += 1
            await _set_level(db, blocker["id"], 1)
        elif level == 1 and age_min >= 2 * step:
            if lead:
                batch.add(participant_id=lead["id"], template_key="BLOCKER_ESCALATED",
                          context={**base, "minutes": round(age_min)},
                          dedupe_key=f"blocker-escalate:{blocker['id']}:2")
                result["blocker_alerts"] += 1
            await _set_level(db, blocker["id"], 2)
        await batch.flush(db, now=stamp)


async def _unblocker(db: aiosqlite.Connection, blocker: dict) -> dict | None:
    if blocker.get("linked_participant_id"):
        return await repo.get_participant(db, blocker["linked_participant_id"])
    if blocker.get("linked_task_id"):
        linked = await repo.get_task(db, blocker["linked_task_id"])
        if linked and linked.get("owner_id"):
            return await repo.get_participant(db, linked["owner_id"])
    return None


async def _set_level(db: aiosqlite.Connection, blocker_id: int, level: int) -> None:
    await db.execute("UPDATE blockers SET escalation_level = ? WHERE id = ?", (level, blocker_id))


async def _flag(db: aiosqlite.Connection, task: dict, flag: str, reason: str, now: str) -> None:
    fresh = await repo.get_task(db, task["id"])
    flags = json.loads(fresh.get("flags_json") or "[]")
    if flag in flags:
        return
    flags.append(flag)
    await db.execute("UPDATE tasks SET flags_json = ? WHERE id = ?", (json.dumps(flags), task["id"]))
    await repo.append_task_event(
        db, task_id=task["id"], event_type="flagged", new_value=flag, reason=reason, actor="system", now=now,
    )
