"""
app/core/next_task.py — next-task selection (spec §7.6).

When someone completes a task, we pick their next task by:
  1. Their own tasks with status pending/in_progress and readiness ready
     → ranked: critical path first, then earliest deadline, then most dependents
  2. If nothing: highest-ranked unassigned ready task matching their skills
  3. If still nothing: None (→ ACK_COMPLETE_ALL_CLEAR)
"""
from __future__ import annotations

import logging

import aiosqlite

from app.db import repo

log = logging.getLogger(__name__)


async def pick_next_task(owner_id: int, db: aiosqlite.Connection) -> dict | None:
    """Return the best next task for this owner, or None."""
    tasks = await repo.list_tasks_for_owner(db, owner_id)
    candidates = [
        t for t in tasks
        if t["status"] in ("pending", "in_progress") and t["readiness"] == "ready"
    ]
    if not candidates:
        return None

    return _rank_candidates(candidates)[0]


def _rank_candidates(tasks: list[dict]) -> list[dict]:
    """
    Sort by:
      1. on_critical_path (1 first)
      2. deadline ascending (None last)
      3. ... (future: most dependents — needs extra query, skip for Tier 1)
    """
    import datetime

    def sort_key(t: dict):
        cp = 0 if t["on_critical_path"] else 1
        if t.get("deadline"):
            try:
                dl = datetime.datetime.fromisoformat(t["deadline"]).timestamp()
            except Exception:
                dl = float("inf")
        else:
            dl = float("inf")
        return (cp, dl)

    return sorted(tasks, key=sort_key)


async def pick_unassigned_for(owner_id: int, project_id: int, db: aiosqlite.Connection) -> dict | None:
    """
    Find the highest-ranked unassigned ready task for this owner.
    Skill matching is simple substring for Tier 1.
    """
    owner = await repo.get_participant(db, owner_id)
    if not owner:
        return None

    skills = set((owner.get("skills") or "").lower().split(","))

    unassigned = [
        t for t in await repo.list_tasks(db, project_id, readiness="ready")
        if t["owner_id"] is None and t["status"] in ("pending", "in_progress")
    ]
    if not unassigned:
        return None

    # Skill-matching: prefer tasks whose title/description overlaps owner skills
    def skill_score(t: dict) -> int:
        text = (t.get("title", "") + " " + t.get("description", "")).lower()
        return sum(1 for s in skills if s and s in text)

    ranked = sorted(unassigned, key=lambda t: (-skill_score(t), t.get("deadline") or ""))
    return ranked[0] if ranked else None
