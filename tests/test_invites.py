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


# ── a saved username has to agree with the account that actually joined ─────────

async def save_username(w: World, name: str, value, **extra):
    who = await person(w, name)
    return await w.http.patch(
        f"/api/projects/{w.project_id}/participants/{who['id']}", json={"telegram_username": value, **extra})


def test_saved_username_must_match_the_account_that_joined(tmp_path):
    run(_must_match(tmp_path))


async def _must_match(tmp_path):
    async with World(tmp_path) as w:
        await w.say("Kabir", f"/start {(await person(w, 'Kabir'))['invite_code']}")
        kabir = await person(w, "Kabir")
        assert kabir["joined_username"] == "kabir" and kabir["username_mismatch"] is False

        # Saving someone else's username for a person who joined as @kabir is refused...
        refused = await save_username(w, "Kabir", "OmkarS", github_username="should-not-be-saved")
        assert refused.status_code == 409
        assert "already joined as Kabir (@kabir)" in refused.json()["detail"]
        assert "not @OmkarS" in refused.json()["detail"] and "Unlink" in refused.json()["detail"]
        after = await person(w, "Kabir")
        assert after["telegram_username"] == "kabir"            # unchanged
        assert after["github_username"] is None                  # and nothing else in the request was applied

        # ...but the same account (any case, with or without @), or clearing the field, is fine.
        assert (await save_username(w, "Kabir", "@KABIR")).status_code == 200
        cleared = await save_username(w, "Kabir", "")
        assert cleared.status_code == 200 and cleared.json()["telegram_username"] is None

        # The way to change who a person is: unlink, then save and issue the new link.
        kabir = await person(w, "Kabir")
        await w.http.post(f"/api/projects/{w.project_id}/participants/{kabir['id']}/reset-invite")
        moved = await save_username(w, "Kabir", "OmkarS")
        assert moved.status_code == 200 and moved.json()["telegram_username"] == "OmkarS"
        assert moved.json()["joined_username"] is None


def test_an_account_without_a_username_leaves_nothing_to_compare(tmp_path):
    run(_no_username_joined(tmp_path))


async def _no_username_joined(tmp_path):
    async with World(tmp_path) as w:
        await lead_joins(w)
        pid = w.project_id
        dev = (await w.http.post(f"/api/projects/{pid}/participants", json={"name": "Dev"})).json()
        await Chat(w.app, w.bot, 500, "Intruder").say(f"/start {dev['invite_code']}")    # no @username

        joined = await person(w, "Dev")
        assert joined["telegram_chat_id"] == 500 and joined["joined_username"] is None
        saved = await save_username(w, "Dev", "somebody_else")
        assert saved.status_code == 200 and saved.json()["username_mismatch"] is False   # allowed; they can still unlink him


def test_a_person_who_is_already_inconsistent_is_flagged(tmp_path):
    run(_flag_existing(tmp_path))


async def _flag_existing(tmp_path):
    async with World(tmp_path) as w:
        meera = await person(w, "Meera")
        # What the dashboard showed for Chirag: joined as @SSJagtap20 (only the label was stored),
        # then a different username was saved.
        async with repo.db_context() as db:
            await db.execute(
                "UPDATE participants SET telegram_chat_id = 777, telegram_username = 'OmkarS', "
                "joined_as = 'Sahil Jagtap (@SSJagtap20)', joined_username = NULL WHERE id = ?", (meera["id"],))
        flagged = await person(w, "Meera")
        assert flagged["joined_username"] == "SSJagtap20" and flagged["username_mismatch"] is True

        url = f"/api/projects/{w.project_id}/participants/{meera['id']}"
        assert (await w.http.patch(url, json={"github_username": "meera-gh"})).status_code == 200   # unrelated edits still work
        assert (await w.http.patch(url, json={"telegram_username": "Someone"})).status_code == 409
        fixed = await w.http.patch(url, json={"telegram_username": "ssjagtap20"})
        assert fixed.status_code == 200 and fixed.json()["username_mismatch"] is False


def test_joining_records_the_account_username_and_unlinking_clears_it(tmp_path):
    run(_records_username(tmp_path))


async def _records_username(tmp_path):
    async with World(tmp_path) as w:
        code = (await person(w, "Kabir"))["invite_code"]
        await w.say("Kabir", f"/start {code}")
        async with repo.db_context() as db:
            row = await (await db.execute("SELECT joined_username, joined_as FROM participants WHERE name = 'Kabir'")).fetchone()
        assert row["joined_username"] == "kabir" and "(@kabir)" in row["joined_as"]
        kabir = await person(w, "Kabir")
        await w.http.post(f"/api/projects/{w.project_id}/participants/{kabir['id']}/reset-invite")
        async with repo.db_context() as db:
            row = await (await db.execute("SELECT joined_username FROM participants WHERE name = 'Kabir'")).fetchone()
        assert row["joined_username"] is None
