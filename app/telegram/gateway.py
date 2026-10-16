"""
app/telegram/gateway.py — python-telegram-bot Application, polling, command handlers.

Runs in polling mode (no webhook needed).
Commands handled: /start, /mytasks, /next, /status, /done, /blocked, /undo, /help
Inline-button callbacks: pq:<question_id>:<option_index>
"""
from __future__ import annotations

import asyncio
import functools
import html
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from telegram import BotCommand, ChatMember, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from app.config import settings
from app.db import repo
from app.core.notifications import buttons_for
from app.telegram.keyboards import parse_callback
from app.telegram.router import _revert_latest, apply_explicit_status, handle_message

log = logging.getLogger(__name__)

# Will be set by main.py lifespan
_sse_publish = None
_project_id: int = 1  # Tier 1: single project


# What /health and the dashboard show about the bot.
bot_state: dict = {"running": False, "username": None, "last_conflict": None}

BOT_COMMANDS = [
    ("start", "Join your project with your invite link"),
    ("mytasks", "Your tasks"),
    ("next", "Your next ready task"),
    ("status", "Project overview"),
    ("done", "Mark a task done: /done T3"),
    ("blocked", "Report a blocker: /blocked T3 reason"),
    ("undo", "Undo your last update"),
    ("pause", "Pause reminders: /pause 3 (hours)"),
    ("digest", "Post the project digest"),
    ("risk", "Post the risk report"),
    ("help", "What I understand"),
]


def on_poll_error(error: Exception) -> None:
    """Called by python-telegram-bot whenever polling fails."""
    if isinstance(error, Conflict):
        bot_state["last_conflict"] = time.monotonic()


def telegram_status() -> dict:
    """{'status': 'polling' | 'conflict' | 'disabled', 'username': str | None}"""
    if not bot_state["running"]:
        return {"status": "disabled", "username": None}
    recent = bot_state["last_conflict"]
    conflict = recent is not None and time.monotonic() - recent < 60
    return {"status": "conflict" if conflict else "polling", "username": bot_state["username"]}


async def configure_bot(application: Application) -> None:
    """After the bot connects: learn its real username, publish the command menu."""
    bot = application.bot
    bot_state.update(running=True, username=bot.username)
    if bot.username:
        settings.telegram_bot_username = bot.username   # invite links must point at THIS bot
    try:
        await bot.set_my_commands([BotCommand(name, text) for name, text in BOT_COMMANDS])
        await bot.set_my_short_description("Cadence keeps your group project on track: reply here with updates.")
    except Exception:
        log.warning("Could not publish the bot command menu", exc_info=True)


def mark_bot_stopped() -> None:
    bot_state.update(running=False)


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


def personal(handler):
    """
    Commands that talk about one person's tasks (/mytasks, /next, /status, /done, ...).
    In a group everyone would see the answer, so they only work in a private chat.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat.type != "private":
            await update.message.reply_text(
                "That one is personal. Message me directly and I'll show only your own tasks."
            )
            return
        await handler(update, context)
    return wrapper


# ── /start ────────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start <invite_code>."""
    chat_id = update.effective_chat.id
    args = context.args or []

    if update.effective_chat.type != "private":
        await update.message.reply_text("Message me directly to join: open my profile and tap Start.")
        return

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
        try:
            await repo.onboard_participant(
                db, participant["id"], chat_id=chat_id, onboarded_at=now
            )
        except sqlite3.IntegrityError:
            current = await repo.get_participant_by_chat_id(db, chat_id)
            await update.message.reply_text(
                f"This Telegram account is already linked to {current['name']} in another project. "
                "For now one account can join one project at a time.",
            )
            return

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

    await _publish("participant.joined", {
        "project_id": participant["project_id"],
        "participant": participant["name"],
        "participant_id": participant["id"],
    })
    await _publish("message.out", {
        "project_id": participant["project_id"],
        "participant": participant["name"],
        "text": welcome,
        "template_key": "ONBOARD_WELCOME",
    })


# ── /mytasks ──────────────────────────────────────────────────────────────────

@personal
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

@personal
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

