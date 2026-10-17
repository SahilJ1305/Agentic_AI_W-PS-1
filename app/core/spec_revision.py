"""
app/core/spec_revision.py — turn spec v1 + meeting notes (Fireflies JSON) into spec v2.

One LLM call returns the whole revised spec plus a change list for the lead to review. Nothing is
saved here: the lead applies v2 by uploading it as a new spec, which keeps v1 unchanged and lets the
normal importer add the new tasks without touching live statuses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import aiosqlite
from pydantic import BaseModel, Field

from app.core.documents import parse_task_table, parse_team
from app.llm.gateway import call_llm

_SYSTEM_PROMPT = (Path(__file__).parent.parent / "agents" / "prompts" / "spec_revision_system.md").read_text(encoding="utf-8")
_MAX_NOTES_CHARS = 16_000


class SpecChange(BaseModel):
    kind: Literal["added", "changed", "removed"]
    section: str = ""
    summary: str
    source: str = ""


class SpecRevision(BaseModel):
    spec_md: str = Field(description="The complete revised spec in Markdown")
    changes: list[SpecChange] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class RevisionError(ValueError):
    """The meeting file or the model's answer cannot be used."""


def meeting_notes(data) -> str:
    """
    Plain-text digest of a meeting export. Understands the summary format (executive_summary,
    key_discussion_points, detected_changes, action_items) and the Fireflies API shape
    (summary.overview / action_items, sentences[]); anything else is passed through as JSON.
    """
    if not isinstance(data, dict):
        raise RevisionError("The meeting file must be a JSON object.")
    data = data.get("data", {}).get("transcript", data) if isinstance(data.get("data"), dict) else data
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    out: list[str] = []

    def add(title: str, value) -> None:
        if not value:
            return
        if isinstance(value, str):
            out.extend([f"## {title}", value.strip(), ""])
            return
        out.append(f"## {title}")
        for item in value:
            if isinstance(item, dict):
                out.append("- " + "; ".join(f"{k}: {v}" for k, v in item.items() if v not in (None, "")))
            else:
                out.append(f"- {item}")
        out.append("")

    add("Title", data.get("title"))
    add("Summary", data.get("executive_summary") or summary.get("overview") or summary.get("short_summary")
        or (data.get("summary") if isinstance(data.get("summary"), str) else None))
    add("Key discussion points", data.get("key_discussion_points") or summary.get("shorthand_bullet")
        or summary.get("bullet_gist"))
    add("Detected changes", data.get("detected_changes"))
    add("Decisions", data.get("decisions"))
    action_items = data.get("action_items") or summary.get("action_items")
    add("Action items", action_items.splitlines() if isinstance(action_items, str) else action_items)

    sentences = data.get("sentences")
    if isinstance(sentences, list) and sentences:
        lines = [f"{s.get('speaker_name') or 'Speaker'}: {s.get('text', '')}" for s in sentences if isinstance(s, dict)]
        add("Transcript", "\n".join(lines))
    elif isinstance(data.get("transcript"), str):
        add("Transcript", data["transcript"])

    text = "\n".join(out).strip() or json.dumps(data, ensure_ascii=False, indent=1)
    if len(text) > _MAX_NOTES_CHARS:
        text = text[:_MAX_NOTES_CHARS] + "\n[transcript cut for length]"
    return text


async def revise_spec(
    *, spec_v1: str, meeting: dict, project_name: str, now: str, db: aiosqlite.Connection,
) -> tuple[SpecRevision, list[str]]:
    """Ask the model for spec v2. Returns the revision and warnings about what v2 lost."""
    notes = meeting_notes(meeting)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"PROJECT: {project_name}\nNOW: {now}\n\nSPEC V1:\n{spec_v1}\n\nMEETING NOTES:\n{notes}"},
    ]
    revision: SpecRevision = await call_llm("planner", messages, SpecRevision, db=db, now=now)
    return revision, check_revision(spec_v1, revision)


def check_revision(spec_v1: str, revision: SpecRevision) -> list[str]:
    """Catch a v2 that would break the importer or silently drop people or tasks."""
    v1_tasks = {t["key"] for t in parse_task_table(spec_v1)}
    v2_tasks = {t["key"] for t in parse_task_table(revision.spec_md)}
    if v1_tasks and not v2_tasks:
        raise RevisionError("The model returned a spec without a readable Tasks table. Try again.")
    warnings = []
    removed = {c.summary for c in revision.changes if c.kind == "removed"}
    lost = sorted(v1_tasks - v2_tasks, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)
    if lost and not removed:
        warnings.append(f"V2 no longer lists {', '.join(lost)} but the change list does not say why.")
    v1_people = {p["name"].lower() for p in parse_team(spec_v1)}
    v2_people = {p["name"].lower() for p in parse_team(revision.spec_md)}
    if v1_people - v2_people:
        warnings.append(f"V2 dropped team members: {', '.join(sorted(v1_people - v2_people))}.")
    if lost:
        warnings.append("Applying v2 never deletes tasks; remove dropped ones from the board yourself if needed.")
    return warnings
