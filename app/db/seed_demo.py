"""
app/db/seed_demo.py — seeds the FestPass demo project.

Run with:  python -m app.db.seed_demo
Or via:    make reset-demo

All deadlines are computed relative to NOW so the demo is always fresh.
The seed only runs if no project named 'FestPass' exists.
Use --force to drop and recreate it.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from app.config import settings
from app.core.dependency_engine import compute_critical_path, recompute_all_readiness
from app.db import repo

_DOCS = Path(__file__).resolve().parents[2] / "docs"

# ── FestPass task definitions ─────────────────────────────────────────────────

PARTICIPANTS = [
    {"name": "Aanya", "role": "lead",   "skills": "design,slides,pitching"},
    {"name": "Kabir", "role": "member", "skills": "backend,apis"},
    {"name": "Meera", "role": "member", "skills": "frontend"},
    {"name": "Rohan", "role": "member", "skills": "backend,devops"},
]

# deadline_offset: hours from now (None = no deadline)
TASKS = [
    {
        "key": "T1",
        "title": "Set up backend and database",
        "description": "Bootstrap the backend server, configure the database and make sure both are reachable from the dev environment.",
        "acceptance": "Backend responds to a health check; database migrations run cleanly.",
        "owner": "Rohan",
        "status": "complete",
        "deadline_offset": None,
        "requires_evidence": True,
        "milestone": "M1",
    },
    {
        "key": "T2",
        "title": "Set up payment gateway sandbox account",
        "description": "Create the sandbox account on the payment gateway and generate test API credentials.",
        "acceptance": "Sandbox credentials are generated and shared with the backend developer.",
        "owner": "Rohan",
        "status": "pending",
        "deadline_offset": 4,  # today +4 h
        "requires_evidence": False,
        "milestone": "M1",
    },
    {
        "key": "T3",
        "title": "Connect the payment API",
        "description": "Integrate the payment gateway API into the backend. Implement charge, refund and webhook endpoints.",
        "acceptance": "End-to-end payment succeeds in the sandbox; webhook fires correctly.",
        "owner": "Kabir",
        "status": "pending",
        "deadline_offset": 8,
        "requires_evidence": True,
        "milestone": "M1",
        "depends_on": [("T1", "hard")],  # T2→T3 deliberately NOT seeded (runtime discovery demo)
    },
    {
        "key": "T4",
        "title": "Build checkout UI",
        "description": "Implement the checkout page: cart summary, payment form and confirmation screen.",
        "acceptance": "Checkout page renders correctly; form validates inputs.",
        "owner": "Meera",
        "status": "in_progress",
        "deadline_offset": 6,
        "requires_evidence": True,
        "milestone": "M1",
    },
    {
        "key": "T5",
        "title": "Integrate checkout UI with payment API",
        "description": "Wire the checkout UI to the backend payment endpoints. Handle success, failure and timeout states.",
        "acceptance": "Full purchase flow works end-to-end in the sandbox.",
        "owner": "Meera",
        "status": "pending",
        "deadline_offset": 11,
        "requires_evidence": True,
        "milestone": "M2",
        "depends_on": [("T3", "hard"), ("T4", "hard")],
    },
    {
        "key": "T6",
        "title": "Prepare pitch slides",
        "description": "Create the presentation slides: problem, solution, demo, tech stack, team.",
        "acceptance": "Slides reviewed by the lead; deck under 12 slides.",
        "owner": "Aanya",
        "status": "complete",
        "deadline_offset": None,
        "requires_evidence": True,
        "milestone": "M2",
    },
    {
        "key": "T7",
        "title": "Record demo video",
        "description": "Record a 90-second screen demo of the working FestPass app.",
        "acceptance": "Video under 2 minutes; audio clear; payment flow visible.",
        "owner": "Aanya",
        "status": "pending",
        "deadline_offset": 20,
        "requires_evidence": True,
        "milestone": "M2",
        "depends_on": [("T5", "hard"), ("T6", "soft")],
    },
    {
        "key": "T8",
        "title": "Final testing and submission",
        "description": "Run the full acceptance test suite; package and submit to the judging portal.",
        "acceptance": "All tests pass; submission confirmed by the portal.",
        "owner": "Aanya",
        "status": "pending",
        "deadline_offset": 22,
        "requires_evidence": True,
        "milestone": "M2",
        "depends_on": [("T5", "hard"), ("T7", "hard")],
    },
]

MILESTONES = [
    {"key": "M1", "name": "Backend + payment ready", "offset_hours": 10},
    {"key": "M2", "name": "Submission ready", "offset_hours": 22},
]


# ── Seed logic ─────────────────────────────────────────────────────────────────

async def seed(force: bool = False) -> None:
    await repo.init_db(settings.database_path)

    async with repo.db_context() as db:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()

        # Check if already seeded
        cur = await db.execute("SELECT id FROM projects WHERE name = 'FestPass' LIMIT 1")
        existing = await cur.fetchone()
        preserved: dict[str, dict] = {}
        if existing:
            if not force:
                print("FestPass already seeded. Use --force to reset.")
                return
            pid = existing["id"]
            people = await repo.list_participants(db, pid)
            for person in people:
                preserved[person["name"]] = person
            await _wipe_project(db, pid)
            print(f"Dropped existing FestPass project (id={pid}).")

        # Create project
        project_id = await repo.create_project(db, name="FestPass", timezone="Asia/Kolkata")
        await repo.update_project_status(db, project_id, "active")
        print(f"Created FestPass project (id={project_id}).")

        # Milestones
        milestone_ids: dict[str, int] = {}
        for m in MILESTONES:
            due_dt = now_dt + timedelta(hours=m["offset_hours"])
            mid = await repo.create_milestone(
                db, project_id=project_id, key=m["key"], name=m["name"],
                due=due_dt.isoformat()
            )
            milestone_ids[m["key"]] = mid

        # Participants
        participant_ids: dict[str, int] = {}
        invite_codes: dict[str, str] = {}
        for p in PARTICIPANTS:
            saved = preserved.get(p["name"]) or {}
            code = saved.get("invite_code") or secrets.token_urlsafe(12)
            pid = await repo.create_participant(
                db,
                project_id=project_id,
                name=p["name"],
                role=p["role"],
                skills=p["skills"],
                invite_code=code,
                telegram_username=saved.get("telegram_username"),
                github_username=saved.get("github_username"),
            )
            if saved.get("telegram_chat_id"):
                await repo.onboard_participant(
                    db,
                    pid,
                    chat_id=saved["telegram_chat_id"],
                    onboarded_at=saved.get("onboarded_at") or now,
                )
            participant_ids[p["name"]] = pid
            invite_codes[p["name"]] = code

        # Tasks (first pass — no deps yet)
        task_ids: dict[str, int] = {}
        for t in TASKS:
            owner_id = participant_ids.get(t["owner"])
            deadline = None
            if t.get("deadline_offset") is not None:
                deadline = (now_dt + timedelta(hours=t["deadline_offset"])).isoformat()
            mid = milestone_ids.get(t.get("milestone", ""))
            tid = await repo.create_task(
                db,
                project_id=project_id,
                key=t["key"],
                title=t["title"],
                description=t["description"],
                acceptance=t["acceptance"],
                owner_id=owner_id,
                status=t["status"],
                deadline=deadline,
                requires_evidence=t["requires_evidence"],
                milestone_id=mid,
                source="task_doc",
                now=now,
            )
            task_ids[t["key"]] = tid

            # Log initial status as an event
            if t["status"] != "pending":
                await repo.append_task_event(
                    db,
                    task_id=tid,
                    event_type="status_changed",
                    old_value="pending",
                    new_value=t["status"],
                    reason="Seeded from demo task doc",
                    actor="system",
                    now=now,
                )

        # Dependencies (second pass)
        for t in TASKS:
            for dep_key, dep_type in t.get("depends_on", []):
                upstream_id = task_ids[dep_key]
                downstream_id = task_ids[t["key"]]
                await repo.create_dependency(
                    db,
                    project_id=project_id,
                    upstream_task_id=upstream_id,
                    downstream_task_id=downstream_id,
                    type=dep_type,
                    source="explicit",
                    state="active",
                    confidence=1.0,
                    reason="Declared in demo task doc",
                    now=now,
                )

        await recompute_all_readiness(project_id, db, now)
        await compute_critical_path(project_id, db, now)
        await _store_demo_documents(db, project_id, now)

        print("\nParticipant invite codes:")
        for name, code in invite_codes.items():
            bot = settings.telegram_bot_username
            print(f"  {name:<6} → t.me/{bot}?start={code}")

        print(f"\n✓ Seeded FestPass: {len(task_ids)} tasks, {len(milestone_ids)} milestones, {len(participant_ids)} participants.")


async def _wipe_project(db: aiosqlite.Connection, project_id: int) -> None:
    """Delete a project in foreign-key order. outbox has no project_id column."""
    task_rows = await (await db.execute(
        "SELECT id FROM tasks WHERE project_id = ?", (project_id,)
    )).fetchall()
    person_rows = await (await db.execute(
        "SELECT id FROM participants WHERE project_id = ?", (project_id,)
    )).fetchall()
    task_ids = [row["id"] for row in task_rows]
    person_ids = [row["id"] for row in person_rows]

    async def delete_in(sql: str, ids: list[int]) -> None:
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        await db.execute(f"{sql} ({marks})", ids)

    await delete_in("DELETE FROM outbox WHERE participant_id IN", person_ids)
    await delete_in("DELETE FROM pending_questions WHERE participant_id IN", person_ids)
    await delete_in("DELETE FROM task_events WHERE task_id IN", task_ids)
    await delete_in("DELETE FROM blockers WHERE task_id IN", task_ids)
    await db.execute("DELETE FROM dependencies WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM reports WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM messages WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM milestones WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM plan_drafts WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM source_documents WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM participants WHERE project_id = ?", (project_id,))
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))


async def _store_demo_documents(db: aiosqlite.Connection, project_id: int, now: str) -> None:
    """Keep the original demo spec and task doc, unchanged, on the project."""
    files = (("spec", _DOCS / "demo-spec.md"), ("task_doc", _DOCS / "demo-tasks.md"))
    for kind, path in files:
        if not path.exists():
            continue
        content = path.read_text()
        await repo.save_source_document(
            db,
            project_id=project_id,
            kind=kind,
            filename=path.name,
            mime_type="text/markdown",
            content=content,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            uploaded_at=now,
        )


if __name__ == "__main__":
    force = "--force" in sys.argv
    asyncio.run(seed(force=force))
