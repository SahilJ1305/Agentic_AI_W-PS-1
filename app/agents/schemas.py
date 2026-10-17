"""
app/agents/schemas.py — Pydantic models for agent inputs/outputs.

These are the single source of truth (spec §10):
  - PlanDraft: Planner Agent output
  - Interpretation: Coordinator Agent output

Their model_json_schema() is passed to Ollama's `format` parameter
and embedded in the system prompt for OpenCode Console.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
#  Planner Agent output (spec §10.1)
# ══════════════════════════════════════════════════════════════════════════════

class PlannedMilestone(BaseModel):
    key: str                           # "M1"
    name: str
    due: str | None = None             # ISO 8601


class PlannedTask(BaseModel):
    key: str                           # "T1"
    title: str
    description: str
    acceptance: str
    milestone_key: str | None = None
    owner_name: str | None = None
    owner_confidence: float = Field(default=1.0, ge=0, le=1)
    deadline: str | None = None        # ISO 8601
    estimate_hours: float | None = None
    requires_evidence: bool = False


class PlannedDependency(BaseModel):
    upstream: str                      # must finish first
    downstream: str                    # waits for upstream
    type: Literal["hard", "soft"] = "hard"
    reason: str
    evidence_quote: str | None = None
    rule: str | None = None            # "pattern:credentials_before_integration"
    confidence: float = Field(default=1.0, ge=0, le=1)


class PlanDraft(BaseModel):
    project_name: str
    summary: str
    deadline: str | None = None
    milestones: list[PlannedMilestone] = []
    tasks: list[PlannedTask]
    dependencies: list[PlannedDependency] = []
    warnings: list[str] = []


# ══════════════════════════════════════════════════════════════════════════════
#  Coordinator Agent output (spec §10.2)
# ══════════════════════════════════════════════════════════════════════════════

class BlockerOut(BaseModel):
    description: str                    # ≤ 8 words
    kind: Literal["task", "person", "external"] = "external"
    suspected_task_key: str | None = None
    suspected_person: str | None = None
    match_confidence: float = Field(default=0.0, ge=0, le=1)


class TaskUpdate(BaseModel):
    task_key: str
    task_match_confidence: float = Field(default=1.0, ge=0, le=1)
    status: Literal["pending", "in_progress", "blocked", "complete"] | None = None
    status_confidence: float = Field(default=1.0, ge=0, le=1)
    progress_note: str | None = None
    eta: str | None = None             # ISO 8601 or None
    blocker: BlockerOut | None = None
    blocker_resolved: bool = False
    completion_evidence: str | None = None  # URL, PR ref, filename
    evidence: str | None = None        # quote from message justifying the status


class RelayOut(BaseModel):
    """Something the sender wants passed to another person ("tell Priya...", "@Rohan can you...")."""
    to: str = ""                        # a teammate's name, "lead", or "everyone"; "" when task_key says who
    text: str = ""                      # what to pass on, in the sender's own words
    task_key: str | None = None         # the task it is about, if any
    resolves_blocker: bool = False      # the LEAD says the blocker on task_key (or on `to`'s task) is cleared


IntentType = Literal[
    "status_update",
    "progress_note",
    "blocker_report",
    "correction",
    "handoff_request",
    "message_relay",
    "off_topic",
    "question",
]


class Interpretation(BaseModel):
    intent: IntentType = "status_update"
    updates: list[TaskUpdate] = []
    messages: list[RelayOut] = []      # messages for other people; may come with or without updates
    needs_clarification: bool = False
    clarification_question: str | None = None
    raw_message: str = ""              # echo for logging / dashboard "why" panel
