"""Log filters: the bot token never reaches the logs, and 409 Conflict spam is collapsed."""
from __future__ import annotations

import logging
import sys

from telegram.error import Conflict

from app.telegram.log_filters import RedactBotToken, SummariseConflict

TOKEN = "123456789:AAH-secret_token_value"


def _record(msg, args=(), exc=None, level=logging.INFO):
    exc_info = None
    if exc is not None:
        try:
            raise exc
        except type(exc):
            exc_info = sys.exc_info()
    return logging.LogRecord("t", level, __file__, 1, msg, args, exc_info)


def test_token_is_redacted_from_httpx_style_records():
    record = _record(
        'HTTP Request: %s %s "%s"',
        ("POST", f"https://api.telegram.org/bot{TOKEN}/getUpdates", "HTTP/1.1 200 OK"),
    )
    assert RedactBotToken().filter(record)
    text = record.getMessage()
    assert TOKEN not in text and "AAH" not in text
    assert "https://api.telegram.org/bot<redacted>/getUpdates" in text
    plain = _record("Scheduler started")
    RedactBotToken().filter(plain)
    assert plain.getMessage() == "Scheduler started"


def test_conflict_spam_collapses_to_one_warning_per_minute():
    flt = SummariseConflict()
    first = _record("Exception happened while polling for updates.", exc=Conflict("terminated"), level=logging.ERROR)
    assert flt.filter(first)
    assert first.levelno == logging.WARNING and first.exc_info is None
    assert "another program is polling" in first.getMessage()

    again = _record("Exception happened while polling for updates.", exc=Conflict("terminated"), level=logging.ERROR)
    assert flt.filter(again) is False

    other = _record("Exception happened while polling for updates.", exc=RuntimeError("boom"), level=logging.ERROR)
    assert flt.filter(other) is True and other.exc_info is not None   # real errors still show
