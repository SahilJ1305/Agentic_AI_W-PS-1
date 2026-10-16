"""
app/telegram/router.py — per-user lock, debounce, context packet assembly.

For each incoming message:
  1. Acquire per-user asyncio.Lock (no parallel processing for same sender).
  2. Buffer messages for DEBOUNCE_S seconds (people often type in bursts).
  3. Build context packet (sender tasks, pending question, recent history, task index).
  4. Call Coordinator Agent.
  5. Run Policy Engine.
  6. Execute approved updates (DB writes + event log).
  7. Trigger dependency propagation.
  8. Flush notification batch → outbox.
  9. Publish SSE events.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiosqlite

from app.agents.coordinator import run_coordinator
from app.config import settings
from app.core.dependency_engine import on_blocker_raised, on_task_completed
from app.core.notifications import NotificationBatch
from app.core.policy import apply as policy_apply
from app.db import repo
from app.llm.gateway import LLMFailure

log = logging.getLogger(__name__)

# Per-user lock registry
_user_locks: dict[int, asyncio.Lock] = {}

# Debounce buffers: participant_id → list of (text, tg_msg_id)
_debounce_buffers: dict[int, list[tuple[str, int]]] = {}
_debounce_tasks: dict[int, asyncio.Task] = {}


def _get_lock(participant_id: int) -> asyncio.Lock:
    if participant_id not in _user_locks:
        _user_locks[participant_id] = asyncio.Lock()
    return _user_locks[participant_id]


async def handle_message(
    *,
    participant_id: int,
    project_id: int,
    text: str,
    telegram_message_id: int,
    sse_publish,           # callable(event, payload) from app/api/sse.py
) -> None:
    """
    Entry point from the Telegram gateway.
    Adds the message to the debounce buffer and schedules processing.
    """
    buf = _debounce_buffers.setdefault(participant_id, [])
    buf.append((text, telegram_message_id))

    # Cancel existing debounce task if any
    existing = _debounce_tasks.get(participant_id)
    if existing and not existing.done():
        existing.cancel()

    # Schedule processing after DEBOUNCE_S
    task = asyncio.create_task(
        _debounce_then_process(
            participant_id=participant_id,
            project_id=project_id,
            sse_publish=sse_publish,
        )
    )
    _debounce_tasks[participant_id] = task


async def _debounce_then_process(
    *,
    participant_id: int,
    project_id: int,
    sse_publish,
) -> None:
    try:
        await asyncio.sleep(settings.debounce_s)
    except asyncio.CancelledError:
        return  # new message arrived, cancelled

    # Drain buffer
    buf = _debounce_buffers.pop(participant_id, [])
    if not buf:
        return

    burst_text = "\n".join(text for text, _ in buf)
    last_tg_id = buf[-1][1]

    async with _get_lock(participant_id):
        await _process_burst(
            participant_id=participant_id,
            project_id=project_id,
            burst_text=burst_text,
            last_telegram_message_id=last_tg_id,
            sse_publish=sse_publish,
        )


async def _process_burst(
    *,
    participant_id: int,
    project_id: int,
    burst_text: str,
    last_telegram_message_id: int,
    sse_publish,
) -> None:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    async with repo.db_context() as db:
        # ── Save inbound message ──────────────────────────────────────────────
        sender = await repo.get_participant(db, participant_id)
        if not sender:
            log.warning("Message from unknown participant_id=%d", participant_id)
            return

        await repo.touch_participant(db, participant_id, last_seen_at=now)

        msg_id = await repo.save_message(
            db,
            project_id=project_id,
            participant_id=participant_id,
            direction="in",
            telegram_message_id=last_telegram_message_id,
            text=burst_text,
            now=now,
        )
        await sse_publish("message.in", {
            "participant": sender["name"],
            "text": burst_text[:100],
        })

        # ── Build context packet ──────────────────────────────────────────────
        sender_tasks = await repo.list_tasks_for_owner(db, participant_id)
        open_pq = await repo.get_open_question(db, participant_id)
        recent = await repo.list_recent_messages(db, participant_id, limit=6)

        all_tasks = await repo.list_tasks(db, project_id)
        task_index = [t for t in all_tasks if t.get("owner_id") != participant_id]

        # Enrich sender_tasks with blocker description
        enriched_sender_tasks = []
        for t in sender_tasks:
            row = dict(t)
            if t["status"] == "blocked":
                blockers = await repo.list_open_blockers_for_task(db, t["id"])
                row["blocker_desc"] = blockers[0]["description"] if blockers else ""
            enriched_sender_tasks.append(row)

        # ── Coordinator Agent ─────────────────────────────────────────────────
        try:
            interpretation = await run_coordinator(
                now=now,
                sender_name=sender["name"],
                pending_question=open_pq,
                sender_tasks=enriched_sender_tasks,
                task_index=task_index,
                recent_messages=recent,
                message_text=burst_text,
                db=db,
            )
        except LLMFailure as e:
            log.error("LLM failure for participant=%d: %s", participant_id, e)
            # R15 fallback: send buttons for most likely task
            if sender_tasks:
                notification = NotificationBatch()
                notification.add(
                    participant_id=participant_id,
                    template_key="NOT_UNDERSTOOD",
                    context={"task_title": sender_tasks[0]["title"]},
                    question_kind="clarify_status",
                    question_task_id=sender_tasks[0]["id"],
                )
                await notification.flush(db, now=now, source_msg_id=msg_id)
            return

        # Update message with interpretation JSON
        await db.execute(
            "UPDATE messages SET interpretation_json = ? WHERE id = ?",
            (interpretation.model_dump_json(), msg_id),
        )

        await sse_publish("interpretation", {
            "message_id": msg_id,
            "intent": interpretation.intent,
            "updates": [u.model_dump() for u in interpretation.updates],
        })

        # ── Policy Engine ─────────────────────────────────────────────────────
        decision = await policy_apply(
            interpretation=interpretation,
            sender=sender,
            project_id=project_id,
            source_message_id=msg_id,
            db=db,
            now=now,
        )

        await sse_publish("interpretation", {
            "message_id": msg_id,
            "intent": interpretation.intent,
            "decision": decision.rule_log,
            "updates": [u.task_key for u in decision.approved],
        })

        # ── Close pending question if answered ────────────────────────────────
        if open_pq and (decision.approved or decision.clarifications == []):
            await repo.close_question(db, open_pq["id"], answered_at=now)

        # ── Execute approved updates ──────────────────────────────────────────
        for upd in decision.approved:
            await _execute_update(upd, project_id, participant_id, msg_id, db, now, sse_publish)

        # ── Flush notification batch ──────────────────────────────────────────
        await decision.notifications.flush(db, now=now, source_msg_id=msg_id)


async def _execute_update(upd, project_id, participant_id, msg_id, db, now, sse_publish):
    """Write an approved update to the DB and trigger propagation."""
    from app.core.policy import ApprovedUpdate  # avoid circular at module level

    task = await repo.get_task(db, upd.task_id)
    if not task:
        return

    flags = json.loads(task.get("flags_json") or "[]")
    for f in upd.flags_to_add:
        if f not in flags:
            flags.append(f)

    completion_at = now if upd.new_status == "complete" else None
    last_reply_at = now

    if upd.new_status is not None:
        ok = await repo.update_task_status(
            db,
            upd.task_id,
            status=upd.new_status,
            progress_note=upd.progress_note,
            eta=upd.eta,
            completion_evidence=upd.completion_evidence,
            flags_json=json.dumps(flags),
            completed_at=completion_at,
            last_reply_at=last_reply_at,
            updated_at=now,
        )
    else:
        # Note only — no status change
        ok = await repo.update_task_status(
            db,
            upd.task_id,
            status=task["status"],
            progress_note=upd.progress_note,
            eta=upd.eta,
            flags_json=json.dumps(flags),
            last_reply_at=last_reply_at,
            updated_at=now,
        )

    if not ok:
        log.warning("Version conflict on task %s — skipping", upd.task_key)
        return

    # Audit event
    if upd.new_status and upd.new_status != upd.old_status:
        event_id = await repo.append_task_event(
            db,
            task_id=upd.task_id,
            event_type="status_changed",
            old_value=upd.old_status,
            new_value=upd.new_status,
            reason=upd.reason,
            actor="coordinator",
            source_message_id=msg_id,
            confidence=upd.confidence,
            now=now,
        )

    # Handle blocker
    if upd.blocker_description and upd.new_status == "blocked":
        blocker_id = await repo.create_blocker(
            db,
            task_id=upd.task_id,
            description=upd.blocker_description,
            kind=upd.blocker_kind or "external",
            linked_task_id=upd.blocker_linked_task_id,
            linked_participant_id=upd.blocker_linked_participant_id,
            raised_message_id=msg_id,
            now=now,
        )
        await repo.append_task_event(
            db,
            task_id=upd.task_id,
            event_type="blocker_raised",
            new_value=upd.blocker_description,
            reason=upd.reason,
            actor="coordinator",
            source_message_id=msg_id,
            now=now,
        )

        # Runtime edge (R11)
        if upd.blocker_linked_task_id:
            await repo.create_dependency(
                db,
                project_id=project_id,
                upstream_task_id=upd.blocker_linked_task_id,
                downstream_task_id=upd.task_id,
                type="hard",
                source="runtime",
                state="active",
                confidence=0.9,
                reason=upd.blocker_description,
                created_by_message_id=msg_id,
                now=now,
            )
            await sse_publish("dependency.changed", {
                "upstream_task_id": upd.blocker_linked_task_id,
                "downstream_task_id": upd.task_id,
                "source": "runtime",
                "state": "active",
            })

        # Propagate blocker
        batch = await on_blocker_raised(blocker_id, db, now)
        await batch.flush(db, now=now, source_msg_id=msg_id)

    # Handle blocker resolved
    if upd.blocker_resolved:
        for blocker in await repo.list_open_blockers_for_task(db, upd.task_id):
            await repo.resolve_blocker(db, blocker["id"], resolved_message_id=msg_id, resolved_at=now)
            await repo.append_task_event(
                db,
                task_id=upd.task_id,
                event_type="blocker_resolved",
                old_value=blocker["description"],
                reason="Owner reported blocker resolved",
                actor="coordinator",
                source_message_id=msg_id,
                now=now,
            )
            await sse_publish("blocker.resolved", {"task_id": upd.task_id})

    # Dependency propagation on completion
    if upd.new_status == "complete" and upd.old_status != "complete":
        batch = await on_task_completed(upd.task_id, msg_id, db, now)
        await batch.flush(db, now=now, source_msg_id=msg_id)

    await sse_publish("task.updated", {
        "task_key": upd.task_key,
        "status": upd.new_status or task["status"],
        "changed_fields": ["status"] if upd.new_status else ["progress_note"],
        "reason": upd.reason,
        "rule_fired": upd.rule_fired,
    })
