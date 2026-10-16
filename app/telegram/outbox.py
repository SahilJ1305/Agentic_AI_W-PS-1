"""
app/telegram/outbox.py — async outbox worker.

Reads rows from the outbox table, sends them via the Telegram bot,
marks them sent/failed, respects Telegram rate limits (30 msg/s global,
1 msg/s per chat), and retries up to MAX_ATTEMPTS on transient errors.

Started as a background task in app/main.py lifespan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import RetryAfter, TelegramError

from app.api.sse import broadcaster
from app.config import settings
from app.db import repo

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_S = 1.0      # how often to check the outbox
PER_CHAT_DELAY_S = 0.05    # ~20 msg/s per chat, well within Telegram limits

# Replies to something the person just said are always sent.
# Check-ins, nudges and alerts wait out the quiet window (R16).
_REPLY_PREFIXES = ("ACK_", "CLARIFY_", "ASK_", "CONFIRM_", "VERIFY_", "DEPENDENCY_", "NOT_", "OFF_", "CORRECTION_", "PEER_")


async def run_outbox_worker(bot: Bot) -> None:
    """Main loop — call from the FastAPI lifespan as an asyncio task."""
    log.info("Outbox worker started")
    while True:
        try:
            await _tick(bot)
        except Exception:
            log.exception("Outbox worker tick error")
        await asyncio.sleep(POLL_INTERVAL_S)


async def _tick(bot: Bot) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with repo.db_context() as db:
        rows = await repo.fetch_queued_messages(db, now=now, limit=20)

    for row in rows:
        await asyncio.sleep(PER_CHAT_DELAY_S)

        if not str(row.get("template_key") or "").startswith(_REPLY_PREFIXES):
            paused_until = await _paused_until(row.get("participant_id"))
            if paused_until:
                async with repo.db_context() as db:
                    await repo.defer_outbox(db, row["id"], paused_until)
                log.info("Paused: deferred outbox %s until %s", row["id"], paused_until)
                continue
            async with repo.db_context() as db:
                last_sent = await repo.last_outbox_sent_at(db, row["chat_id"])
            if last_sent and _within_quiet_window(last_sent):
                resume_at = (
                    datetime.now(timezone.utc) + timedelta(minutes=settings.effective_quiet_min)
                ).isoformat()
                async with repo.db_context() as db:
                    await repo.defer_outbox(db, row["id"], resume_at)
                log.info("Quiet window: deferred outbox %s until %s", row["id"], resume_at)
                continue

        try:
            markup = _build_markup(row.get("buttons_json"))
            project_id = _get_project_id(row)
            async with repo.db_context() as db:
                tg_msg = await bot.send_message(
                    chat_id=row["chat_id"],
                    text=row["text"],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                msg_id = await repo.save_message(
                    db,
                    project_id=project_id,
                    participant_id=row.get("participant_id"),
                    direction="out",
                    telegram_message_id=tg_msg.message_id,
                    text=row["text"],
                    template_key=row["template_key"],
                    now=now,
                )
                await repo.mark_outbox_sent(db, row["id"], sent_message_id=msg_id)
                person = (
                    await repo.get_participant(db, row["participant_id"])
                    if row.get("participant_id") else None
                )
            await broadcaster.publish("message.out", {
                "project_id": project_id,
                "participant": person["name"] if person else "group",
                "text": row["text"],
                "template_key": row["template_key"],
            })

        except RetryAfter as e:
            log.warning("Telegram flood control: retry after %ss", e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramError as e:
            log.error("Telegram send error for outbox_id=%d: %s", row["id"], e)
            async with repo.db_context() as db:
                if row["attempts"] + 1 >= MAX_ATTEMPTS:
                    await repo.mark_outbox_permanent_failure(db, row["id"], error=str(e))
                else:
                    await repo.mark_outbox_failed(db, row["id"], error=str(e))


def _within_quiet_window(last_sent: str) -> bool:
    try:
        sent_at = datetime.fromisoformat(last_sent)
    except ValueError:
        return False
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - sent_at
    return age < timedelta(minutes=settings.effective_quiet_min)


def _build_markup(buttons_json: str | None) -> InlineKeyboardMarkup | None:
    if not buttons_json:
        return None
    try:
        raw = json.loads(buttons_json)
        if not raw:
            return None
        keyboard = [
            [InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
             for btn in row]
            for row in raw
        ]
        return InlineKeyboardMarkup(keyboard)
    except Exception:
        return None


def _get_project_id(row: dict) -> int:
    return row.get("project_id") or 1


async def _paused_until(participant_id: int | None) -> str | None:
    """If the person ran /pause, return when check-ins may resume (ISO), else None."""
    if not participant_id:
        return None
    async with repo.db_context() as db:
        person = await repo.get_participant(db, participant_id)
    until = (person or {}).get("paused_until")
    if not until:
        return None
    try:
        when = datetime.fromisoformat(until)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.isoformat() if when > datetime.now(timezone.utc) else None
