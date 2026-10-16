"""
app/core/taskview.py — one read-only snapshot of a project, shared by the API,
the reports and the risk rules so they all describe tasks the same way.

load_view() makes a fixed number of queries (no per-task round trips) and
returns tasks already enriched with what a person or a dashboard wants to see:
owner name, open blocker, parsed flags, who the task is waiting on, the latest
status quote, and its risk.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite

from app.core import risk as risk_rules
from app.db import repo


@dataclass
class ProjectView:
    project: dict
    tasks: list[dict]
    people: dict[int, dict]
    deps: list[dict]
    open_blockers: dict[int, list[dict]] = field(default_factory=dict)   # task_id -> blockers
    waiting_on: dict[str, list[str]] = field(default_factory=dict)       # task_key -> unfinished upstream keys
    conflicts: set[str] = field(default_factory=set)                     # task keys with an open conflict question
    risks: list[risk_rules.Risk] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)

    def task(self, key: str) -> dict | None:
        return next((t for t in self.tasks if t["key"] == key), None)

    def task_by_id(self, task_id: int | None) -> dict | None:
        return next((t for t in self.tasks if t["id"] == task_id), None) if task_id else None

    def owner_of_task(self, task_id: int | None) -> str | None:
        task = self.task_by_id(task_id)
        return task.get("owner_name") if task else None


async def load_view(
    db: aiosqlite.Connection, project_id: int, now: datetime | None = None
) -> ProjectView:
    now = now or datetime.now(timezone.utc)
    project = await repo.get_project(db, project_id) or {}
    tasks = await repo.list_tasks(db, project_id)
    people = {p["id"]: p for p in await repo.list_participants(db, project_id)}
    deps = await repo.list_all_dependencies(db, project_id)
    by_id = {t["id"]: t for t in tasks}

    open_blockers: dict[int, list[dict]] = {}
    for blocker in await repo.list_open_blockers(db, project_id):
        open_blockers.setdefault(blocker["task_id"], []).append(blocker)

    waiting: dict[str, list[str]] = {}
    for dep in deps:
        if dep["state"] != "active" or dep["type"] != "hard":
            continue
        upstream, downstream = by_id.get(dep["upstream_task_id"]), by_id.get(dep["downstream_task_id"])
        if upstream and downstream and upstream["status"] != "complete":
            waiting.setdefault(downstream["key"], []).append(upstream["key"])

    cur = await db.execute(
        """SELECT t.key FROM pending_questions q JOIN tasks t ON t.id = q.task_id
           WHERE t.project_id = ? AND q.status = 'open' AND q.kind = 'dependency_conflict'""",
        (project_id,),
    )
    conflicts = {row["key"] for row in await cur.fetchall()}

    latest: dict[int, dict] = {}
    if tasks:
        cur = await db.execute(
            """SELECT e.* FROM task_events e
               WHERE e.id IN (SELECT MAX(id) FROM task_events
                              WHERE event_type IN ('status_changed','note_added','blocker_raised',
                                                   'blocker_resolved','verified','override','reverted')
                                AND task_id IN (SELECT id FROM tasks WHERE project_id = ?)
                              GROUP BY task_id)""",
            (project_id,),
        )
        latest = {row["task_id"]: dict(row) for row in await cur.fetchall()}

    for task in tasks:
        task["owner_name"] = (people.get(task.get("owner_id")) or {}).get("name")
        blockers = open_blockers.get(task["id"], [])
        task["blocker"] = blockers[0]["description"] if blockers else None
        task["flags"] = json.loads(task.get("flags_json") or "[]")
        task["verified"] = bool(task.get("verified"))
        task["waiting_on"] = waiting.get(task["key"], [])
        event = latest.get(task["id"])
        task["last_update"] = (
            {
                "text": event.get("reason") or event.get("new_value"),
                "at": event["created_at"],
                "event_type": event["event_type"],
            }
            if event else None
        )
        task["risk"] = None

    view = ProjectView(
        project=project, tasks=tasks, people=people, deps=deps,
        open_blockers=open_blockers, waiting_on=waiting, conflicts=conflicts,
    )
    view.risks = risk_rules.assess(view, now)
    for item in view.risks:
        task = view.task(item.task_key)
        if task:
            task["risk"] = {"level": item.level, "why": item.why}
    path = [t for t in tasks if t.get("on_critical_path")]
    path.sort(key=lambda t: _topo_rank(t, view))
    view.critical_path = [t["key"] for t in path]
    return view


def _topo_rank(task: dict, view: ProjectView) -> int:
    """Order critical-path tasks upstream-first by counting their ancestors."""
    seen: set[int] = set()
    stack = [task["id"]]
    while stack:
        current = stack.pop()
        for dep in view.deps:
            if dep["state"] == "active" and dep["downstream_task_id"] == current \
                    and dep["upstream_task_id"] not in seen:
                seen.add(dep["upstream_task_id"])
                stack.append(dep["upstream_task_id"])
    return len(seen)
