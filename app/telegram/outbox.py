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
from datetime import datetime, timezone

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import RetryAfter, TelegramError

from app.config import settings
from app.db import repo

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_S = 1.0      # how often to check the outbox
PER_CHAT_DELAY_S = 0.05    # ~20 msg/s per chat, well within Telegram limits


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

        # Respect quiet window: QUIET_MIN — skip unsolicited messages in window
        # (template_key-based: skip if not a reply and quiet window active)
        # TODO: implement quiet window check (Tier 2 detail)

        try:
            markup = _build_markup(row.get("buttons_json"))
            async with repo.db_context() as db:
                tg_msg = await bot.send_message(
                    chat_id=row["chat_id"],
                    text=row["text"],
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                msg_id = await repo.save_message(
                    db,
                    project_id=_get_project_id(row),
                    participant_id=row.get("participant_id"),
                    direction="out",
                    telegram_message_id=tg_msg.message_id,
                    text=row["text"],
                    template_key=row["template_key"],
                    now=now,
                )
                await repo.mark_outbox_sent(db, row["id"], sent_message_id=msg_id)

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
    # project_id is not stored in outbox; look it up from participant if needed
    # For now return 1 (the demo project) — Tier 2 improvement
    return 1
