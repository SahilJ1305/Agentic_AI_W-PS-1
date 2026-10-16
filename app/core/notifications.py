"""
app/core/notifications.py — message batching, template rendering, outbox write.

The NotificationBatch accumulates messages during one propagation event.
flush() merges per recipient (one message per person per event) and writes
to the outbox table.

Templates are loaded from app/templates/messages.yaml.
"""
from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import aiosqlite

from app.db import repo

log = logging.getLogger(__name__)

_TEMPLATES_PATH = Path(__file__).parent.parent / "templates" / "messages.yaml"
_TEMPLATES: dict | None = None


def _load_templates() -> dict:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = yaml.safe_load(_TEMPLATES_PATH.read_text())
    return _TEMPLATES


# ── Inline keyboards ───────────────────────────────────────────────────────────

BUTTONS: dict[str, list[str]] = {
    "FOLLOWUP_SINGLE":      ["Done", "In progress", "Blocked"],
    "NUDGE_1":              ["Done", "In progress", "Blocked", "Not started"],
    "ACK_COMPLETE_NEXT":    ["Starting now", "Later"],
    "UNBLOCKED_DOWNSTREAM": ["Starting now", "Later"],
    "CONFIRM_UNBLOCKED":    ["Yes unblocked", "Still blocked"],
    "CLARIFY_STATUS":       ["Done", "In progress", "Blocked"],
    "DEPENDENCY_CONFLICT":  ["Yes it works", "Not fully"],
    "PEER_CLAIM_CONFIRM":   ["Yes", "No"],
    "CONFIRM_REOPEN":       ["Yes reopen", "No keep it done"],
    "VERIFY_COMPLETION":    ["No link"],
    "UNBLOCK_REQUEST":      ["Working on it", "Already done", "Not mine"],
    "NOT_UNDERSTOOD":       ["Done", "In progress", "Blocked", "Different task"],
}


def buttons_for(template_key: str, context: dict | None = None) -> list[str]:
    """Fixed buttons, or one button per open task for CLARIFY_TASK."""
    if template_key == "CLARIFY_TASK":
        labels = []
        for task in (context or {}).get("tasks") or []:
            if task.get("status") == "complete":
                continue
            label = f"{task.get('key', '')} {task.get('title', '')}".strip()
            labels.append(label[:40])
        return labels + ["None of these"]
    return list(BUTTONS.get(template_key, []))


def build_inline_keyboard(template_key: str, question_id: int, context: dict | None = None) -> str:
    """
    Build inline keyboard JSON for a template.
    Callback data format: pq:<question_id>:<option_index>
    Telegram limits callback_data to 64 bytes.
    """
    buttons = buttons_for(template_key, context)
    if not buttons:
        return json.dumps([])
    keyboard = [
        [{"text": btn, "callback_data": f"pq:{question_id}:{i}"}]
        for i, btn in enumerate(buttons)
    ]
    return json.dumps(keyboard)


# ── Template rendering ─────────────────────────────────────────────────────────

def _esc(v: Any) -> str:
    """HTML-escape a value for Telegram parse_mode=HTML."""
    return html.escape(str(v)) if v is not None else ""


