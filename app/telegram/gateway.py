"""
app/telegram/gateway.py — python-telegram-bot Application, polling, command handlers.

Runs in polling mode (no webhook needed).
Commands handled: /start, /mytasks, /next, /status, /done, /blocked, /undo, /help
Inline-button callbacks: pq:<question_id>:<option_index>
"""
from __future__ import annotations

import html
import json
import logging
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
from app.core.notifications import buttons_for
from app.telegram.keyboards import parse_callback
from app.telegram.router import _revert_latest, apply_explicit_status, handle_message

log = logging.getLogger(__name__)

# Will be set by main.py lifespan
_sse_publish = None
_project_id: int = 1  # Tier 1: single project


def set_sse_publish(fn) -> None:
    global _sse_publish
    _sse_publish = fn


async def _publish(event: str, payload: dict) -> None:
    if _sse_publish is not None:
        await _sse_publish(event, payload)


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

    await _publish("message.out", {
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
    chat_id = update.effective_chat.id
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        project_id = participant["project_id"] if participant else _project_id
        tasks = await repo.list_tasks(db, project_id)
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
    """Explicit /done <key> — skips the LLM and still goes through the Policy Engine."""
    chat_id = update.effective_chat.id
    args = context.args or []

    if not args:
        await update.message.reply_text("Usage: /done T3", parse_mode="HTML")
        return

    key = args[0].upper()
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
    if not participant:
        await update.message.reply_text("You're not in this project.")
        return

    reply = await apply_explicit_status(
        participant_id=participant["id"],
        project_id=participant["project_id"],
        task_key=key,
        status="complete",
        text=f"/done {key}",
        telegram_message_id=update.message.message_id,
        sse_publish=_publish,
    )
    await update.message.reply_text(reply, parse_mode="HTML")


# ── /undo ─────────────────────────────────────────────────────────────────────

async def undo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    now = await _now()
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return
        reply = await _revert_latest(
            db,
            participant,
            now=now,
            reason="Reverted by /undo",
            sse_publish=_publish,
        )
    await update.message.reply_text(reply, parse_mode="HTML")


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

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return

    reply = await apply_explicit_status(
        participant_id=participant["id"],
        project_id=participant["project_id"],
        task_key=key,
        status="blocked",
        text=f"/blocked {key}: {reason}",
        telegram_message_id=update.message.message_id,
        sse_publish=_publish,
        blocker_description=reason,
    )
    await update.message.reply_text(reply, parse_mode="HTML")


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

        try:
            payload = json.loads(open_pq.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        template_key = payload.get("_template_key", "")
        buttons = buttons_for(template_key, payload) or ["Done", "In progress", "Blocked"]
        cb = parse_callback(data, buttons)
        if cb is None:
            return
        option_text = cb.option_text
        task = await repo.get_task(db, open_pq["task_id"]) if open_pq.get("task_id") else None

    status_from_button = {
        "Done": "complete",
        "In progress": "in_progress",
        "Blocked": "blocked",
        "Not started": "pending",
        "Yes it works": "complete",
        "Not fully": "in_progress",
    }
    if option_text == "Yes" and payload.get("_claimed_status") and task:
        status_from_button = {**status_from_button, "Yes": payload["_claimed_status"]}
    if option_text == "None of these":
        await query.message.reply_text("Okay, I won't change a task.")
        return
    chosen_key = option_text.split()[0].upper() if option_text else ""
    if task is None and chosen_key.startswith("T") and chosen_key[1:].isdigit():
        source = str(payload.get("_source_text") or option_text)
        reply = await apply_explicit_status(
            participant_id=participant["id"],
            project_id=participant["project_id"],
            task_key=chosen_key,
            status="complete",
            text=source,
            telegram_message_id=query.message.message_id,
            sse_publish=_publish,
        )
        await query.message.reply_text(reply)
        await query.edit_message_reply_markup(reply_markup=None)
        return
    if option_text == "No" and payload.get("_template_key") == "PEER_CLAIM_CONFIRM":
        await query.message.reply_text("Left that task unchanged.")
        return
    if task and option_text in status_from_button:
        await apply_explicit_status(
            participant_id=participant["id"],
            project_id=participant["project_id"],
            task_key=task["key"],
            status=status_from_button[option_text],
            text=option_text,
            telegram_message_id=query.message.message_id,
            sse_publish=_publish,
        )
    else:
        await handle_message(
            participant_id=participant["id"],
            project_id=participant["project_id"],
            text=option_text,
            telegram_message_id=query.message.message_id,
            sse_publish=_publish,
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
        project_id=participant["project_id"],
        text=text,
        telegram_message_id=update.message.message_id,
        sse_publish=_publish,
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
