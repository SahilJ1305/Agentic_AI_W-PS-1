"""
app/agents/coordinator.py — Coordinator Agent.

Converts one inbound message (or burst) into an Interpretation.
Latency budget: < 5 s (thinking off, small context).
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite
import yaml

from app.agents.schemas import Interpretation
from app.llm.gateway import LLMFailure, call_llm

log = logging.getLogger(__name__)

_PROMPTS = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS / "coordinator_system.md").read_text()
_FEWSHOTS = _PROMPTS / "fewshots.yaml"


def _examples_text() -> str:
    """Compact few-shots so Hinglish, multi-task, and undo examples reach the model."""
    if not _FEWSHOTS.exists():
        return ""
    data = yaml.safe_load(_FEWSHOTS.read_text()) or {}
    lines = ["Examples (message → what to report):"]
    for case in data.get("cases") or []:
        expected = case.get("expected") or {}
        updates = expected.get("updates") or []
        summary = expected.get("intent", "status_update")
        if updates:
            bits = []
            for update in updates:
                status = update.get("status") or "note"
                bits.append(f"{update.get('task_key')}={status}")
            summary = ", ".join(bits)
        lines.append(f"- {case.get('message')!r} → {summary}")
    return "\n".join(lines)


def _format_task_line(t: dict) -> str:
    """Format a single task for the context packet."""
    blocker = f"blocker: {t.get('blocker_desc', 'none')}" if t.get("status") == "blocked" else ""
    parts = [
        f"- {t['key']}",
        f"| {t['title']}",
        f"| {t['status']}",
    ]
    if t.get("deadline"):
        parts.append(f"| deadline {t['deadline']}")
    if blocker:
        parts.append(f"| {blocker}")
    return " ".join(parts)


def build_context_packet(
    *,
    now: str,
    sender_name: str,
    pending_question: dict | None,
    sender_tasks: list[dict],
    task_index: list[dict],
    recent_messages: list[dict],
    message_text: str,
) -> str:
    """
    Build the context packet exactly as described in spec §10.2.
    Kept under ~2k tokens.
    """
    lines: list[str] = [
        f"NOW: {now}",
        f"SENDER: {sender_name}",
    ]

    if pending_question:
        pq = pending_question
        task_key = pq.get("task_key", "?")
        kind = pq.get("kind", "?")
        asked_at = pq.get("created_at", "")
        lines.append(f"PENDING QUESTION: {kind} for {task_key} (asked {asked_at})")
    else:
        lines.append("PENDING QUESTION: none")

    lines.append("SENDER TASKS:")
    for t in sender_tasks:
        lines.append(_format_task_line(t))

    # Task index: other team members' tasks (title only, to limit tokens)
    if task_index:
        lines.append("TASK INDEX:")
        for t in task_index:
            owner = t.get("owner_name", "?")
            status = t.get("status", "?")
            lines.append(f"- {t['key']} {t['title']} ({owner}, {status})")

    if recent_messages:
        lines.append("RECENT MESSAGES (oldest first):")
        for m in recent_messages[-6:]:  # cap at 6
            direction = "bot" if m["direction"] == "out" else sender_name
            lines.append(f"[{direction} {m['created_at']}] {m['text']}")

    lines.append("MESSAGE:")
    lines.append(message_text)

    return "\n".join(lines)


async def run_coordinator(
    *,
    now: str,
    sender_name: str,
    pending_question: dict | None,
    sender_tasks: list[dict],
    task_index: list[dict],
    recent_messages: list[dict],
    message_text: str,
    db: aiosqlite.Connection,
) -> Interpretation:
    """
    Call the Coordinator Agent and return a validated Interpretation.

    Args:
        now:              ISO 8601 current timestamp.
        sender_name:      Name of the participant who sent the message.
        pending_question: Open pending_question row for this participant, or None.
        sender_tasks:     List of task dicts owned by the sender.
        task_index:       All other tasks in the project (for blocker matching).
        recent_messages:  Last ≤ 6 messages for this participant.
        message_text:     The actual message to interpret (may be a burst joined by \n).
        db:               Open DB connection for LLM call logging.

    Returns:
        Interpretation — may have needs_clarification=True.

    Raises:
        LLMFailure if all providers fail.
    """
    context = build_context_packet(
        now=now,
        sender_name=sender_name,
        pending_question=pending_question,
        sender_tasks=sender_tasks,
        task_index=task_index,
        recent_messages=recent_messages,
        message_text=message_text,
    )

    examples = _examples_text()
    system = _SYSTEM_PROMPT if not examples else f"{_SYSTEM_PROMPT}\n\n{examples}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": context},
    ]

    log.debug("Coordinator context for %s: %s", sender_name, context[:300])

    interp = await call_llm(
        "coordinator",
        messages,
        Interpretation,
        db=db,
        now=now,
    )

    # Stamp the raw message for the dashboard "why" panel
    interp.raw_message = message_text

    log.info(
        "Coordinator: sender=%s intent=%s updates=%d clarify=%s",
        sender_name,
        interp.intent,
        len(interp.updates),
        interp.needs_clarification,
    )
    return interp
