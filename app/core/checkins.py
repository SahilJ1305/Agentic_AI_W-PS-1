"""Queue one follow-up per owner for that owner's chase-able tasks."""
from __future__ import annotations

import aiosqlite

from app.core.notifications import NotificationBatch
from app.db import repo


async def queue_checkins(
    db: aiosqlite.Connection,
    project_id: int,
    now: str,
    task_keys: list[str] | None = None,
) -> int:
    """
    Chase tasks that are in progress, blocked, or pending and ready.
    One outbox message per onboarded owner. Returns how many tasks were covered.
    """
    tasks = await repo.list_tasks(db, project_id)
    participants = {p["id"]: p for p in await repo.list_participants(db, project_id)}

    chaseable = [
        task for task in tasks
        if task["status"] in ("in_progress", "blocked")
        or (task["status"] == "pending" and task["readiness"] == "ready")
    ]
    if task_keys:
        wanted = set(task_keys)
        chaseable = [task for task in chaseable if task["key"] in wanted]

    by_owner: dict[int, list[dict]] = {}
    for task in chaseable:
        if task.get("owner_id"):
            by_owner.setdefault(task["owner_id"], []).append(task)

    targeted = 0
    for owner_id, owner_tasks in by_owner.items():
        person = participants.get(owner_id)
        if not person or not person.get("telegram_chat_id"):
            continue
        batch = NotificationBatch()
        if len(owner_tasks) == 1:
            task = owner_tasks[0]
            batch.add(
                participant_id=owner_id,
                template_key="FOLLOWUP_SINGLE",
                context={"task": task, "name": person["name"]},
                dedupe_key=f"followup:{task['id']}:{now[:16]}",
                question_kind="status_check",
                question_task_id=task["id"],
            )
        else:
            batch.add(
                participant_id=owner_id,
                template_key="FOLLOWUP_MULTI",
                context={
                    "name": person["name"],
                    "numbered_task_list": "\n".join(
                        f"{index}. {task['key']} · {task['title']}"
                        for index, task in enumerate(owner_tasks, start=1)
                    ),
                },
                dedupe_key=f"followup-multi:{owner_id}:{now[:16]}",
            )
        await batch.flush(db, now=now)
        for task in owner_tasks:
            await repo.set_last_followup(db, task["id"], at=now)
        targeted += len(owner_tasks)
    return targeted
