"""
Parse a project spec and an optional task doc into participants and tasks.

Used when a document is uploaded so Tier 1 seeding does not depend on the
planner succeeding. The original text stays in source_documents; this module
only writes rows.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from app.config import settings
from app.core.dependency_engine import compute_critical_path, recompute_all_readiness
from app.db import repo

_STATUSES = {
    "pending": "pending",
    "not_started": "pending",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "doing": "in_progress",
    "blocked": "blocked",
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
}


def _norm_header(header: str) -> str:
    header = header.split("(")[0]
    header = header.replace("@", " ")
    header = re.sub(r"\s+", " ", header).strip().lower()
    return header.replace(" ", "_")


def parse_markdown_tables(text: str) -> list[list[dict[str, str]]]:
    """Return every GitHub-style table as a list of header→cell dicts."""
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines) - 1:
        header_line = lines[i].strip()
        separator = lines[i + 1].strip()
        if header_line.startswith("|") and _is_separator(separator):
            headers = [_norm_header(cell) for cell in _split_row(header_line)]
            i += 2
            rows: list[dict[str, str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = _split_row(lines[i].strip())
                rows.append({
                    headers[j]: (cells[j].strip() if j < len(cells) else "")
                    for j in range(len(headers))
                    if headers[j]
                })
                i += 1
            if rows:
                tables.append(rows)
            continue
        i += 1
    return tables


def _is_separator(line: str) -> bool:
    if not line.startswith("|"):
        return False
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_team(spec_text: str) -> list[dict[str, str]]:
    """Read the Team table: name, role, skills, telegram username."""
    people: list[dict[str, str]] = []
    for table in parse_markdown_tables(spec_text):
        if not table or "name" not in table[0] or "title" in table[0] or "key" in table[0]:
            continue
        for row in table:
            name = row.get("name", "").strip()
            if not name or name.lower() == "name":
                continue
            role = row.get("role", "member").strip().lower()
            people.append({
                "name": name,
                "role": "lead" if "lead" in role else "member",
                "skills": row.get("skills", "").strip(),
                "telegram_username": (
                    row.get("telegram_username") or row.get("telegram") or ""
                ).strip().lstrip("@"),
                "github_username": (
                    row.get("github_username") or row.get("github") or ""
                ).strip().lstrip("@"),
            })
    return people


def parse_task_table(text: str) -> list[dict]:
    """Read a §14.2 task table. Returns [] when the document has none."""
    tasks: list[dict] = []
    for table in parse_markdown_tables(text):
        if not table or "key" not in table[0] or "title" not in table[0]:
            continue
        for row in table:
            key = row.get("key", "").strip().upper()
            title = row.get("title", "").strip()
            if not key or not title or key == "KEY":
                continue
            status_raw = row.get("status", "").strip().lower().replace(" ", "_")
            evidence = row.get("requires_evidence", "").strip().lower()
            tasks.append({
                "key": key,
                "title": title,
                "owner": row.get("owner", "").strip(),
                "status": _STATUSES.get(status_raw, "pending"),
                "deadline": row.get("deadline", "").strip(),
                "depends_on": _parse_depends(row.get("depends_on", "")),
                "requires_evidence": evidence in {"yes", "true", "y", "1"},
                "milestone": row.get("milestone", "").strip(),
                "notes": row.get("notes", "").strip(),
            })
    return tasks


def _parse_depends(raw: str) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        kind = "hard"
        if part.startswith("~"):
            kind = "soft"
            part = part[1:].strip()
        key = part.upper()
        if key:
            edges.append((key, kind))
    return edges


def parse_deadline(text: str, now: datetime | None = None) -> str | None:
    """Turn 'today 20:00', 'tomorrow 08:00', or an ISO stamp into ISO 8601."""
    text = (text or "").strip()
    if not text:
        return None
    zone = ZoneInfo(settings.timezone)
    current = now.astimezone(zone) if now else datetime.now(zone)
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=zone).isoformat()
        except ValueError:
            continue
    match = re.fullmatch(
        r"(today|tomorrow)\s+(\d{1,2}):(\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return text
    day = current
    if match.group(1).lower() == "tomorrow":
        day = current + timedelta(days=1)
    stamp = day.replace(
        hour=int(match.group(2)),
        minute=int(match.group(3)),
        second=0,
        microsecond=0,
    )
    return stamp.isoformat()


async def ensure_participants_from_spec(
    db: aiosqlite.Connection,
    project_id: int,
    spec_text: str,
) -> int:
    """Create any team members named in the spec who are not already stored."""
    existing = {
        person["name"].lower(): person
        for person in await repo.list_participants(db, project_id)
    }
    created = 0
    for person in parse_team(spec_text):
        if person["name"].lower() in existing:
            continue
        await repo.create_participant(
            db,
            project_id=project_id,
            name=person["name"],
            role=person["role"],
            skills=person["skills"] or None,
            invite_code=secrets.token_urlsafe(12),
            telegram_username=person["telegram_username"] or None,
            github_username=person["github_username"] or None,
        )
        created += 1
    return created


async def _apply_revision(db, existing: dict, row: dict, before: dict | None, owner_id, deadline, now: str) -> None:
    """Copy what a spec revision changed about an existing task. Unchanged cells are left alone."""
    changes: dict = {}
    if row["title"] != existing["title"]:
        changes["title"] = row["title"]
    if owner_id is not None and owner_id != existing.get("owner_id"):
        changes["owner_id"] = owner_id
    # Deadlines are relative ("today 18:00"): re-reading an unchanged cell on a later day would move it.
    if before is not None and row["deadline"] != before["deadline"] and deadline:
        changes["deadline"] = deadline
    if before is not None and row["notes"] != before["notes"]:
        changes["description"] = row["notes"] or None
    if not changes:
        return
    await repo.update_task_details(db, existing["id"], updated_at=now, **changes)
    await repo.append_task_event(
        db, task_id=existing["id"], event_type="override",
        new_value=", ".join(sorted("owner" if k == "owner_id" else k for k in changes)),
        reason="Updated from the revised spec", actor="system", now=now,
    )


async def import_task_document(
    db: aiosqlite.Connection,
    project_id: int,
    task_doc_text: str,
    now: str,
    previous_text: str | None = None,
) -> dict:
    """
    Write tasks, owners, deadlines and dependencies from a task table.
    Existing keys keep their id; status is updated when the document disagrees.

    previous_text is the earlier version of a revised spec. Then live statuses are kept (the team has
    moved on since v1) and existing tasks only take the title, owner and deadline the revision changed.
    """
    rows = parse_task_table(task_doc_text)
    if not rows:
        return {"tasks": 0, "dependencies": 0}
    previous = {r["key"]: r for r in parse_task_table(previous_text)} if previous_text is not None else None

    current = datetime.now(ZoneInfo(settings.timezone))
    participants = {
        person["name"].lower(): person
        for person in await repo.list_participants(db, project_id)
    }
    milestone_ids: dict[str, int] = {}
    task_ids: dict[str, int] = {}

    for row in rows:
        milestone_id = None
        if row["milestone"]:
            milestone_id = milestone_ids.get(row["milestone"])
            if milestone_id is None:
                found = await repo.get_milestone_by_key(db, project_id, row["milestone"])
                if found:
                    milestone_id = found["id"]
                else:
                    milestone_id = await repo.create_milestone(
                        db,
                        project_id=project_id,
                        key=row["milestone"],
                        name=row["milestone"],
                        due=None,
                    )
                milestone_ids[row["milestone"]] = milestone_id

        owner = participants.get(row["owner"].lower())
        owner_id = owner["id"] if owner else None
        deadline = parse_deadline(row["deadline"], current)
        existing = await repo.get_task_by_key(db, project_id, row["key"])
        if existing and previous is not None:
            task_ids[row["key"]] = existing["id"]
            await _apply_revision(db, existing, row, previous.get(row["key"]), owner_id, deadline, now)
            continue
        if existing:
            task_ids[row["key"]] = existing["id"]
            if row["status"] != existing["status"]:
                await repo.update_task_status(
                    db,
                    existing["id"],
                    status=row["status"],
                    updated_at=now,
                )
                await repo.append_task_event(
                    db,
                    task_id=existing["id"],
                    event_type="status_changed",
                    old_value=existing["status"],
                    new_value=row["status"],
                    reason="Updated from the uploaded task document",
                    actor="system",
                    now=now,
                )
            continue

        task_id = await repo.create_task(
            db,
            project_id=project_id,
            key=row["key"],
            title=row["title"],
            description=row["notes"] or None,
            owner_id=owner_id,
            status=row["status"],
            deadline=deadline,
            requires_evidence=row["requires_evidence"],
            milestone_id=milestone_id,
            source="task_doc",
            now=now,
        )
        task_ids[row["key"]] = task_id
        if row["status"] != "pending":
            await repo.append_task_event(
                db,
                task_id=task_id,
                event_type="status_changed",
                old_value="pending",
                new_value=row["status"],
                reason="Imported from the task document",
                actor="system",
                now=now,
            )

    dependencies = 0
    for row in rows:
        downstream_id = task_ids.get(row["key"])
        if downstream_id is None:
            continue
        for upstream_key, edge_type in row["depends_on"]:
            upstream_id = task_ids.get(upstream_key)
            if upstream_id is None:
                continue
            await repo.create_dependency(
                db,
                project_id=project_id,
                upstream_task_id=upstream_id,
                downstream_task_id=downstream_id,
                type=edge_type,
                source="explicit",
                state="active",
                confidence=1.0,
                reason="Declared in the uploaded task document",
                now=now,
            )
            dependencies += 1

    await recompute_all_readiness(project_id, db, now)
    await compute_critical_path(project_id, db, now)
    return {"tasks": len(task_ids), "dependencies": dependencies}
