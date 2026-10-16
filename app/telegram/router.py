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
import re
from datetime import datetime, timezone

import aiosqlite

from app.agents.coordinator import run_coordinator
from app.agents.fastpath import quick_interpretation
from app.config import settings
from app.core.dependency_engine import on_blocker_raised, on_task_completed
from app.core.notifications import NotificationBatch
from app.core.policy import apply as policy_apply
from app.db import repo
from app.llm.gateway import LLMFailure
from app.tools.git_checker import verify_updates

log = logging.getLogger(__name__)

_BARE_DONE = re.compile(
    r"^(done+|ho gaya|hogaya|ho gya|hogya|ho gaya bhai|hogaya bhai)[\s!.]*$",
    re.IGNORECASE,
)

# Per-user lock registry
_user_locks: dict[int, asyncio.Lock] = {}

# Debounce buffers: participant_id → list of (text, tg_msg_id)
_debounce_buffers: dict[int, list[tuple[str, int]]] = {}
_debounce_tasks: dict[int, asyncio.Task] = {}


def _tagged(sse_publish, project_id: int):
    """Wrap an SSE publisher so every event says which project it belongs to."""
    async def publish(event: str, payload: dict) -> None:
        await sse_publish(event, {"project_id": project_id, **payload})
    return publish


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
    sse_publish = _tagged(sse_publish, project_id)
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
        await db.commit()
        await sse_publish("message.in", {
            "message_id": msg_id,
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

        open_tasks = [t for t in enriched_sender_tasks if t["status"] != "complete"]
        if not open_pq and len(open_tasks) > 1 and _BARE_DONE.match(burst_text.strip()):
            log.info("Ambiguous done from %s across %d tasks", sender["name"], len(open_tasks))
            batch = NotificationBatch()
            batch.add(
                participant_id=participant_id,
                template_key="CLARIFY_TASK",
                context={"tasks": open_tasks, "_source_text": burst_text},
                question_kind="clarify_task",
            )
            await batch.flush(db, now=now, source_msg_id=msg_id)
            await db.commit()
            await sse_publish("interpretation", {
                "message_id": msg_id,
                "intent": "status_update",
                "decision": ["G2.2: bare done with several open tasks → CLARIFY_TASK"],
                "updates": [],
            })
            return

        # ── Coordinator Agent (skipped for unambiguous one-word replies) ───────
        fast = quick_interpretation(
            burst_text, sender_tasks=enriched_sender_tasks, pending_question=open_pq,
        )
        try:
            if fast is not None:
                interpretation = fast
                interpretation.raw_message = burst_text
            else:
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

        await db.commit()
        await sse_publish("interpretation", {
            "message_id": msg_id,
            "intent": interpretation.intent,
            "updates": [u.model_dump() for u in interpretation.updates],
        })

        # ── Git claim checker: look for the sender's commit/PR behind "done" ──
        verifications = await verify_updates(
            interpretation,
            sender=sender,
            sender_tasks=sender_tasks,
            open_question=open_pq,
        )

        # ── Policy Engine ─────────────────────────────────────────────────────
        decision = await policy_apply(
            interpretation=interpretation,
            sender=sender,
            project_id=project_id,
            source_message_id=msg_id,
            db=db,
            now=now,
            verifications=verifications,
        )

        if fast is not None:
            decision.rule_log.insert(0, "Fast path: a plain one-word status, so no AI call was needed")
        await db.commit()
        await sse_publish("interpretation", {
            "message_id": msg_id,
            "intent": interpretation.intent,
            "decision": decision.rule_log,
            "updates": [u.task_key for u in decision.approved],
            "git_checks": {key: v.model_dump(mode="json") for key, v in verifications.items()},
        })

        if decision.revert:
            await _revert_latest(
                db,
                sender,
                now=now,
                reason=burst_text,
                sse_publish=sse_publish,
            )
            await db.commit()
            return

        # ── Close pending question if answered ────────────────────────────────
        if open_pq and decision.approved:
            await repo.close_question(db, open_pq["id"], answered_at=now)

        # ── Execute approved updates ──────────────────────────────────────────
        for upd in decision.approved:
            await _execute_update(upd, project_id, participant_id, msg_id, db, now, sse_publish)

        # ── Flush notification batch ──────────────────────────────────────────
        await decision.notifications.flush(db, now=now, source_msg_id=msg_id)


async def _revert_latest(db, sender: dict, *, now: str, reason: str, sse_publish) -> str:
    """Undo the sender's newest status change inside UNDO_WINDOW_MIN."""
    tasks = await repo.list_tasks_for_owner(db, sender["id"])
    last_event = None
    last_task = None
    for task in tasks:
        event = await repo.get_latest_event(db, task["id"], actor="coordinator")
        if event and event["event_type"] == "status_changed" and not event.get("reverted_by_event_id"):
            if last_event is None or event["created_at"] > last_event["created_at"]:
                last_event = event
                last_task = task
    if not last_event or not last_task or not last_event.get("old_value"):
        return "Nothing to undo."

    event_dt = datetime.fromisoformat(last_event["created_at"])
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)
    age_min = (datetime.now(timezone.utc) - event_dt).total_seconds() / 60
    if age_min > settings.undo_window_min:
        return f"Undo window ({settings.undo_window_min} min) expired."

    restored = last_event["old_value"]
    await repo.update_task_status(db, last_task["id"], status=restored, updated_at=now)
    revert_id = await repo.append_task_event(
        db,
        task_id=last_task["id"],
        event_type="reverted",
        old_value=last_event["new_value"],
        new_value=restored,
        reason=reason,
        actor="coordinator",
        now=now,
    )
    await repo.mark_event_reverted(db, last_event["id"], revert_event_id=revert_id)
    await recompute_readiness_quietly(db, last_task["project_id"], now)
    if last_event["new_value"] == "complete" and restored != "complete":
        await _notify_reopened(db, last_task, reason, now)
    await sse_publish("task.updated", {
        "task_key": last_task["key"],
        "status": restored,
        "reason": reason,
        "rule_fired": "undo",
    })
    return f"Undone: {last_task['title']} is back to {restored}."


async def recompute_readiness_quietly(db, project_id: int, now: str) -> None:
    from app.core.dependency_engine import recompute_all_readiness
    await recompute_all_readiness(project_id, db, now)


async def _notify_reopened(db, task: dict, reason: str, now: str) -> None:
    downstream = await repo.list_dependencies_upstream(db, task["id"], state="active")
    batch = NotificationBatch()
    for edge in downstream:
        if edge["type"] != "hard":
            continue
        down = await repo.get_task(db, edge["downstream_task_id"])
        if not down or not down.get("owner_id"):
            continue
        batch.add(
            participant_id=down["owner_id"],
            template_key="REOPENED_ALERT",
            context={
                "upstream_task": task,
                "task": down,
                "reason": reason,
            },
        )
    await batch.flush(db, now=now)


async def apply_explicit_status(
    *,
    participant_id: int,
    project_id: int,
    task_key: str,
    status: str,
    text: str,
    telegram_message_id: int,
    sse_publish,
    blocker_description: str | None = None,
    blocker_resolved: bool = False,
    confirmed: frozenset[str] = frozenset(),
    question_id: int | None = None,
) -> str | None:
    """
    Apply a button or slash-command status through the Policy Engine, skipping the LLM.

    `confirmed` lists rules the person just said yes to ("R6" it works end to end, "R8" reopen);
    `question_id` is the pending question the button belonged to, closed once the update lands.
    """
    from app.agents.schemas import BlockerOut, Interpretation, TaskUpdate

    sse_publish = _tagged(sse_publish, project_id)
    now = datetime.now(timezone.utc).isoformat()
    blocker = None
    if status == "blocked" and blocker_description:
        blocker = BlockerOut(description=blocker_description, kind="external", match_confidence=1.0)
    interpretation = Interpretation(
        intent="blocker_report" if status == "blocked" else "status_update",
        updates=[TaskUpdate(
            task_key=task_key,
            task_match_confidence=1.0,
            status=status,  # type: ignore[arg-type]
            status_confidence=1.0,
            blocker=blocker,
            blocker_resolved=blocker_resolved,
            evidence=text,
        )],
        raw_message=text,
    )
    async with repo.db_context() as db:
        sender = await repo.get_participant(db, participant_id)
        if not sender:
            return "You're not in this project."
        task = await repo.get_task_by_key(db, project_id, task_key)
        if not task or task.get("owner_id") != participant_id:
            return f"Task {task_key} not found or not yours."
        msg_id = await repo.save_message(
            db,
            project_id=project_id,
            participant_id=participant_id,
            direction="in",
            telegram_message_id=telegram_message_id,
            text=text,
            now=now,
        )
        verifications = await verify_updates(
            interpretation,
            sender=sender,
            sender_tasks=await repo.list_tasks_for_owner(db, participant_id),
        )
        decision = await policy_apply(
            interpretation=interpretation,
            sender=sender,
            project_id=project_id,
            source_message_id=msg_id,
            db=db,
            now=now,
            verifications=verifications,
            confirmed=confirmed,
        )
        open_pq = (
            await repo.get_question(db, question_id) if question_id
            else await repo.get_open_question(db, participant_id)
        )
        if open_pq and open_pq["status"] == "open" and decision.approved:
            await repo.close_question(db, open_pq["id"], answered_at=now)
        for upd in decision.approved:
            await _execute_update(upd, project_id, participant_id, msg_id, db, now, sse_publish)
        await decision.notifications.flush(db, now=now, source_msg_id=msg_id)
        await db.commit()
    # Success, a clarifying question and the acknowledgement all reach the person through the
    # outbox. Replying here as well is what made /done answer twice.
    if decision.approved or decision.clarifications or decision.notifications._messages:
        return None
    return f"No change recorded for {task_key}."


async def _acknowledge(upd, task: dict, db, now: str, msg_id: int | None) -> None:
    """Confirm the new status to the person who reported it (completion is acknowledged by the engine)."""
    if not upd.new_status or upd.new_status == upd.old_status or not task.get("owner_id"):
        return
    batch = NotificationBatch()
    if upd.new_status == "in_progress":
        batch.add(participant_id=task["owner_id"], template_key="ACK_PROGRESS", context={"task": task})
    elif upd.new_status == "blocked":
        routing = "I'll flag it to the lead."
        if upd.blocker_linked_task_id:
            linked = await repo.get_task(db, upd.blocker_linked_task_id)
            helper = await repo.get_participant(db, linked["owner_id"]) if linked and linked.get("owner_id") else None
            if helper:
                routing = f"I've asked {helper['name']}."
        elif upd.blocker_linked_participant_id:
            helper = await repo.get_participant(db, upd.blocker_linked_participant_id)
            if helper:
                routing = f"I've asked {helper['name']}."
        batch.add(
            participant_id=task["owner_id"],
            template_key="ACK_BLOCKED",
            context={
                "task": task,
                "blocker": {"description": upd.blocker_description or "no reason given"},
                "routing_part": routing,
            },
        )
    await batch.flush(db, now=now, source_msg_id=msg_id)


async def _execute_update(upd, project_id, participant_id, msg_id, db, now, sse_publish):
    """Write an approved update to the DB and trigger propagation."""
    task = await repo.get_task(db, upd.task_id)
    if not task:
        return

    flags = json.loads(task.get("flags_json") or "[]")
    for f in upd.flags_to_add:
        if f not in flags:
            flags.append(f)
    flags = [f for f in flags if f not in upd.flags_to_remove]

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
            verified=upd.verified,
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

    # Audit event — every status change and every note-only update.
    event_id = None
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
    elif upd.progress_note or upd.eta:
        event_id = await repo.append_task_event(
            db,
            task_id=upd.task_id,
            event_type="note_added",
            new_value=upd.progress_note or upd.eta,
            reason=upd.reason,
            actor="coordinator",
            source_message_id=msg_id,
            confidence=upd.confidence,
            now=now,
        )

    if upd.verified:
        verified_event_id = await repo.append_task_event(
            db,
            task_id=upd.task_id,
            event_type="verified",
            new_value=upd.completion_evidence,
            reason=upd.reason,
            actor="engine",
            source_message_id=msg_id,
            now=now,
        )
        event_id = event_id or verified_event_id

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

        await db.commit()
        await sse_publish("blocker.raised", {
            "blocker_id": blocker_id,
            "task_key": upd.task_key,
            "description": upd.blocker_description,
            "kind": upd.blocker_kind or "external",
        })

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
            await db.commit()
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
            await sse_publish("blocker.resolved", {
                "blocker_id": blocker["id"], "task_id": upd.task_id, "task_key": upd.task_key,
            })

    # Completing a task closes the blocker that was holding it.
    if upd.new_status == "complete" and upd.old_status != "complete":
        for blocker in await repo.list_open_blockers_for_task(db, upd.task_id):
            await repo.resolve_blocker(db, blocker["id"], resolved_message_id=msg_id, resolved_at=now)
            await repo.append_task_event(
                db,
                task_id=upd.task_id,
                event_type="blocker_resolved",
                old_value=blocker["description"],
                reason="Owner reported the task complete",
                actor="coordinator",
                source_message_id=msg_id,
                now=now,
            )
        batch = await on_task_completed(upd.task_id, msg_id, db, now)
        await batch.flush(db, now=now, source_msg_id=msg_id)

    fresh = await repo.get_task(db, upd.task_id)
    await _acknowledge(upd, fresh or task, db, now, msg_id)
    await db.commit()
    await sse_publish("task.updated", {
        "task_key": upd.task_key,
        "status": (fresh or task)["status"],
        "readiness": (fresh or task)["readiness"],
        "flags": json.loads((fresh or task).get("flags_json") or "[]"),
        "verified": bool((fresh or task).get("verified")),
        "changed_fields": (["status"] if upd.new_status else ["progress_note"])
                          + (["verified"] if upd.verified is not None else []),
        "event_id": event_id,
        "reason": upd.reason,
        "rule_fired": upd.rule_fired,
    })
