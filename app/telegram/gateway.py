"""
app/telegram/gateway.py — python-telegram-bot Application, polling, command handlers.

Runs in polling mode (no webhook needed).
Commands handled: /start, /mytasks, /next, /status, /done, /blocked, /undo, /help
Inline-button callbacks: pq:<question_id>:<option_index>
"""
from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from app.config import settings
from app.db import repo
from app.telegram.keyboards import parse_callback, BUTTONS
from app.telegram.router import handle_message

log = logging.getLogger(__name__)

# Will be set by main.py lifespan
_sse_publish = None
_project_id: int = 1  # Tier 1: single project


def set_sse_publish(fn) -> None:
    global _sse_publish
    _sse_publish = fn


async def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _escape(text: str) -> str:
    return html.escape(text)


# ── /start ────────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start <invite_code>."""
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Hi! I'm Cadence, the project coordinator. To join your project, use the invite link your lead shared.",
            parse_mode="HTML",
        )
        return

    invite_code = args[0]
    now = await _now()

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_invite(db, invite_code)
        if not participant:
            await update.message.reply_text(
                "That invite code isn't valid. Ask your lead for a new link.",
                parse_mode="HTML",
            )
            return

        if participant.get("telegram_chat_id") and participant["telegram_chat_id"] != chat_id:
            await update.message.reply_text(
                "This code has already been used by someone else. Ask your lead for a new one.",
                parse_mode="HTML",
            )
            return

        # Onboard
        await repo.onboard_participant(
            db, participant["id"], chat_id=chat_id, onboarded_at=now
        )

        tasks = await repo.list_tasks_for_owner(db, participant["id"])
        project = await repo.get_project(db, participant["project_id"])
        project_name = project["name"] if project else "your project"

    # Build task list
    task_lines = []
    for t in tasks:
        status_emoji = {
            "pending": "⏳",
            "in_progress": "🔄",
            "blocked": "🚫",
            "complete": "✅",
        }.get(t["status"], "•")
        task_lines.append(f"  {status_emoji} <b>{t['key']}</b> · {_escape(t['title'])}")

    task_list = "\n".join(task_lines) if task_lines else "  (no tasks assigned yet)"

    welcome = (
        f"Hi <b>{_escape(participant['name'])}</b>! I'm Cadence, the coordinator for <b>{_escape(project_name)}</b>.\n"
        f"I'll check in on your tasks and keep everyone in sync. You own:\n"
        f"{task_list}\n\n"
        f"Reply in plain words any time: \"done\", \"stuck on X\", \"kal tak ho jayega\".\n"
        f"Type /help to see all commands."
    )

    await update.message.reply_text(welcome, parse_mode="HTML")

    if _sse_publish:
        await _sse_publish("message.out", {
            "participant": participant["name"],
            "template_key": "ONBOARD_WELCOME",
        })


# ── /mytasks ──────────────────────────────────────────────────────────────────

