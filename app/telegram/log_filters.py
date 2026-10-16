"""
app/telegram/log_filters.py — keep the Telegram logs readable and free of secrets.

  - httpx logs every request URL, and Telegram puts the bot token in that URL
    (https://api.telegram.org/bot<id>:<secret>/getUpdates). Redact it.
  - When a second program polls the same token, Telegram answers 409 Conflict
    every few seconds and python-telegram-bot logs a full stack trace each time.
    Collapse that into one explanatory warning per minute.
"""
from __future__ import annotations

import logging
import re
import time

from telegram.error import Conflict

_TOKEN = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")
_CONFLICT_EVERY_S = 60.0


class RedactBotToken(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/bot" in message:
            record.msg = _TOKEN.sub("/bot<redacted>", message)
            record.args = ()
        return True


class SummariseConflict(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self._last_logged = float("-inf")

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if not isinstance(exc, Conflict):
            return True
        now = time.monotonic()
        if now - self._last_logged < _CONFLICT_EVERY_S:
            return False
        self._last_logged = now
        record.levelno, record.levelname = logging.WARNING, "WARNING"
        record.msg = (
            "Telegram 409 Conflict: another program is polling this bot token, so each "
            "side keeps knocking the other off. Stop the other copy (teammate, server, "
            "other laptop) or give it its own bot, or revoke the token in @BotFather. "
            "Repeats are hidden for %d s."
        )
        record.args = (int(_CONFLICT_EVERY_S),)
        record.exc_info = record.exc_text = None
        return True


def install() -> None:
    """Attach the filters. Call once after logging.basicConfig()."""
    logging.getLogger("httpx").addFilter(RedactBotToken())
    logging.getLogger("telegram.ext.Updater").addFilter(SummariseConflict())
