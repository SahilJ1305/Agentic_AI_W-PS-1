"""
app/telegram/keyboards.py — inline button builders and callback parser.

Callback data format: pq:<pending_question_id>:<option_index>
Telegram limits callback_data to 64 bytes — this fits comfortably.
"""
from __future__ import annotations

import json
from typing import NamedTuple


class CallbackAnswer(NamedTuple):
    question_id: int
    option_index: int
    option_text: str


def parse_callback(data: str, buttons: list[str]) -> CallbackAnswer | None:
    """
    Parse a callback_data string of the form pq:<id>:<index>.
    Returns a CallbackAnswer or None if the format is wrong.
    """
    try:
        prefix, qid, idx = data.split(":")
        if prefix != "pq":
            return None
        return CallbackAnswer(
            question_id=int(qid),
            option_index=int(idx),
            option_text=buttons[int(idx)] if int(idx) < len(buttons) else "?",
        )
    except (ValueError, IndexError):
        return None


def make_keyboard(buttons: list[str], question_id: int) -> list[list[dict]]:
    """
    Build a Telegram inline keyboard (row per button).
    Each button's callback_data is pq:<question_id>:<index>.
    """
    return [
        [{"text": btn, "callback_data": f"pq:{question_id}:{i}"}]
        for i, btn in enumerate(buttons)
    ]


def keyboard_json(buttons: list[str], question_id: int) -> str:
    return json.dumps({"inline_keyboard": make_keyboard(buttons, question_id)})
