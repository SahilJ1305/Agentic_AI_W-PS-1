"""
app/db/repo.py — all database reads and writes for Cadence.

Rules:
  - No business logic here; only SQL + serialisation.
  - No raw SQL outside this module.
  - All writes go through these functions so the Policy Engine and
    Dependency Engine remain testable without a DB.
  - Timestamps are ISO 8601 strings with UTC offset (e.g. 2026-10-17T14:05:00+05:30).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def database_path() -> str:
    """Resolve the SQLite file. Tests can point settings.database_path elsewhere."""
    try:
        from app.config import settings
        if settings.database_path:
            return settings.database_path
    except Exception:
        pass
    return os.getenv("DATABASE_PATH", "./data/cadence.db")


# ── Connection pool ────────────────────────────────────────────────────────────

async def get_db() -> aiosqlite.Connection:
    """Open a WAL-mode connection.  Caller is responsible for closing."""
    db = await aiosqlite.connect(database_path())
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


@asynccontextmanager
async def db_context():
    """Async context manager: yields a connection and commits on exit."""
    db = await get_db()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def init_db(db_path: str | None = None) -> None:
    """Create tables and indexes if they do not exist."""
    path = db_path or database_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(_SCHEMA_PATH.read_text())
        await _add_missing_columns(db)
        await db.commit()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS skips
# existing tables, so older DB files get these through ALTER TABLE.
_ADDED_COLUMNS = [
    ("projects", "owner_user_id", "INTEGER"),
    ("participants", "github_username", "TEXT"),
    ("outbox", "project_id", "INTEGER"),
]


async def _add_missing_columns(db: aiosqlite.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        cur = await db.execute(f"PRAGMA table_info({table})")
        if column not in {row[1] for row in await cur.fetchall()}:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ── helpers ────────────────────────────────────────────────────────────────────

def _row(row: aiosqlite.Row | None) -> dict | None:
    return dict(row) if row else None


def _rows(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── Projects ──────────────────────────────────────────────────────────────────

async def create_project(
    db: aiosqlite.Connection,
    *,
    name: str,
    timezone: str = "Asia/Kolkata",
    owner_user_id: int | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO projects (name, timezone, owner_user_id) VALUES (?, ?, ?)",
        (name, timezone, owner_user_id),
    )
    return cur.lastrowid


async def list_projects(db: aiosqlite.Connection, *, user_id: int | None = None) -> list[dict]:
    """All projects, or only those `user_id` owns plus unowned demo projects."""
    if user_id is None:
        cur = await db.execute("SELECT * FROM projects ORDER BY id")
    else:
        cur = await db.execute(
            "SELECT * FROM projects WHERE owner_user_id = ? OR owner_user_id IS NULL ORDER BY id",
            (user_id,),
        )
    return _rows(await cur.fetchall())


async def get_project(db: aiosqlite.Connection, project_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return _row(await cur.fetchone())


async def get_project_by_group(db: aiosqlite.Connection, group_chat_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM projects WHERE group_chat_id = ?", (group_chat_id,))
    return _row(await cur.fetchone())


async def set_project_group(db: aiosqlite.Connection, project_id: int, group_chat_id: int | None) -> None:
    await db.execute("UPDATE projects SET group_chat_id = ? WHERE id = ?", (group_chat_id, project_id))


async def update_project_status(db: aiosqlite.Connection, project_id: int, status: str) -> None:
    await db.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))


# ── Participants ───────────────────────────────────────────────────────────────

async def create_participant(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    name: str,
    role: str = "member",
    skills: str | None = None,
    invite_code: str,
    telegram_username: str | None = None,
    github_username: str | None = None,
) -> int:
    cur = await db.execute(
        """INSERT INTO participants
           (project_id, name, role, skills, invite_code, telegram_username, github_username)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, name, role, skills, invite_code, telegram_username, github_username),
    )
    return cur.lastrowid


async def set_participant_github(
    db: aiosqlite.Connection, participant_id: int, github_username: str | None
) -> None:
    await db.execute(
        "UPDATE participants SET github_username = ? WHERE id = ?",
        (github_username, participant_id),
    )


