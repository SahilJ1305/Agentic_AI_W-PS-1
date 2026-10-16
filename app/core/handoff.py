"""
app/core/handoff.py — suggest who should take over a task (spec G3.11).

Ranks teammates by how well their skills match the task's words, then by how
few open tasks they already carry. Only a suggestion: the lead decides.
"""
from __future__ import annotations

import re

import aiosqlite

from app.db import repo


def _words(text: str | None) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) >= 3}


def _skill_hits(skills: str | None, task_words: set[str]) -> int:
    hits = 0
    for skill in re.split(r"[,;/]", (skills or "").lower()):
        skill = skill.strip()
        if not skill:
            continue
        parts = _words(skill)
        if skill in task_words or (parts and parts & task_words) or any(
            w.startswith(skill) or skill.startswith(w) for w in task_words if len(skill) >= 4
        ):
            hits += 1
    return hits


async def suggest_owner(
    db: aiosqlite.Connection, project_id: int, task: dict, exclude_participant_id: int
) -> dict | None:
    """Return {name, skills, open_count, skill_hits} for the best candidate, or None."""
    task_words = _words(f"{task.get('title', '')} {task.get('description', '')}")
    tasks = await repo.list_tasks(db, project_id)
    best: tuple[tuple, dict] | None = None
    for person in await repo.list_participants(db, project_id):
        if person["id"] == exclude_participant_id:
            continue
        open_count = sum(
            1 for t in tasks if t.get("owner_id") == person["id"] and t["status"] != "complete"
        )
        hits = _skill_hits(person.get("skills"), task_words)
        # skills first, then lighter load, then members over the lead
        rank = (-hits, open_count, person["role"] == "lead")
        candidate = {
            "name": person["name"], "skills": person.get("skills") or "no skills listed",
            "open_count": open_count, "skill_hits": hits,
        }
        if best is None or rank < best[0]:
            best = (rank, candidate)
    return best[1] if best else None
