"""
A pretend Telegram for end-to-end tests.

FakeBot is a real python-telegram-bot ExtBot whose network layer is replaced, so
the real handlers, router, policy engine and outbox run unmodified. Tests feed it
updates exactly as Telegram would deliver them and read back what the bot sent.
"""
from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

from telegram import Update
from telegram.ext import ExtBot

TOKEN = "123456789:AAFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFA"


class FakeBot(ExtBot):
    def __init__(self) -> None:
        super().__init__(token=TOKEN)
        self._sent: list[dict[str, Any]] = []        # underscore: PTB bots are frozen objects
        self._calls: list[tuple[str, dict]] = []
        self._ids = itertools.count(5000)
        self._failures: list[Exception] = []          # errors to raise on the next sendMessage calls
        self._attempts = 0                             # every sendMessage that reached the "network"

    @property
    def sent(self) -> list[dict[str, Any]]:
        return self._sent

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def calls(self) -> list[tuple[str, dict]]:
        return self._calls

    async def _do_post(self, endpoint: str, data: dict, **_: Any):
        self._calls.append((endpoint, data))
        if endpoint == "getMe":
            return {"id": 4242, "is_bot": True, "first_name": "Cadence Test",
                    "username": "cadence_test_bot", "can_join_groups": True}
        if endpoint == "sendMessage":
            self._attempts += 1
            if self._failures:
                raise self._failures.pop(0)
            message_id = next(self._ids)
            self._sent.append({
                "chat_id": int(data["chat_id"]),
                "text": data["text"],
                "markup": data.get("reply_markup"),
                "message_id": message_id,
            })
            return {"message_id": message_id, "date": int(time.time()),
                    "chat": {"id": int(data["chat_id"]), "type": "private"}, "text": data["text"]}
        return True

    def fail_next(self, *errors: Exception) -> None:
        """Make the next sendMessage calls fail with these errors, in order."""
        self._failures.extend(errors)

    # ── reading what the bot said ─────────────────────────────────────────────
    def to(self, chat_id: int) -> list[dict]:
        return [m for m in self.sent if m["chat_id"] == chat_id]

    def last(self, chat_id: int) -> dict:
        messages = self.to(chat_id)
        assert messages, f"the bot never wrote to chat {chat_id}; it wrote to {sorted({m['chat_id'] for m in self.sent})}"
        return messages[-1]

    def buttons(self, message: dict) -> list[str]:
        markup = message.get("markup")
        if not markup:
            return []
        rows = markup.to_dict()["inline_keyboard"] if hasattr(markup, "to_dict") else markup["inline_keyboard"]
        return [button["text"] for row in rows for button in row]

    def callback_data(self, message: dict, label: str) -> str:
        markup = message["markup"]
        rows = markup.to_dict()["inline_keyboard"] if hasattr(markup, "to_dict") else markup["inline_keyboard"]
        for row in rows:
            for button in row:
                if button["text"] == label:
                    return button["callback_data"]
        raise AssertionError(f"no button {label!r} in {self.buttons(message)}")


class Chat:
    """One person's Telegram client."""

    _update_ids = itertools.count(1)

    def __init__(self, application, bot: FakeBot, chat_id: int, name: str, *,
                 kind: str = "private", user_id: int | None = None) -> None:
        self.app, self.bot, self.id, self.name, self.kind = application, bot, chat_id, name, kind
        self.user_id = user_id if user_id is not None else chat_id
        self._message_ids = itertools.count(1)

    def _user(self) -> dict:
        return {"id": self.user_id, "is_bot": False, "first_name": self.name}

    def _chat(self) -> dict:
        return {"id": self.id, "type": self.kind, "first_name": self.name}

    async def say(self, text: str, *, wait: bool = True) -> None:
        message: dict[str, Any] = {
            "message_id": next(self._message_ids),
            "date": int(time.time()),
            "chat": self._chat(),
            "from": self._user(),
            "text": text,
        }
        if text.startswith("/"):
            length = len(text.split()[0])
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": length}]
        update = Update.de_json({"update_id": next(self._update_ids), "message": message}, self.bot)
        await self.app.process_update(update)
        if wait:
            await settle()

    async def press(self, message: dict, label: str, *, wait: bool = True) -> None:
        data = self.bot.callback_data(message, label)
        update = Update.de_json({
            "update_id": next(self._update_ids),
            "callback_query": {
                "id": str(next(self._update_ids)),
                "from": self._user(),
                "chat_instance": "test",
                "data": data,
                "message": {
                    "message_id": message["message_id"],
                    "date": int(time.time()),
                    "chat": self._chat(),
                    "text": message["text"],
                },
            },
        }, self.bot)
        await self.app.process_update(update)
        if wait:
            await settle()


async def settle() -> None:
    """Wait for the debounce timer and any message the router is still processing."""
    from app.telegram import router

    for _ in range(100):
        pending = [t for t in router._debounce_tasks.values() if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)
