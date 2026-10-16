"""Small time helpers shared by risk rules, reports and the escalation ladder."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_ts(value: str | None) -> datetime | None:
    """Parse the timestamps we store (ISO with offset, 'Z', or SQLite 'YYYY-MM-DD HH:MM:SS' = UTC)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def human_duration(delta: timedelta) -> str:
    seconds = abs(delta.total_seconds())
    if seconds < 90:
        return "under a minute" if seconds < 45 else "1 min"
    minutes = seconds / 60
    if minutes < 90:
        return f"{round(minutes)} min"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.0f} h" if hours >= 10 else f"{hours:.1f} h".replace(".0 h", " h")
    return f"{hours / 24:.0f} d"


def human_rel(when: datetime | None, now: datetime) -> str:
    """'in 6 h', '2 h ago', or 'no deadline'."""
    if when is None:
        return "no deadline"
    delta = when - now
    text = human_duration(delta)
    return f"in {text}" if delta.total_seconds() >= 0 else f"{text} ago"
