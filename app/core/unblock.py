"""
app/core/unblock.py — clear a task's open blockers and tell everyone who was waiting on it.

One place for every way a blocker can be cleared by someone other than the owner:
  - the lead presses Resolve on the dashboard            (POST /blockers/{id}/resolve)
  - the lead sets a blocked task to another status       (PATCH /tasks/{id})
  - the lead says "unblock Omar" to the bot on Telegram  (app/telegram/router.py)

Before this, the dashboard Resolve button flipped the blocker row and nothing else: the owner was
never told, the task stayed "blocked" on their side, and the escalation ladder had no idea.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import aiosqlite

from app.core.dependency_engine import recompute_all_readiness
from app.core.notifications import NotificationBatch
from app.db import repo


@dataclass
class ClearResult:
    blockers: list[dict] = field(default_factory=list)
    new_status: str | None = None          # set when the task moved off "blocked"
    batch: NotificationBatch = field(default_factory=NotificationBatch)

    @property
    def cleared(self) -> bool:
        return bool(self.blockers)


async def clear_blockers(
    db: aiosqlite.Connection,
    task: dict,
    *,
    by: dict | None,
    note: str,
    now: str,
    actor: str = "lead",
    set_in_progress: bool = True,
    notify_owner: bool = True,
    only_blocker_id: int | None = None,
    source_msg_id: int | None = None,
) -> ClearResult:
    """
    Resolve every open blocker on `task`. Does not commit; the caller flushes `result.batch`.

    set_in_progress  move a blocked task to In progress (off when the caller already set the status)
    notify_owner     tell the owner (off when the caller sends its own message to them)
    only_blocker_id  clear just this blocker (the dashboard's per-blocker Resolve button)
    """
    result = ClearResult()
    blockers = await repo.list_open_blockers_for_task(db, task["id"])
    if only_blocker_id is not None:
        blockers = [b for b in blockers if b["id"] == only_blocker_id]
    if not blockers:
        return result
    result.blockers = blockers

    by_name = (by or {}).get("name") or "The lead"
    reason = note.strip() or f"Cleared by {by_name}"
    for blocker in blockers:
        await repo.resolve_blocker(db, blocker["id"], resolved_message_id=source_msg_id, resolved_at=now)
        await repo.append_task_event(
            db, task_id=task["id"], event_type="blocker_resolved", old_value=blocker["description"],
            reason=reason, actor=actor, source_message_id=source_msg_id, now=now,
        )

    still_blocked = bool(await repo.list_open_blockers_for_task(db, task["id"]))
    if set_in_progress and task["status"] == "blocked" and not still_blocked:
        await repo.update_task_status(db, task["id"], status="in_progress", updated_at=now)
        await repo.append_task_event(
            db, task_id=task["id"], event_type="status_changed", old_value="blocked", new_value="in_progress",
            reason=reason, actor=actor, source_message_id=source_msg_id, now=now,
        )
        result.new_status = "in_progress"

    await recompute_all_readiness(task["project_id"], db, now)

    owner = await repo.get_participant(db, task["owner_id"]) if task.get("owner_id") else None
    description = blockers[0]["description"]
    if notify_owner and owner and owner["id"] != (by or {}).get("id"):
        result.batch.add(
            participant_id=owner["id"],
            template_key="BLOCKER_CLEARED",
            context={
                "task": task,
                "blocker": {"description": description},
                "sender": by_name,
                "note_part": f" They said: “{note.strip()}”." if note.strip() else "",
                "routing_part": " It's back to In progress, so you can carry on." if result.new_status else "",
            },
            dedupe_key=f"cleared:{blockers[0]['id']}",
        )

    # Whoever was asked to help no longer has to.
    helpers = {b.get("linked_participant_id") for b in blockers if b.get("linked_participant_id")}
    for b in blockers:
        if b.get("linked_task_id"):
            linked = await repo.get_task(db, b["linked_task_id"])
            if linked and linked.get("owner_id"):
                helpers.add(linked["owner_id"])
    skip = {(owner or {}).get("id"), (by or {}).get("id")}
    await _close_help_requests(db, {b["id"] for b in blockers}, now)
    for helper_id in helpers - skip:
        result.batch.add(
            participant_id=helper_id,
            template_key="BLOCKER_CLEARED_HELPER",
            context={
                "task": task,
                "sender": by_name,
                "reporter": (owner or {}).get("name", "The owner"),
                "blocker": {"description": description},
            },
            dedupe_key=f"cleared-helper:{blockers[0]['id']}:{helper_id}",
        )
    return result


async def _close_help_requests(db: aiosqlite.Connection, blocker_ids: set[int], now: str) -> None:
    """Close open 'can you unblock X?' questions that were about these blockers."""
    cur = await db.execute(
        "SELECT id, payload_json FROM pending_questions WHERE status = 'open' AND kind IN ('unblock_request', 'confirm_unblocked')"
    )
    for row in await cur.fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if (payload.get("blocker") or {}).get("id") in blocker_ids:
            await repo.close_question(db, row["id"], answered_at=now)
