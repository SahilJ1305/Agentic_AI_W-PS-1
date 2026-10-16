"""
app/agents/planner.py — Planner Agent.

Converts project documents into a PlanDraft.
Called once on project creation (and again on re-plan).
Latency budget: 30–120 s (thinking on, large context).
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from app.agents.schemas import PlanDraft
from app.config import settings
from app.llm.gateway import LLMFailure, call_llm

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "planner_system.md").read_text()


async def run_planner(
    *,
    project_name: str,
    now: str,
    timezone: str,
    roster: list[dict],
    spec_text: str,
    task_doc_text: str | None = None,
    db: aiosqlite.Connection,
) -> PlanDraft:
    """
    Call the Planner Agent and return a validated PlanDraft.

    Args:
        project_name: Human name of the project.
        now:          ISO 8601 timestamp for the current moment.
        timezone:     e.g. "Asia/Kolkata"
        roster:       List of {"name", "role", "skills"} dicts.
        spec_text:    Full text of the spec document.
        task_doc_text: Optional task doc text (Mode B).
        db:           Open DB connection for LLM call logging.

    Raises:
        LLMFailure if all providers fail.
    """
    roster_text = "\n".join(
        f"  - {p['name']} ({p['role']}): {p.get('skills', 'unknown')}"
        for p in roster
    )

    task_section = f"TASK DOC:\n{task_doc_text}" if task_doc_text else "TASK DOC: none"

    user_content = (
        f"PROJECT: {project_name}\n"
        f"NOW: {now} ({timezone})\n"
        f"ROSTER:\n{roster_text}\n\n"
        f"SPEC:\n{spec_text}\n\n"
        f"{task_section}"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    log.info("Running Planner Agent for project=%s", project_name)

    draft = await call_llm(
        "planner",
        messages,
        PlanDraft,
        db=db,
        now=now,
    )

    log.info(
        "Planner returned %d tasks, %d deps, %d warnings",
        len(draft.tasks),
        len(draft.dependencies),
        len(draft.warnings),
    )
    return draft