@personal
async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await update.message.reply_text("You're not in this project. Use the invite link your lead shared.")
            return
        tasks = await repo.list_tasks(db, participant["project_id"])
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

@personal
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
    if reply:
        await update.message.reply_text(reply, parse_mode="HTML")


# ── /undo ─────────────────────────────────────────────────────────────────────

@personal
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
        "/pause 3 — no reminders for 3 hours (/pause 0 to resume)\n"
        "/digest, /risk — post a project report (lead, or in the team group)\n"
        "/linkgroup — lead only: send in the team group to receive the daily digest there\n"
        "\nOr just reply in plain English — I'll understand."
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── /blocked ──────────────────────────────────────────────────────────────────

@personal
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
    if reply:
        await update.message.reply_text(reply, parse_mode="HTML")


# ── Inline button callback ────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-button presses. Every button maps to a fixed action, so the LLM is never involved."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id
    now = await _now()

    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, chat_id)
        if not participant:
            await query.message.reply_text("I don't recognise you. Use the invite link your project lead shared.")
            return
        question = None
        try:
            asked = await repo.get_question(db, int(data.split(":")[1]))
            if asked and asked["participant_id"] == participant["id"]:
                question = asked          # the question this very button belongs to
        except (IndexError, ValueError):
            pass
        if not question or question["status"] != "open":
            await _clear_buttons(query)
            await query.message.reply_text("That question was already answered.")
            return
        try:
            payload = json.loads(question.get("payload_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        template_key = payload.get("_template_key", "")
        cb = parse_callback(data, buttons_for(template_key, payload) or ["Done", "In progress", "Blocked"])
        if cb is None:
            return
        choice = cb.option_text
        task = await repo.get_task(db, question["task_id"]) if question.get("task_id") else None
        blocker = None
        if payload.get("blocker", {}).get("id"):
            blocker = await repo.get_blocker(db, payload["blocker"]["id"])

    async def close() -> None:
        async with repo.db_context() as db:
            await repo.close_question(db, question["id"], answered_at=now)

    async def set_status(key: str, status: str, **extra) -> str:
        return await apply_explicit_status(
            participant_id=participant["id"],
            project_id=participant["project_id"],
            task_key=key,
            status=status,
            text=choice,
            telegram_message_id=query.message.message_id,
            sse_publish=_publish,
            question_id=question["id"],
            **extra,
        )

    reply: str | None = None

    if choice == "None of these":
        await close()
        reply = "Okay, I won't change a task."

    elif template_key == "PEER_CLAIM_CONFIRM":
        if choice == "Yes" and task and payload.get("_claimed_status"):
            await set_status(task["key"], payload["_claimed_status"])
        else:
            await close()
            reply = "Left that task unchanged."

    elif template_key == "UNBLOCK_REQUEST" and task:
        blocked = await _get_task(blocker["task_id"]) if blocker else None
        if choice == "Working on it":
            if task["status"] == "pending":
                await set_status(task["key"], "in_progress")
            else:
                await close()
            await _tell_blocked_owner(blocked, task, blocker, participant, "UNBLOCK_WORKING")
            reply = f"Thanks. I've told them you're on <b>{_escape(task['title'])}</b>."
        elif choice == "Already done":
            await set_status(task["key"], "complete")
        else:  # Not mine
            await close()
            await _tell_blocked_owner(blocked, task, blocker, participant, "UNBLOCK_DECLINED", lead_too=True)
            reply = "Okay, I've passed this to the lead to find the right person."

    elif template_key == "CONFIRM_UNBLOCKED" and task:
        if choice == "Yes unblocked":
            await set_status(task["key"], "in_progress", blocker_resolved=True)
        else:
            if blocker:
                async with repo.db_context() as db:
                    await repo.reopen_blocker(db, blocker["id"])
            await close()
            reply = "Okay, it stays Blocked. I'll keep chasing."

    elif template_key == "DEPENDENCY_CONFLICT" and task:
        await set_status(
            task["key"],
            "complete" if choice == "Yes it works" else "in_progress",
            confirmed=frozenset({"R6"} if choice == "Yes it works" else ()),
        )

    elif template_key == "CONFIRM_REOPEN" and task:
        if choice == "Yes reopen":
            await set_status(task["key"], "in_progress", confirmed=frozenset({"R8"}))
        else:
            await close()
            reply = "Okay, it stays Complete."

    elif template_key in ("VERIFY_COMPLETION", "GIT_UNVERIFIED"):
        await close()
        reply = "Okay. It stays Complete, marked unverified until you share a link."

    elif task and choice in _STATUS_BUTTONS:
        await set_status(task["key"], _STATUS_BUTTONS[choice])

    elif template_key == "CLARIFY_TASK":
        key = choice.split()[0].upper() if choice else ""
        if key.startswith("T") and key[1:].isdigit():
            source = str(payload.get("_source_text") or choice)
            await apply_explicit_status(
                participant_id=participant["id"],
                project_id=participant["project_id"],
                task_key=key,
                status="complete",
                text=source,
                telegram_message_id=query.message.message_id,
                sse_publish=_publish,
                question_id=question["id"],
            )
        else:
            await close()
            reply = "Okay, I won't change a task."

    else:
        await handle_message(
            participant_id=participant["id"],
            project_id=participant["project_id"],
            text=choice,
            telegram_message_id=query.message.message_id,
            sse_publish=_publish,
        )

    await _clear_buttons(query)
    if reply:
        await query.message.reply_text(reply, parse_mode="HTML")


_STATUS_BUTTONS = {
    "Done": "complete",
    "In progress": "in_progress",
    "Blocked": "blocked",
    "Not started": "pending",
}


async def _get_task(task_id: int):
    async with repo.db_context() as db:
        return await repo.get_task(db, task_id)


async def _clear_buttons(query) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass     # the message may be too old to edit; the answer still counts


async def _tell_blocked_owner(blocked, upstream, blocker, helper, template_key, lead_too: bool = False) -> None:
    """Tell whoever is waiting what the person they were waiting on said."""
    if not blocked:
        return
    from app.core.notifications import NotificationBatch

    now = await _now()
    async with repo.db_context() as db:
        batch = NotificationBatch()
        context = {
            "task": blocked,
            "upstream_task": upstream,
            "blocker": blocker or {},
            "upstream_owner": helper["name"],
        }
        if blocked.get("owner_id"):
            batch.add(participant_id=blocked["owner_id"], template_key=template_key, context=context)
        if lead_too:
            lead = await repo.get_lead(db, blocked["project_id"])
            owner = await repo.get_participant(db, blocked["owner_id"]) if blocked.get("owner_id") else None
            if lead:
                batch.add(
                    participant_id=lead["id"],
                    template_key="BLOCKER_ESCALATED",
                    context={**context, "reporter": (owner or {}).get("name", "The owner"), "minutes": "a few"},
                )
        await batch.flush(db, now=now)


# ── Plain message ─────────────────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return       # group chatter is a stretch goal (S1); commands still work there
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

    # Show "typing..." straight away; the reply follows once the message has been understood.
    asyncio.create_task(_typing(context.bot, chat_id))
    await handle_message(
        participant_id=participant["id"],
        project_id=participant["project_id"],
        text=text,
        telegram_message_id=update.message.message_id,
        sse_publish=_publish,
    )


async def _typing(bot, chat_id: int) -> None:
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        pass     # purely cosmetic


# ── /pause ────────────────────────────────────────────────────────────────────

@personal
async def pause_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop reminders for a while. Replies to things you say still work."""
    async with repo.db_context() as db:
        participant = await repo.get_participant_by_chat_id(db, update.effective_chat.id)
        if not participant:
            await update.message.reply_text("You're not in this project.")
            return
        args = context.args or []
        try:
            hours = float(args[0]) if args else 4.0
        except ValueError:
            await update.message.reply_text("Usage: /pause 3 (hours). /pause 0 turns reminders back on.")
            return
        hours = max(0.0, min(hours, 72.0))
        if hours == 0:
            await repo.set_paused_until(db, participant["id"], None)
            # messages held back while paused can go out now
            await db.execute(
                "UPDATE outbox SET not_before = NULL WHERE participant_id = ? AND status = 'queued'",
                (participant["id"],),
            )
            reply = "Reminders are back on."
        else:
            until = datetime.now(timezone.utc) + timedelta(hours=hours)
            await repo.set_paused_until(db, participant["id"], until.isoformat())
            reply = f"Paused for {hours:g} h. I won't send reminders until then. /pause 0 to resume."
    await update.message.reply_text(reply)
    await _publish("team.changed", {"project_id": participant["project_id"], "participant": participant["name"]})


# ── /digest, /risk, /linkgroup ────────────────────────────────────────────────

async def _report_context(update: Update):
    """Who is asking and for which project. Allowed: the lead anywhere, anyone in the linked group."""
    chat, user = update.effective_chat, update.effective_user
    async with repo.db_context() as db:
        sender = await repo.get_participant_by_chat_id(db, user.id) if user else None
        group_project = None
        if chat.type != "private":
            group_project = await repo.get_project_by_group(db, chat.id)
    if group_project:
        return group_project["id"], sender
    if sender and sender["role"] == "lead":
        return sender["project_id"], sender
    return None, sender


async def _send_report(update: Update, kind: str) -> None:
    from app.core.reports import generate_report

    project_id, sender = await _report_context(update)
    if project_id is None:
        await update.message.reply_text(
            "Only the project lead can ask for this, or anyone in the team group once the lead has run /linkgroup there."
            if sender else "You're not in a project yet. Use your invite link first."
        )
        return
    async with repo.db_context() as db:
        report = await generate_report(db, project_id, kind, post=False)
    await update.message.reply_text(report["telegram_html"], parse_mode="HTML")


async def digest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_report(update, "digest")


async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_report(update, "risk")


async def linkgroup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lead sends this inside the team group so digests are posted there."""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Add me to your team group, then send /linkgroup there.")
        return
    async with repo.db_context() as db:
        sender = await repo.get_participant_by_chat_id(db, update.effective_user.id)
        if not sender or sender["role"] != "lead":
            await update.message.reply_text("Only the project lead can link this group.")
            return
        await repo.set_project_group(db, sender["project_id"], chat.id)
        project = await repo.get_project(db, sender["project_id"])
    await update.message.reply_text(
        f"Linked. I'll post the daily digest for {project['name']} here. Anyone can use /digest and /risk in this group.",
    )
    await _publish("team.changed", {"project_id": sender["project_id"], "group_linked": True})


async def added_to_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    change = update.my_chat_member
    if not change or change.chat.type not in ("group", "supergroup"):
        return
    if change.new_chat_member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR) \
            and change.old_chat_member.status in (ChatMember.LEFT, ChatMember.BANNED):
        await context.bot.send_message(
            change.chat.id,
            "Hi, I'm Cadence. Project lead: send /linkgroup here so I post the daily digest in this group. "
            "Everyone else: message me directly with your invite link to join.",
        )


# ── Application builder ───────────────────────────────────────────────────────

def build_application(project_id: int = 1, bot=None) -> Application:
    """Build the bot. Tests pass `bot` (a fake) so no network is needed."""
    global _project_id
    _project_id = project_id

    builder = Application.builder()
    if bot is not None:
        builder = builder.bot(bot)
    else:
        builder = (
            builder.token(settings.telegram_bot_token)
            # Sending: patient, because a send that gives up early may still have been delivered.
            .request(HTTPXRequest(connection_pool_size=8, connect_timeout=15, read_timeout=30,
                                  write_timeout=30, pool_timeout=15))
            # Long-polling for updates holds a request open on purpose.
            .get_updates_request(HTTPXRequest(connection_pool_size=2, connect_timeout=15, read_timeout=40,
                                              write_timeout=20, pool_timeout=15))
        )
    app = builder.build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("mytasks", mytasks_handler))
    app.add_handler(CommandHandler("next", next_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("done", done_handler))
    app.add_handler(CommandHandler("blocked", blocked_handler))
    app.add_handler(CommandHandler("undo", undo_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("pause", pause_handler))
    app.add_handler(CommandHandler("digest", digest_handler))
    app.add_handler(CommandHandler("risk", risk_handler))
    app.add_handler(CommandHandler("linkgroup", linkgroup_handler))
    app.add_handler(ChatMemberHandler(added_to_group_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app
