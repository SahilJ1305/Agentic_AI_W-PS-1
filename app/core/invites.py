"""
app/core/invites.py — who an invite belongs to, and whether the saved username agrees with who joined.

A lead can save a Telegram username for a person; from then on only that account may join with the
invite. After someone has joined, the saved username has to stay consistent with the account that
actually joined, otherwise the dashboard says "only @OmkarS can use this" about a person who joined
as @SSJagtap20. Rules:

  - Nobody has joined yet                      -> any username may be saved.
  - They joined and have a Telegram username   -> a saved username must match it (case and "@" ignored).
  - They joined but have no Telegram username  -> nothing to compare, so any username may be saved.
  - Clearing the saved username                -> always allowed.

To change the account of someone who already joined, unlink them first ("Unlink & new link").
"""
from __future__ import annotations

import re

# Older rows only have the display label, e.g. "Sahil Jagtap (@SSJagtap20)".
_LABEL_HANDLE = re.compile(r"\(@([A-Za-z0-9_]{3,})\)")


def clean(handle: str | None) -> str | None:
    return (handle or "").strip().lstrip("@") or None


def same_handle(a: str | None, b: str | None) -> bool:
    return bool(clean(a) and clean(b) and clean(a).lower() == clean(b).lower())


def joined_handle(person: dict) -> str | None:
    """The Telegram username of the account that joined as this person, or None if unknown/none."""
    if not person.get("telegram_chat_id"):
        return None
    stored = clean(person.get("joined_username"))
    if stored:
        return stored
    match = _LABEL_HANDLE.search(person.get("joined_as") or "")
    return match.group(1) if match else None


def username_mismatch(person: dict) -> bool:
    """True when the saved username contradicts the account that joined."""
    saved, joined = clean(person.get("telegram_username")), joined_handle(person)
    return bool(saved and joined and not same_handle(saved, joined))


def rejection_reason(person: dict, new_username: str | None) -> str | None:
    """Why `new_username` may not be saved for this person right now, or None if it may."""
    new = clean(new_username)
    if not new or same_handle(new, person.get("telegram_username")):
        return None                                   # clearing it, or no change
    joined = joined_handle(person)
    if joined is None or same_handle(new, joined):
        return None                                   # not joined, no username to compare, or it matches
    label = person.get("joined_as") or f"@{joined}"
    return (
        f"{person['name']} already joined as {label}, which is not @{new}. A saved username has to match "
        f"the account that joined. If the wrong person joined, press “Unlink & new link” first."
    )