async def get_participant_by_invite(db: aiosqlite.Connection, invite_code: str) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM participants WHERE invite_code = ?", (invite_code,)
    )
    return _row(await cur.fetchone())


async def get_participant_by_chat_id(db: aiosqlite.Connection, chat_id: int) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM participants WHERE telegram_chat_id = ?", (chat_id,)
    )
    return _row(await cur.fetchone())


async def get_participant(db: aiosqlite.Connection, participant_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM participants WHERE id = ?", (participant_id,))
    return _row(await cur.fetchone())


async def list_participants(db: aiosqlite.Connection, project_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM participants WHERE project_id = ?", (project_id,)
    )
    return _rows(await cur.fetchall())


async def onboard_participant(
    db: aiosqlite.Connection,
    participant_id: int,
    *,
    chat_id: int,
    onboarded_at: str,
) -> None:
    await db.execute(
        """UPDATE participants
           SET telegram_chat_id = ?, onboarded_at = ?, last_seen_at = ?
           WHERE id = ?""",
        (chat_id, onboarded_at, onboarded_at, participant_id),
    )


async def set_paused_until(db: aiosqlite.Connection, participant_id: int, until: str | None) -> None:
    await db.execute("UPDATE participants SET paused_until = ? WHERE id = ?", (until, participant_id))


async def touch_participant(db: aiosqlite.Connection, participant_id: int, *, last_seen_at: str) -> None:
    await db.execute(
        "UPDATE participants SET last_seen_at = ? WHERE id = ?",
        (last_seen_at, participant_id),
    )


async def get_lead(db: aiosqlite.Connection, project_id: int) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM participants WHERE project_id = ? AND role = 'lead' LIMIT 1",
        (project_id,),
    )
    return _row(await cur.fetchone())


# ── Source documents ───────────────────────────────────────────────────────────

async def save_source_document(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    kind: str,
    filename: str,
    mime_type: str,
    content: str,
    sha256: str,
    uploaded_at: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO source_documents
           (project_id, kind, filename, mime_type, content, sha256, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, kind, filename, mime_type, content, sha256, uploaded_at),
    )
    return cur.lastrowid


async def list_source_documents(db: aiosqlite.Connection, project_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM source_documents WHERE project_id = ?", (project_id,)
    )
    return _rows(await cur.fetchall())


# ── Tasks ──────────────────────────────────────────────────────────────────────

async def create_task(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    key: str,
    title: str,
    description: str | None = None,
    acceptance: str | None = None,
    owner_id: int | None = None,
    status: str = "pending",
    deadline: str | None = None,
    estimate_hours: float | None = None,
    requires_evidence: bool = False,
    milestone_id: int | None = None,
    source: str = "planner",
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO tasks
           (project_id, key, title, description, acceptance, owner_id, status,
            deadline, estimate_hours, requires_evidence, milestone_id, source,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id, key, title, description, acceptance, owner_id, status,
            deadline, estimate_hours, int(requires_evidence), milestone_id, source,
            now, now,
        ),
    )
    return cur.lastrowid


async def get_task(db: aiosqlite.Connection, task_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return _row(await cur.fetchone())


async def get_task_by_key(db: aiosqlite.Connection, project_id: int, key: str) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM tasks WHERE project_id = ? AND key = ?", (project_id, key)
    )
    return _row(await cur.fetchone())


