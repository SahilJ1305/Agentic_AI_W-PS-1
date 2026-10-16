"""
app/agents/fastpath.py — answer the most common one-word replies without the LLM.

"done", "ho gaya", "started", "working on it" are unambiguous when the person has exactly
one open task (or just answered a check-in about one). Calling the model for them costs
3-8 seconds for no gain. Anything with a reason, a link, a time, a second task or a
question still goes to the Coordinator Agent, and every result still passes the Policy Engine.
"""
from __future__ import annotations

import re

from app.agents.schemas import Interpretation, TaskUpdate

_DONE = re.compile(
    r"^[\W_]*(done|finished|completed?|ho ?gaya( bhai)?|ho ?gya|done hai|all done|✅|👍)[\W_]*$",
    re.IGNORECASE,
)
_STARTED = re.compile(
    r"^[\W_]*(started|i started|working on it|on it|in progress|working|chal raha hai|kaam chal raha hai)[\W_]*$",
    re.IGNORECASE,
)

# Only these questions are answered by a plain status word. For the others ("share a link",
# "does that clear your blocker?", ...) the same word means something different.
_PLAIN_STATUS_QUESTIONS = {"status_check", "clarify_status"}


def quick_interpretation(
    text: str,
    *,
    sender_tasks: list[dict],
    pending_question: dict | None,
) -> Interpretation | None:
    """Return an Interpretation for an unambiguous one-word status, or None to ask the LLM."""
    text = (text or "").strip()
    if not text or len(text) > 40 or "\n" in text:
        return None
    if _DONE.match(text):
        status = "complete"
    elif _STARTED.match(text):
        status = "in_progress"
    else:
        return None

    if pending_question and pending_question.get("kind") not in _PLAIN_STATUS_QUESTIONS:
        return None
    open_tasks = [t for t in sender_tasks if t["status"] != "complete"]
    if pending_question and pending_question.get("task_id"):
        task = next((t for t in sender_tasks if t["id"] == pending_question["task_id"]), None)
    elif len(open_tasks) == 1:
        task = open_tasks[0]
    else:
        return None                          # several open tasks: the router asks which one
    if task is None or task["status"] == "complete":
        return None
    if status == "in_progress" and task["status"] == "in_progress":
        return None                          # nothing to change; let the model read any nuance

    return Interpretation(
        intent="status_update",
        updates=[TaskUpdate(
            task_key=task["key"],
            task_match_confidence=0.97,
            status=status,
            status_confidence=0.97,
            evidence=text,
        )],
    )
