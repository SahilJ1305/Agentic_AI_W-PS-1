"""
Invite links belong to one person: a saved Telegram username decides who can use them,
and the lead hears about (and can undo) joins that could not be checked.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.db import repo
from tests.e2e_world import World
from tests.fake_telegram import Chat


def run(coro):
    return asyncio.run(coro)


async def person(w: World, name: str) -> dict:
    people = (await w.http.get(f"/api/projects/{w.project_id}/participants")).json()
    return next(p for p in people if p["name"] == name)


async def lead_joins(w: World) -> None:
    await w.say("Aanya", f"/start {(await person(w, 'Aanya'))['invite_code']}")


def test_someone_else_cannot_use_a_link_meant_for_another_username(tmp_path):
    run(_wrong_account(tmp_path))


async def _wrong_account(tmp_path):
    async with World(tmp_path) as w:
        await lead_joins(w)
        rohan = w.chat["Rohan"]
        await rohan.say(f"/start {(await person(w, 'Kabir'))['invite_code']}")
        await w.deliver()

        assert "@kabir" in w.bot.last(rohan.id)["text"]
        assert (await person(w, "Kabir"))["telegram_chat_id"] is None
        alert = w.bot.last(101)["text"]
        assert "Rohan (@rohan)" in alert and "Kabir" in alert

        await w.say("Kabir", f"/start {(await person(w, 'Kabir'))['invite_code']}")
        assert (await person(w, "Kabir"))["telegram_chat_id"] == 102


def test_a_known_username_joins_without_any_link(tmp_path):
    run(_no_link(tmp_path))


async def _no_link(tmp_path):
    async with World(tmp_path) as w:
        await w.say("Meera", "/start")
        assert "Hi <b>Meera</b>" in w.bot.last(103)["text"]
        assert (await person(w, "Meera"))["telegram_chat_id"] == 103

        await w.say("Meera", "/start")
        assert "already in as Meera" in w.bot.last(103)["text"]

        stranger = Chat(w.app, w.bot, 999, "Stranger", username="stranger")
        await stranger.say("/start")
        assert "invite link" in w.bot.last(999)["text"]


def test_unchecked_join_alerts_the_lead_who_can_unlink_it(tmp_path):
    run(_unlink(tmp_path))


async def _unlink(tmp_path):
    async with World(tmp_path) as w:
        await lead_joins(w)
        pid = w.project_id
        newbie = (await w.http.post(f"/api/projects/{pid}/participants", json={"name": "Dev"})).json()
        old_code = newbie["invite_code"]

        intruder = Chat(w.app, w.bot, 500, "Intruder")
        await intruder.say(f"/start {old_code}")
        await w.deliver()
        dev = await person(w, "Dev")
        assert dev["telegram_chat_id"] == 500
        assert dev["joined_as"] == "Intruder (no username)"
        assert "Intruder (no username) joined as <b>Dev</b>" in w.bot.last(101)["text"]

        reset = await w.http.post(f"/api/projects/{pid}/participants/{dev['id']}/reset-invite")
        assert reset.status_code == 200, reset.text
        dev = reset.json()
        assert dev["telegram_chat_id"] is None and dev["joined_as"] is None
        assert dev["invite_code"] != old_code
        await w.deliver()
        assert "disconnected" in w.bot.last(500)["text"]

        await intruder.say(f"/start {old_code}")
        assert "isn't valid" in w.bot.last(500)["text"]

        real = Chat(w.app, w.bot, 600, "Dev", username="dev")
        await real.say(f"/start {dev['invite_code']}")
        assert (await person(w, "Dev"))["telegram_chat_id"] == 600


def test_demo_mode_skips_the_username_check(tmp_path):
    run(_demo(tmp_path))


async def _demo(tmp_path):
    async with World(tmp_path) as w:
        settings.demo_mode = True
        rohan = w.chat["Rohan"]
        await rohan.say(f"/start {(await person(w, 'Kabir'))['invite_code']}")
        assert (await person(w, "Kabir"))["telegram_chat_id"] == rohan.id


def test_editing_the_telegram_username_keeps_the_github_one(tmp_path):
    run(_edit(tmp_path))


async def _edit(tmp_path):
    async with World(tmp_path) as w:
        kabir = await person(w, "Kabir")
        url = f"/api/projects/{w.project_id}/participants/{kabir['id']}"
        await w.http.patch(url, json={"github_username": "kabir-gh"})
        updated = (await w.http.patch(url, json={"telegram_username": "@Kabir_Real"})).json()
        assert updated["telegram_username"] == "Kabir_Real"
        assert updated["github_username"] == "kabir-gh"

        async with repo.db_context() as db:
            assert [p["name"] for p in await repo.find_unjoined_by_telegram_username(db, "kabir_real")] == ["Kabir"]
