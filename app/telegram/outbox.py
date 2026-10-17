"""
app/telegram/outbox.py — async outbox worker.

Reads rows from the outbox table, sends them via the Telegram bot, marks them
sent/failed, and respects Telegram rate limits.

Why this is careful about retries: Telegram has no idempotency keys. If a send
times out *after* the request left, the message is often already delivered, and
sending it again shows the person the same message twice. So:

  - A row is claimed (attempt counted, short lease) BEFORE sending, so a crash or a
    slow tick can never send it a second time straight away.
  - Errors where Telegram never saw the request (could not connect, pool busy) are
    retried with backoff.
  - Errors where it might have been delivered (read/write timeout, dropped connection)
    are NOT retried: the row is closed as "unconfirmed" and the worker moves on.
  - Errors Telegram answered with (blocked bot, bad request) are permanent.
  - Anything that goes wrong AFTER a successful send (database bookkeeping) is retried
    on its own and can never cause a resend.

Started as a background task in app/main.py lifespan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

from app.api.sse import broadcaster
from app.config import settings
from app.db import repo

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_S = 0.25     # how often to check the outbox (replies feel instant)
PER_CHAT_DELAY_S = 0.05    # ~20 msg/s per chat, well within Telegram limits
LEASE_S = 90               # a claimed row is not picked up again for this long
BACKOFF_S = (3, 10)        # wait before retry 2 and retry 3 (safe errors only)

# Replies to something the person just said are always sent.
# Check-ins, nudges and alerts wait out the quiet window (R16).
_REPLY_PREFIXES = ("ACK_", "CLARIFY_", "ASK_", "CONFIRM_", "VERIFY_", "DEPENDENCY_", "NOT_", "OFF_", "CORRECTION_", "PEER_", "GIT_",
                   "RELAY_", "BLOCKER_CLEARED", "LEAD_")


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

        # Claim the row before touching the network.
        lease = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_S)).isoformat()
        async with repo.db_context() as db:
            if not await repo.claim_outbox(db, row["id"], lease_until=lease):
                continue
        attempt = row["attempts"] + 1

        try:
            tg_msg = await bot.send_message(
                chat_id=row["chat_id"],
                text=row["text"],
                parse_mode="HTML",
                reply_markup=_build_markup(row.get("buttons_json")),
            )
        except RetryAfter as e:
            log.warning("Telegram flood control: retry after %ss", e.retry_after)
            await _retry_later(row["id"], delay=float(e.retry_after) + 1, error="flood control", count=False)
            await asyncio.sleep(min(float(e.retry_after), 30))
        except (BadRequest, Forbidden) as e:
            # Telegram answered: the chat is gone, the bot is blocked, or the text is invalid.
            log.error("Telegram rejected outbox_id=%d for good: %s", row["id"], e)
            await _close(row["id"], f"rejected: {e}")
        except TelegramError as e:
            if _never_reached_telegram(e) and attempt < MAX_ATTEMPTS:
                delay = BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]
                log.warning("Could not reach Telegram for outbox_id=%d (%s); retry in %ss", row["id"], e, delay)
                await _retry_later(row["id"], delay=delay, error=str(e))
            elif _never_reached_telegram(e):
                log.error("Giving up on outbox_id=%d after %d attempts: %s", row["id"], attempt, e)
                await _close(row["id"], f"unreachable: {e}")
            else:
                # The request may have been delivered. Resending could show a duplicate.
                log.warning(
                    "Send for outbox_id=%d (%s) was cut off (%s); delivery unconfirmed, NOT resending",
                    row["id"], row["template_key"], e,
                )
                await _close(row["id"], f"unconfirmed: {e}")
        else:
            await _record_sent(row, tg_msg.message_id)


def _never_reached_telegram(error: TelegramError) -> bool:
    """True only when the request provably did not arrive, so a retry cannot duplicate it."""
    cause = error.__cause__
    return isinstance(cause, (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError)) and not isinstance(
        cause, (httpx.ReadTimeout, httpx.WriteTimeout)
    )


async def _retry_later(outbox_id: int, *, delay: float, error: str, count: bool = True) -> None:
    when = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    async with repo.db_context() as db:
        await repo.release_outbox(db, outbox_id, not_before=when, error=error, refund_attempt=not count)


async def _close(outbox_id: int, error: str) -> None:
    async with repo.db_context() as db:
        await repo.mark_outbox_permanent_failure(db, outbox_id, error=error)


async def _record_sent(row: dict, telegram_message_id: int) -> None:
    """Bookkeeping after a successful send. Retried on its own; never triggers a resend."""
    project_id = _get_project_id(row)
    now = datetime.now(timezone.utc).isoformat()
    for attempt in range(1, 4):
        try:
            async with repo.db_context() as db:
                msg_id = await repo.save_message(
                    db,
                    project_id=project_id,
                    participant_id=row.get("participant_id"),
                    direction="out",
                    telegram_message_id=telegram_message_id,
                    text=row["text"],
                    template_key=row["template_key"],
                    now=now,
                )
                await repo.mark_outbox_sent(db, row["id"], sent_message_id=msg_id)
                person = (
                    await repo.get_participant(db, row["participant_id"])
                    if row.get("participant_id") else None
                )
            break
        except Exception:
            log.exception("Could not record sent outbox_id=%s (try %d)", row["id"], attempt)
            await asyncio.sleep(0.2 * attempt)
    else:
        # Last resort: at least stop the row from being sent again.
        try:
            async with repo.db_context() as db:
                await db.execute("UPDATE outbox SET status = 'sent' WHERE id = ?", (row["id"],))
        except Exception:
            log.exception("Could not even close outbox_id=%s; it may be sent again after the lease", row["id"])
        return
    try:
        await broadcaster.publish("message.out", {
            "project_id": project_id,
            "participant": person["name"] if person else "group",
            "text": row["text"],
            "template_key": row["template_key"],
        })
    except Exception:
        log.exception("Could not publish message.out")


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