def render_template(template_key: str, context: dict) -> str:
    """
    Render a message template with the given context.
    Falls back to a plain-text summary if the template is not found.
    """
    templates = _load_templates()
    tmpl = templates.get(template_key)
    if not tmpl:
        log.warning("Template not found: %s", template_key)
        return f"[{template_key}]"

    text: str = tmpl.get("text", "")

    # Build replacement map — escape all user-generated strings
    def _rel(deadline: str | None) -> str:
        if not deadline:
            return "no deadline"
        try:
            import datetime
            from zoneinfo import ZoneInfo
            dl = datetime.datetime.fromisoformat(deadline)
            now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
            diff = dl - now
            hours = int(diff.total_seconds() / 3600)
            if hours < 0:
                return "overdue"
            if hours == 0:
                return "in less than 1 h"
            if hours < 24:
                return f"in {hours} h"
            return f"in {hours // 24} d"
        except Exception:
            return str(deadline)

    task = context.get("task", {})
    upstream = context.get("upstream_task", {})
    next_task = context.get("next_task", {})
    blocker = context.get("blocker", {})
    participant = context.get("participant", {})

    replacements = {
        "{name}":            _esc(participant.get("name", context.get("name", ""))),
        "{project}":         _esc(context.get("project", "the project")),
        "{task_key}":        _esc(task.get("key", "")),
        "{task_title}":      _esc(task.get("title", "")),
        "{deadline_rel}":    _rel(task.get("deadline")),
        "{task_list}":       _esc(context.get("task_list", "")),
        "{numbered_task_list}": _esc(context.get("numbered_task_list", "")),
        "{upstream_title}":  _esc(upstream.get("title", "")),
        "{upstream_owner}":  _esc(context.get("upstream_owner", "")),
        "{upstream_status}": _esc(upstream.get("status", "")),
        "{next_key}":        _esc(next_task.get("key", "")) if next_task else "",
        "{next_title}":      _esc(next_task.get("title", "")) if next_task else "",
        "{next_deadline_rel}": _rel(next_task.get("deadline")) if next_task else "",
        "{blocker}":         _esc(blocker.get("description", context.get("blocker_desc", ""))),
        "{unblocker}":       _esc(context.get("unblocker", "")),
        "{upstream_title}":  _esc(upstream.get("title", "")),
        "{lead}":            _esc(context.get("lead", "the lead")),
        "{status}":          _esc(context.get("status", "")),
        "{eta_part}":        f", ETA {_esc(task.get('eta'))}" if task.get("eta") else "",
        "{unblocked_part}":  _esc(context.get("unblocked_part", "")),
        "{offer_part}":      _esc(context.get("offer_part", "")),
        "{routing_part}":    _esc(context.get("routing_part", "")),
        "{reporter}":        _esc(context.get("reporter", "")),
        "{claimed_status}":  _esc(context.get("claimed_status", "")),
        "{reason}":          _esc(context.get("reason", "")),
        "{minutes}":         _esc(context.get("minutes", "")),
        "{critical_path_note}": " (critical path)" if task.get("on_critical_path") else "",
        "{suggested_owner}": _esc(context.get("suggested_owner", "")),
        "{skills}":          _esc(context.get("skills", "")),
        "{open_count}":      _esc(context.get("open_count", "")),
        "{milestone}":       _esc(context.get("milestone", "")),
        "{done}":            _esc(context.get("done_count", "")),
        "{total}":           _esc(context.get("total_count", "")),
        "{clarification_question}": _esc(context.get("clarification_question", "")),
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    return text.strip()


# ── Batch ──────────────────────────────────────────────────────────────────────

@dataclass
class _QueuedMessage:
    participant_id: int
    template_key: str
    context: dict
    dedupe_key: str | None = None
    question_kind: str | None = None  # if this message should create a pending_question
    question_task_id: int | None = None


@dataclass
class NotificationBatch:
    _messages: list[_QueuedMessage] = field(default_factory=list)

    def add(
        self,
        *,
        participant_id: int | None,
        template_key: str,
        context: dict,
        dedupe_key: str | None = None,
        question_kind: str | None = None,
        question_task_id: int | None = None,
    ) -> None:
        if participant_id is None:
            return
        self._messages.append(
            _QueuedMessage(
                participant_id=participant_id,
                template_key=template_key,
                context=context,
                dedupe_key=dedupe_key,
                question_kind=question_kind,
                question_task_id=question_task_id,
            )
        )

    async def flush(
        self,
        db: aiosqlite.Connection,
        now: str,
        source_msg_id: int | None = None,
    ) -> None:
        """
        Merge per recipient (one message per person per event), write to outbox.
        If a message should create a pending_question, do that first to get the ID
        (needed for callback data).
        """
        # Merge: group by (participant_id, template_key)
        seen: set[tuple] = set()

        for msg in self._messages:
            key = (msg.participant_id, msg.template_key, msg.dedupe_key)
            if key in seen:
                continue
            seen.add(key)

            participant = await repo.get_participant(db, msg.participant_id)
            if not participant or not participant.get("telegram_chat_id"):
                log.debug("Skipping outbox for unboarded participant %d", msg.participant_id)
                continue

            chat_id = participant["telegram_chat_id"]

            # Create pending question if needed
            pq_id: int | None = None
            if msg.question_kind:
                payload = dict(msg.context)
                payload["_template_key"] = msg.template_key
                pq_id = await repo.create_pending_question(
                    db,
                    participant_id=msg.participant_id,
                    task_id=msg.question_task_id,
                    kind=msg.question_kind,
                    payload_json=json.dumps(payload, default=str),
                    now=now,
                )

            # Render text
            ctx = dict(msg.context)
            ctx["participant"] = participant
            ctx.setdefault("name", participant.get("name", ""))
            text = render_template(msg.template_key, ctx)

            # Build buttons
            buttons_json: str | None = None
            labels = buttons_for(msg.template_key, ctx)
            if pq_id and labels:
                buttons_json = build_inline_keyboard(msg.template_key, pq_id, ctx)

            outbox_id = await repo.enqueue_message(
                db,
                participant_id=msg.participant_id,
                chat_id=chat_id,
                template_key=msg.template_key,
                text=text,
                buttons_json=buttons_json,
                dedupe_key=msg.dedupe_key,
                now=now,
            )
            if outbox_id is None:
                log.debug("Dedupe hit for key=%s", msg.dedupe_key)

            # Update the pending_question with the outbox message_id
            # (message_id is set when the outbox worker records the sent message)