async def mytasks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project. Use your invite link to join.")
            return
        tasks = await repo.list_tasks_for_owner(db, participant["id"])

    if not tasks:
        await update.message.reply_text("You have no tasks assigned.")
        return

    lines = ["<b>Your tasks:</b>"]
    for t in tasks:
        status_emoji = {"pending": "⏳", "in_progress": "🔄", "blocked": "🚫", "complete": "✅"}.get(t["status"], "•")
        readiness = " (waiting)" if t["readiness"] == "waiting" else ""
        lines.append(f"{status_emoji} <b>{t['key']}</b> · {_escape(t['title'])}{readiness}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /next ─────────────────────────────────────────────────────────────────────

async def next_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.core.next_task import pick_next_task
    chat_id = update.effective_chat.id
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return
        nxt = await pick_next_task(participant["id"], db)

    if nxt:
        await update.message.reply_text(
            f"Your next task: <b>{nxt['key']} · {_escape(nxt['title'])}</b>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("You have no ready tasks right now. You're all clear! 🎉")


# ── /status ───────────────────────────────────────────────────────────────────

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with repo.db_context() as db:
        tasks = await repo.list_tasks(db, _project_id)
    by_status = {}
    for t in tasks:
        by_status.setdefault(t["status"], []).append(t)
    lines = [f"<b>Project status:</b>"]
    for status, icon in [("complete", "✅"), ("in_progress", "🔄"), ("blocked", "🚫"), ("pending", "⏳")]:
        items = by_status.get(status, [])
        if items:
            lines.append(f"{icon} {status.replace('_', ' ').title()}: {len(items)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /done ─────────────────────────────────────────────────────────────────────

async def done_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit /done <key> — skips LLM, goes through Policy Engine."""
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /done T3", parse_mode="HTML")
        return

    key = args[0].upper()
    now = await _now()

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return
        task = await repo.get_task_by_key(db, _project_id, key)
        if not task or task.get("owner_id") != participant["id"]:
            await update.message.reply_text(f"Task {key} not found or not yours.")
            return

        # Artificial interpretation for the Policy Engine
        from app.agents.schemas import Interpretation, TaskUpdate
        interp = Interpretation(
            intent="status_update",
            updates=[TaskUpdate(
                task_key=key,
                task_match_confidence=1.0,
                status="complete",
                status_confidence=1.0,
                evidence=f"/done command by {participant['name']}",
            )],
        )

        async def _noop_publish(event, payload):
            if _sse_publish:
                await _sse_publish(event, payload)

        # Save message first
        msg_id = await repo.save_message(
            db,
            project_id=_project_id,
            participant_id=participant["id"],
            direction="in",
            text=f"/done {key}",
            now=now,
        )

        from app.core.policy import apply as policy_apply
        decision = await policy_apply(
            interpretation=interp,
            sender=participant,
            project_id=_project_id,
            source_message_id=msg_id,
            db=db,
            now=now,
        )
        from app.telegram.router import _execute_update
        for upd in decision.approved:
            await _execute_update(upd, _project_id, participant["id"], msg_id, db, now, _noop_publish)
        await decision.notifications.flush(db, now=now)

    await update.message.reply_text(f"<b>{key}</b> marked as Complete.", parse_mode="HTML")


# ── /undo ─────────────────────────────────────────────────────────────────────

async def undo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    now = await _now()

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return

        # Find the most recent status_changed event from this participant
        tasks = await repo.list_tasks_for_owner(db, participant["id"])
        last_event = None
        last_task = None
        for t in tasks:
            ev = await repo.get_latest_event(db, t["id"], actor="coordinator")
            if ev and ev["event_type"] == "status_changed":
                if last_event is None or ev["created_at"] > last_event["created_at"]:
                    last_event = ev
                    last_task = t

        if not last_event or not last_task:
            await update.message.reply_text("Nothing to undo.")
            return

        # Check undo window
        import datetime as dt_mod
        event_dt = dt_mod.datetime.fromisoformat(last_event["created_at"])
        now_dt = dt_mod.datetime.now(dt_mod.timezone.utc)
        age_min = (now_dt - event_dt).total_seconds() / 60
        if age_min > settings.undo_window_min:
            await update.message.reply_text(
                f"Undo window ({settings.undo_window_min} min) expired."
            )
            return

        # Revert: create a new event and restore old status
        reverted_status = last_event["old_value"]
        await repo.update_task_status(
            db, last_task["id"],
            status=reverted_status,
            updated_at=now,
        )
        revert_event_id = await repo.append_task_event(
            db,
            task_id=last_task["id"],
            event_type="reverted",
            old_value=last_event["new_value"],
            new_value=reverted_status,
            reason=f"Reverted by /undo",
            actor="coordinator",
            now=now,
        )
        await repo.mark_event_reverted(db, last_event["id"], revert_event_id=revert_event_id)

    await update.message.reply_text(
        f"Undone: <b>{last_task['title']}</b> is back to {reverted_status}.",
        parse_mode="HTML",
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Cadence commands:</b>\n"
        "/mytasks — see your tasks\n"
        "/next — your next ready task\n"
        "/status — project overview\n"
        "/done T3 — mark a task complete\n"
        "/blocked T3 reason — report a blocker\n"
        "/undo — revert your last update\n"
        "\nOr just reply in plain English — I'll understand."
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── /blocked ──────────────────────────────────────────────────────────────────

async def blocked_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /blocked T3 reason for being blocked", parse_mode="HTML")
        return
    key = args[0].upper()
    reason = " ".join(args[1:])
    text_for_router = f"/blocked {key}: {reason}"

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return

    await handle_message(
        participant_id=participant["id"],
        project_id=_project_id,
        text=text_for_router,
        telegram_message_id=update.message.message_id,
        sse_publish=_sse_publish or (lambda e, p: None),
    )


# ── Inline button callback ────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id
    now = await _now()

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            return

        open_pq = await repo.get_open_question(db, participant["id"])
        if not open_pq:
            await query.edit_message_text("This button has already been answered.")
            return

        template_key = open_pq.get("payload_json")
        buttons = BUTTONS.get("", [])
        cb = parse_callback(data, buttons)
        if cb is None:
            return

        option_text = cb.option_text

    # Route the button answer through the normal message handler
    await handle_message(
        participant_id=participant["id"],
        project_id=_project_id,
        text=option_text,
        telegram_message_id=query.message.message_id,
        sse_publish=_sse_publish or (lambda e, p: None),
    )

    await query.edit_message_reply_markup(reply_markup=None)


# ── Plain message ─────────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)

    if not participant:
        await update.message.reply_text(
            "I don't recognise you. Use the invite link your project lead shared."
        )
        return

    await handle_message(
        participant_id=participant["id"],
        project_id=_project_id,
        text=text,
        telegram_message_id=update.message.message_id,
        sse_publish=_sse_publish or (lambda e, p: None),
    )


# ── Application builder ───────────────────────────────────────────────────────

def build_application(project_id: int = 1) -> Application:
    global _project_id
    _project_id = project_id

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("mytasks", mytasks_handler))
    app.add_handler(CommandHandler("next", next_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("done", done_handler))
    app.add_handler(CommandHandler("blocked", blocked_handler))
    app.add_handler(CommandHandler("undo", undo_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app