async def list_tasks(
    db: aiosqlite.Connection,
    project_id: int,
    *,
    status: str | None = None,
    owner_id: int | None = None,
    readiness: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM tasks WHERE project_id = ?"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if owner_id is not None:
        sql += " AND owner_id = ?"
        params.append(owner_id)
    if readiness:
        sql += " AND readiness = ?"
        params.append(readiness)
    sql += " ORDER BY key"
    cur = await db.execute(sql, params)
    return _rows(await cur.fetchall())


async def list_tasks_for_owner(db: aiosqlite.Connection, owner_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM tasks WHERE owner_id = ? ORDER BY key", (owner_id,)
    )
    return _rows(await cur.fetchall())


async def update_task_status(
    db: aiosqlite.Connection,
    task_id: int,
    *,
    status: str,
    readiness: str | None = None,
    progress_note: str | None = None,
    eta: str | None = None,
    completion_evidence: str | None = None,
    verified: bool | None = None,
    flags_json: str | None = None,
    completed_at: str | None = None,
    last_reply_at: str | None = None,
    owner_id: int | None = None,
    deadline: str | None = None,
    updated_at: str,
    expected_version: int | None = None,
) -> bool:
    """
    Update task status.  Returns False if the version check fails (409-like).
    """
    sets = ["status = ?", "updated_at = ?", "version = version + 1"]
    params: list[Any] = [status, updated_at]
    if readiness is not None:
        sets.append("readiness = ?")
        params.append(readiness)
    if progress_note is not None:
        sets.append("progress_note = ?")
        params.append(progress_note)
    if eta is not None:
        sets.append("eta = ?")
        params.append(eta)
    if completion_evidence is not None:
        sets.append("completion_evidence = ?")
        params.append(completion_evidence)
    if verified is not None:
        sets.append("verified = ?")
        params.append(1 if verified else 0)
    if flags_json is not None:
        sets.append("flags_json = ?")
        params.append(flags_json)
    if completed_at is not None:
        sets.append("completed_at = ?")
        params.append(completed_at)
    if last_reply_at is not None:
        sets.append("last_reply_at = ?")
        params.append(last_reply_at)
    if owner_id is not None:
        sets.append("owner_id = ?")
        params.append(owner_id)
    if deadline is not None:
        sets.append("deadline = ?")
        params.append(deadline)

    params.append(task_id)
    where = "id = ?"
    if expected_version is not None:
        where += " AND version = ?"
        params.append(expected_version)

    cur = await db.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE {where}", params
    )
    return cur.rowcount > 0


async def set_task_readiness(
    db: aiosqlite.Connection, task_id: int, readiness: str, updated_at: str
) -> None:
    await db.execute(
        "UPDATE tasks SET readiness = ?, updated_at = ? WHERE id = ?",
        (readiness, updated_at, task_id),
    )


async def set_critical_path(db: aiosqlite.Connection, task_ids: list[int]) -> None:
    await db.execute("UPDATE tasks SET on_critical_path = 0")
    if task_ids:
        placeholders = ",".join("?" * len(task_ids))
        await db.execute(
            f"UPDATE tasks SET on_critical_path = 1 WHERE id IN ({placeholders})",
            task_ids,
        )


async def set_last_followup(db: aiosqlite.Connection, task_id: int, at: str) -> None:
    await db.execute(
        "UPDATE tasks SET last_followup_at = ?, updated_at = ? WHERE id = ?",
        (at, at, task_id),
    )


# ── Dependencies ───────────────────────────────────────────────────────────────

async def create_dependency(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    upstream_task_id: int,
    downstream_task_id: int,
    type: str = "hard",
    source: str = "explicit",
    state: str = "active",
    confidence: float = 1.0,
    reason: str | None = None,
    evidence: str | None = None,
    created_by_message_id: int | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT OR IGNORE INTO dependencies
           (project_id, upstream_task_id, downstream_task_id, type, source, state,
            confidence, reason, evidence, created_by_message_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id, upstream_task_id, downstream_task_id, type, source, state,
            confidence, reason, evidence, created_by_message_id, now,
        ),
    )
    return cur.lastrowid


async def list_dependencies_upstream(
    db: aiosqlite.Connection, task_id: int, *, state: str = "active"
) -> list[dict]:
    """All edges where this task is the upstream (i.e. what depends ON it)."""
    cur = await db.execute(
        "SELECT * FROM dependencies WHERE upstream_task_id = ? AND state = ?",
        (task_id, state),
    )
    return _rows(await cur.fetchall())


async def list_dependencies_downstream(
    db: aiosqlite.Connection, task_id: int, *, state: str = "active"
) -> list[dict]:
    """All edges where this task is the downstream (i.e. what it waits FOR)."""
    cur = await db.execute(
        "SELECT * FROM dependencies WHERE downstream_task_id = ? AND state = ?",
        (task_id, state),
    )
    return _rows(await cur.fetchall())


async def list_all_dependencies(db: aiosqlite.Connection, project_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM dependencies WHERE project_id = ?", (project_id,)
    )
    return _rows(await cur.fetchall())


async def update_dependency_state(
    db: aiosqlite.Connection, dep_id: int, state: str
) -> None:
    await db.execute(
        "UPDATE dependencies SET state = ? WHERE id = ?", (state, dep_id)
    )


async def mark_dependency_redundant(db: aiosqlite.Connection, dep_id: int) -> None:
    await db.execute(
        "UPDATE dependencies SET redundant = 1 WHERE id = ?", (dep_id,)
    )


# ── Blockers ───────────────────────────────────────────────────────────────────

async def create_blocker(
    db: aiosqlite.Connection,
    *,
    task_id: int,
    description: str,
    kind: str,
    linked_task_id: int | None = None,
    linked_participant_id: int | None = None,
    raised_message_id: int | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO blockers
           (task_id, description, kind, linked_task_id, linked_participant_id,
            raised_message_id, raised_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (task_id, description, kind, linked_task_id, linked_participant_id,
         raised_message_id, now),
    )
    return cur.lastrowid


async def get_blocker(db: aiosqlite.Connection, blocker_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM blockers WHERE id = ?", (blocker_id,))
    return _row(await cur.fetchone())


async def list_open_blockers_for_task(db: aiosqlite.Connection, task_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM blockers WHERE task_id = ? AND status IN ('open', 'pending_confirmation')",
        (task_id,)
    )
    return _rows(await cur.fetchall())


async def list_blockers_linked_to_task(
    db: aiosqlite.Connection, linked_task_id: int
) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM blockers WHERE linked_task_id = ? AND status = 'open'",
        (linked_task_id,),
    )
    return _rows(await cur.fetchall())


async def resolve_blocker(
    db: aiosqlite.Connection,
    blocker_id: int,
    *,
    resolved_message_id: int | None,
    resolved_at: str,
) -> None:
    await db.execute(
        "UPDATE blockers SET status = 'resolved', resolved_message_id = ?, resolved_at = ? WHERE id = ?",
        (resolved_message_id, resolved_at, blocker_id),
    )


async def reopen_blocker(db: aiosqlite.Connection, blocker_id: int) -> None:
    await db.execute("UPDATE blockers SET status = 'open' WHERE id = ?", (blocker_id,))


async def set_blocker_pending_confirmation(
    db: aiosqlite.Connection, blocker_id: int
) -> None:
    await db.execute(
        "UPDATE blockers SET status = 'pending_confirmation' WHERE id = ?",
        (blocker_id,),
    )


async def list_open_blockers(db: aiosqlite.Connection, project_id: int) -> list[dict]:
    cur = await db.execute(
        """SELECT b.* FROM blockers b
           JOIN tasks t ON t.id = b.task_id
           WHERE t.project_id = ? AND b.status IN ('open', 'pending_confirmation')""",
        (project_id,),
    )
    return _rows(await cur.fetchall())


# ── Pending questions ──────────────────────────────────────────────────────────

async def create_pending_question(
    db: aiosqlite.Connection,
    *,
    participant_id: int,
    task_id: int | None,
    kind: str,
    payload_json: str = "{}",
    message_id: int | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO pending_questions
           (participant_id, task_id, kind, payload_json, message_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (participant_id, task_id, kind, payload_json, message_id, now),
    )
    return cur.lastrowid


async def get_question(db: aiosqlite.Connection, question_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM pending_questions WHERE id = ?", (question_id,))
    return _row(await cur.fetchone())


async def get_open_question(
    db: aiosqlite.Connection, participant_id: int
) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM pending_questions WHERE participant_id = ? AND status = 'open' ORDER BY created_at LIMIT 1",
        (participant_id,),
    )
    return _row(await cur.fetchone())


async def close_question(
    db: aiosqlite.Connection, question_id: int, *, answered_at: str
) -> None:
    await db.execute(
        "UPDATE pending_questions SET status = 'answered', answered_at = ? WHERE id = ?",
        (answered_at, question_id),
    )


async def increment_nudge_count(db: aiosqlite.Connection, question_id: int) -> None:
    await db.execute(
        "UPDATE pending_questions SET nudge_count = nudge_count + 1 WHERE id = ?",
        (question_id,),
    )


async def escalate_question(db: aiosqlite.Connection, question_id: int) -> None:
    await db.execute(
        "UPDATE pending_questions SET status = 'escalated' WHERE id = ?",
        (question_id,),
    )


# ── Task events (audit log) ────────────────────────────────────────────────────

async def append_task_event(
    db: aiosqlite.Connection,
    *,
    task_id: int,
    event_type: str,
    old_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
    actor: str,
    source_message_id: int | None = None,
    confidence: float | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO task_events
           (task_id, event_type, old_value, new_value, reason, actor,
            source_message_id, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, event_type, old_value, new_value, reason, actor,
         source_message_id, confidence, now),
    )
    return cur.lastrowid


async def mark_event_reverted(
    db: aiosqlite.Connection, event_id: int, *, revert_event_id: int
) -> None:
    await db.execute(
        "UPDATE task_events SET reverted_by_event_id = ? WHERE id = ?",
        (revert_event_id, event_id),
    )


async def list_task_events(db: aiosqlite.Connection, task_id: int) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at",
        (task_id,),
    )
    return _rows(await cur.fetchall())


async def get_latest_event(db: aiosqlite.Connection, task_id: int, *, actor: str | None = None) -> dict | None:
    if actor:
        cur = await db.execute(
            "SELECT * FROM task_events WHERE task_id = ? AND actor = ? ORDER BY created_at DESC LIMIT 1",
            (task_id, actor),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
            (task_id,),
        )
    return _row(await cur.fetchone())


# ── Messages ───────────────────────────────────────────────────────────────────

async def save_message(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    participant_id: int | None,
    direction: str,
    channel: str = "telegram_dm",
    telegram_message_id: int | None = None,
    text: str,
    template_key: str | None = None,
    related_task_ids: list[int] | None = None,
    interpretation_json: str | None = None,
    llm_call_id: int | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO messages
           (project_id, participant_id, direction, channel, telegram_message_id,
            text, template_key, related_task_ids, interpretation_json, llm_call_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id, participant_id, direction, channel, telegram_message_id,
            text, template_key, json.dumps(related_task_ids or []),
            interpretation_json, llm_call_id, now,
        ),
    )
    return cur.lastrowid


async def list_recent_messages(
    db: aiosqlite.Connection, participant_id: int, *, limit: int = 6
) -> list[dict]:
    cur = await db.execute(
        """SELECT * FROM messages WHERE participant_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (participant_id, limit),
    )
    rows = _rows(await cur.fetchall())
    return list(reversed(rows))


# ── Outbox ─────────────────────────────────────────────────────────────────────

async def enqueue_message(
    db: aiosqlite.Connection,
    *,
    participant_id: int | None,
    chat_id: int,
    template_key: str,
    text: str,
    buttons_json: str | None = None,
    dedupe_key: str | None = None,
    not_before: str | None = None,
    project_id: int | None = None,
    now: str,
) -> int | None:
    """Insert into outbox. Returns None if dedupe_key already exists."""
    try:
        cur = await db.execute(
            """INSERT INTO outbox
               (project_id, participant_id, chat_id, template_key, text, buttons_json,
                dedupe_key, not_before, created_at)
               VALUES (COALESCE(?, (SELECT project_id FROM participants WHERE id = ?)),
                       ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, participant_id, participant_id, chat_id, template_key, text,
             buttons_json, dedupe_key, not_before, now),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # dedupe_key already present


async def fetch_queued_messages(
    db: aiosqlite.Connection, *, now: str, limit: int = 20
) -> list[dict]:
    cur = await db.execute(
        """SELECT * FROM outbox
           WHERE status = 'queued'
             AND (not_before IS NULL OR not_before <= ?)
           ORDER BY created_at
           LIMIT ?""",
        (now, limit),
    )
    return _rows(await cur.fetchall())


async def last_outbox_sent_at(db: aiosqlite.Connection, chat_id: int) -> str | None:
    cur = await db.execute(
        """SELECT created_at FROM outbox
           WHERE chat_id = ? AND status = 'sent'
           ORDER BY created_at DESC LIMIT 1""",
        (chat_id,),
    )
    row = await cur.fetchone()
    return row["created_at"] if row else None


async def defer_outbox(db: aiosqlite.Connection, outbox_id: int, not_before: str) -> None:
    await db.execute(
        "UPDATE outbox SET not_before = ? WHERE id = ?",
        (not_before, outbox_id),
    )


async def mark_outbox_sent(
    db: aiosqlite.Connection, outbox_id: int, *, sent_message_id: int
) -> None:
    await db.execute(
        "UPDATE outbox SET status = 'sent', sent_message_id = ?, attempts = attempts + 1 WHERE id = ?",
        (sent_message_id, outbox_id),
    )


async def mark_outbox_failed(
    db: aiosqlite.Connection, outbox_id: int, *, error: str
) -> None:
    await db.execute(
        "UPDATE outbox SET attempts = attempts + 1, error = ? WHERE id = ?",
        (error, outbox_id),
    )


async def mark_outbox_permanent_failure(
    db: aiosqlite.Connection, outbox_id: int, *, error: str
) -> None:
    await db.execute(
        "UPDATE outbox SET status = 'failed', error = ? WHERE id = ?",
        (error, outbox_id),
    )


# ── LLM calls ─────────────────────────────────────────────────────────────────

async def log_llm_call(
    db: aiosqlite.Connection,
    *,
    agent: str,
    provider: str,
    model: str,
    request_json: str | None,
    response_text: str | None,
    parsed_ok: bool,
    error: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    latency_ms: int | None = None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO llm_calls
           (agent, provider, model, request_json, response_text, parsed_ok, error,
            prompt_tokens, completion_tokens, latency_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            agent, provider, model, request_json, response_text, int(parsed_ok),
            error, prompt_tokens, completion_tokens, latency_ms, now,
        ),
    )
    return cur.lastrowid


# ── Plan drafts ────────────────────────────────────────────────────────────────

async def save_plan_draft(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    plan_json: str,
    validation_json: str,
    llm_call_id: int | None,
    now: str,
) -> int:
    cur = await db.execute(
        """INSERT INTO plan_drafts
           (project_id, plan_json, validation_json, llm_call_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, plan_json, validation_json, llm_call_id, now),
    )
    return cur.lastrowid


async def get_plan_draft(db: aiosqlite.Connection, draft_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM plan_drafts WHERE id = ?", (draft_id,))
    return _row(await cur.fetchone())


async def commit_plan_draft(
    db: aiosqlite.Connection, draft_id: int, *, committed_at: str
) -> None:
    await db.execute(
        "UPDATE plan_drafts SET status = 'committed', committed_at = ? WHERE id = ?",
        (committed_at, draft_id),
    )


# ── Milestones ─────────────────────────────────────────────────────────────────

async def create_milestone(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    key: str,
    name: str,
    due: str | None,
) -> int:
    cur = await db.execute(
        "INSERT INTO milestones (project_id, key, name, due) VALUES (?, ?, ?, ?)",
        (project_id, key, name, due),
    )
    return cur.lastrowid


async def get_milestone_by_key(
    db: aiosqlite.Connection, project_id: int, key: str
) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM milestones WHERE project_id = ? AND key = ?", (project_id, key)
    )
    return _row(await cur.fetchone())


# ── Reports ────────────────────────────────────────────────────────────────────

async def save_report(
    db: aiosqlite.Connection,
    *,
    project_id: int,
    kind: str,
    content_md: str,
    now: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO reports (project_id, kind, content_md, created_at) VALUES (?, ?, ?, ?)",
        (project_id, kind, content_md, now),
    )
    return cur.lastrowid


async def get_latest_report(
    db: aiosqlite.Connection, project_id: int, kind: str
) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM reports WHERE project_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
        (project_id, kind),
    )
    return _row(await cur.fetchone())
