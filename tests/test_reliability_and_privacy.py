"""
Things the team hit for real: duplicate messages, slow replies, and people seeing the wrong tasks.

Every test runs the true bot, policy engine, outbox and HTTP API against a pretend Telegram.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from telegram.error import BadRequest, Forbidden, TimedOut

from app.agents.schemas import BlockerOut, Interpretation
from app.config import settings
from app.core.escalation import run_escalations
from app.db import repo
from tests.e2e_world import PEOPLE, World, update


def run(coro):
    return asyncio.run(coro)


def timed_out(cause: Exception) -> TimedOut:
    error = TimedOut("Timed out")
    error.__cause__ = cause
    return error


async def queue_one(w: World, who: str = "Kabir", text: str = "ping") -> int:
    """Put one plain message for `who` in the outbox and return its row id."""
    async with repo.db_context() as db:
        person = (await repo.list_participants(db, w.project_id))
        person = next(p for p in person if p["name"] == who)
        return await repo.enqueue_message(
            db, participant_id=person["id"], chat_id=person["telegram_chat_id"],
            template_key="ACK_PROGRESS", text=text, now=datetime.now(timezone.utc).isoformat())


async def row(outbox_id: int) -> dict:
    async with repo.db_context() as db:
        return dict(await (await db.execute("SELECT * FROM outbox WHERE id = ?", (outbox_id,))).fetchone())


# ══════════════════════════════════════════════════════════════════════════════
#  Duplicate messages
# ══════════════════════════════════════════════════════════════════════════════

def test_a_send_that_may_have_arrived_is_never_resent(tmp_path):
    run(_ambiguous_timeout(tmp_path))


async def _ambiguous_timeout(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        before = len(w.bot.to(102))
        outbox_id = await queue_one(w, "Kabir", "hello once")

        # The request was written, then the answer never came: Telegram may well have delivered it.
        w.bot.fail_next(timed_out(httpx.ReadTimeout("slow")))
        attempts_before = w.bot.attempts
        await w.deliver()
        await w.deliver()
        assert w.bot.attempts == attempts_before + 1, "it was tried once and never again"
        assert (await row(outbox_id))["status"] == "failed"
        assert "unconfirmed" in (await row(outbox_id))["error"]
        assert not any(m["text"] == "hello once" for m in w.bot.to(102)), "nothing more was sent"
        assert len(w.bot.to(102)) == before


def test_a_send_that_never_reached_telegram_is_retried_once_connected(tmp_path, monkeypatch):
    run(_unreachable_then_ok(tmp_path, monkeypatch))


async def _unreachable_then_ok(tmp_path, monkeypatch):
    from app.telegram import outbox

    monkeypatch.setattr(outbox, "BACKOFF_S", (0, 0))
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        outbox_id = await queue_one(w, "Kabir", "will arrive")
        w.bot.fail_next(timed_out(httpx.ConnectTimeout("no route")))     # Telegram never saw the request
        await outbox._tick(w.bot)
        first = await row(outbox_id)
        assert first["status"] == "queued" and first["attempts"] == 1       # waiting for its retry
        assert not any(m["text"] == "will arrive" for m in w.bot.to(102))
        await w.deliver()                                                    # the retry goes through
        assert (await row(outbox_id))["status"] == "sent"
        assert [m["text"] for m in w.bot.to(102)].count("will arrive") == 1


def test_blocked_bot_and_bad_requests_are_closed_not_retried(tmp_path):
    run(_permanent_errors(tmp_path))


async def _permanent_errors(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        a = await queue_one(w, "Kabir", "to a blocked chat")
        w.bot.fail_next(Forbidden("bot was blocked by the user"))
        await w.deliver()
        assert (await row(a))["status"] == "failed"
        b = await queue_one(w, "Rohan", "bad markup")
        w.bot.fail_next(BadRequest("can't parse entities"))
        attempts_before = w.bot.attempts
        await w.deliver()
        await w.deliver()
        assert (await row(b))["status"] == "failed" and w.bot.attempts == attempts_before + 1


def test_a_database_hiccup_after_sending_cannot_cause_a_resend(tmp_path, monkeypatch):
    run(_bookkeeping_failure(tmp_path, monkeypatch))


async def _bookkeeping_failure(tmp_path, monkeypatch):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        outbox_id = await queue_one(w, "Kabir", "sent exactly once")
        real, calls = repo.save_message, {"n": 0}

        async def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("database is locked")
            return await real(*args, **kwargs)

        monkeypatch.setattr(repo, "save_message", flaky)
        for _ in range(3):
            await w.deliver()
        assert [m["text"] for m in w.bot.to(102)].count("sent exactly once") == 1
        assert (await row(outbox_id))["status"] == "sent"


def test_one_reminder_per_person_even_with_two_open_questions(tmp_path):
    run(_one_nudge_per_person(tmp_path))


async def _one_nudge_per_person(tmp_path):
    async with World(tmp_path) as w:
        w.understands("waiting for test credentials", lambda: Interpretation(updates=[update(
            "T3", "blocked", blocker=BlockerOut(description="test credentials", kind="task",
                                                 suspected_task_key="T2", match_confidence=0.9))]))
        await w.onboard_everyone()
        await w.http.post("/api/admin/checkin", json={"project_id": w.project_id})
        await w.say("Kabir", "waiting for test credentials")      # Rohan now has a check-in AND an unblock question
        async with repo.db_context() as db:
            open_for_rohan = await (await db.execute(
                "SELECT COUNT(*) AS n FROM pending_questions WHERE participant_id = 4 AND status = 'open'")).fetchone()
        assert open_for_rohan["n"] == 2

        async with repo.db_context() as db:                         # let 1.5 minutes "pass"
            for r in await (await db.execute("SELECT id, created_at FROM pending_questions")).fetchall():
                aged = datetime.fromisoformat(r["created_at"]) - timedelta(minutes=1.5)
                await db.execute("UPDATE pending_questions SET created_at = ? WHERE id = ?", (aged.isoformat(), r["id"]))
            await run_escalations(db)
        await w.deliver()
        bumps = [m for m in w.bot.to(PEOPLE["Rohan"]) if "bumping this" in m["text"]]
        assert len(bumps) == 1, [m["text"][:60] for m in w.bot.to(PEOPLE["Rohan"])]


def test_pressing_check_in_twice_does_not_ask_twice(tmp_path):
    run(_double_checkin(tmp_path))


async def _double_checkin(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        first = (await w.http.post("/api/admin/checkin", json={"project_id": w.project_id})).json()
        second = (await w.http.post("/api/admin/checkin", json={"project_id": w.project_id})).json()
        await w.deliver()
        assert first["tasks_targeted"] >= 3 and second["tasks_targeted"] == 0
        assert len([m for m in w.bot.to(102) if "How's" in m["text"]]) == 1


def test_slash_commands_answer_once(tmp_path):
    run(_single_reply(tmp_path))


async def _single_reply(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        before = len(w.bot.to(102))
        await w.say("Kabir", "/blocked T3 waiting for the sandbox keys")
        replies = w.bot.to(102)[before:]
        assert len(replies) == 1 and "Blocked" in replies[0]["text"], [m["text"] for m in replies]
        await w.say("Rohan", "/done T2")
        replies = [m for m in w.bot.to(104) if "Complete" in m["text"] or "complete" in m["text"]]
        assert len(replies) == 1, [m["text"] for m in w.bot.to(104)]


# ══════════════════════════════════════════════════════════════════════════════
#  Privacy: a member sees only their own tasks
# ══════════════════════════════════════════════════════════════════════════════

def test_members_only_see_their_own_tasks(tmp_path):
    run(_privacy(tmp_path))


async def _privacy(tmp_path):
    from tests.fake_telegram import Chat

    async with World(tmp_path) as w:
        await w.onboard_everyone()
        mine = {"Kabir": ("T3",), "Meera": ("T4", "T5"), "Rohan": ("T1", "T2"), "Aanya": ("T6", "T7", "T8")}
        every_key = {f"T{i}" for i in range(1, 9)}
        for name, keys in mine.items():
            await w.say(name, "/mytasks")
            shown = {k for k in every_key if f"<b>{k}</b>" in w.bot.last(PEOPLE[name])["text"]}
            assert shown == set(keys), (name, shown)

        await w.say("Kabir", "/next")
        assert "T3" in w.bot.last(102)["text"] or "all clear" in w.bot.last(102)["text"]
        assert not any(f"{k} " in w.bot.last(102)["text"] for k in ("T1", "T2", "T4", "T5", "T6", "T7", "T8"))

        # someone who never joined learns nothing
        stranger = Chat(w.app, w.bot, 555000, "Stranger")
        for command in ("/mytasks", "/status", "/next", "/done T3", "/digest", "/risk"):
            await stranger.say(command)
            said = w.bot.last(555000)["text"]
            assert not any(f"T{i}" in said for i in range(1, 9)) and "FestPass" not in said, (command, said)

        # …and a teammate cannot change someone else's task
        before = (await w.tasks())["T3"]["status"]
        await w.say("Meera", "/done T3")
        assert (await w.tasks())["T3"]["status"] == before
        assert "not yours" in w.bot.last(103)["text"]

        # personal commands do not work in a group, where everyone would read the answer
        group = Chat(w.app, w.bot, -100999, "Team", kind="supergroup", user_id=102)
        await group.say("/mytasks")
        assert "personal" in w.bot.last(-100999)["text"] and "T3" not in w.bot.last(-100999)["text"]

        # a button on someone else's question does nothing for you
        await w.http.post("/api/admin/checkin", json={"project_id": w.project_id})
        await w.deliver()
        kabirs_question = w.bot.last(102)
        await w.chat["Meera"].press(kabirs_question, "Done")
        await w.deliver()
        assert (await w.tasks())["T3"]["status"] == before
        assert "already answered" in w.bot.last(103)["text"]


def test_one_telegram_account_cannot_join_a_second_project_by_accident(tmp_path):
    run(_second_project(tmp_path))


async def _second_project(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        other = (await w.http.post("/api/projects", json={"name": "Second"})).json()["id"]
        invite = (await w.http.post(f"/api/projects/{other}/participants", json={"name": "Meera Too"})).json()
        await w.say("Meera", f"/start {invite['invite_code']}")
        assert "already linked" in w.bot.last(103)["text"]
        people = (await w.http.get(f"/api/projects/{other}/participants")).json()
        assert people[0]["telegram_chat_id"] is None


# ══════════════════════════════════════════════════════════════════════════════
#  Speed
# ══════════════════════════════════════════════════════════════════════════════

def test_plain_status_words_skip_the_ai(tmp_path):
    run(_fast_path(tmp_path))


async def _fast_path(tmp_path):
    async with World(tmp_path) as w:
        from app.telegram import router

        asked = []

        async def must_not_be_called(**kwargs):
            asked.append(kwargs["message_text"])
            return Interpretation(intent="off_topic")

        router.run_coordinator = must_not_be_called
        await w.onboard_everyone()

        await w.say("Rohan", "done")              # Rohan has one open task (T2)
        assert (await w.tasks())["T2"]["status"] == "complete" and asked == []
        decision = next(e for e in w.events_of("interpretation") if e.get("decision"))["decision"]
        assert decision[0].startswith("Fast path")

        await w.say("Meera", "hogaya")            # two open tasks, no question: she is asked which
        assert asked == [] and w.bot.buttons(w.bot.last(103))[-1] == "None of these"

        await w.say("Kabir", "done, but the webhook still fails")      # anything longer goes to the AI
        assert asked == ["done, but the webhook still fails"]
        asked.clear()
        await w.say("Kabir", "working on it")     # one word of progress is fast too
        assert asked == [] and (await w.tasks())["T3"]["status"] == "in_progress"


def test_replies_are_prompt_and_demo_actions_are_locked_down(tmp_path):
    run(_speed_and_gates(tmp_path))


async def _speed_and_gates(tmp_path):
    from app.telegram import outbox

    assert outbox.POLL_INTERVAL_S <= 0.5
    from app.config import Settings
    assert Settings.model_fields["debounce_s"].default <= 2.0

    async with World(tmp_path) as w:
        # outside demo mode the wipe-and-reseed and fast-forward buttons are refused
        assert (await w.http.post("/api/admin/reset-demo")).status_code == 403
        assert (await w.http.post("/api/admin/tick")).status_code == 403
        settings.demo_mode = True
        try:
            assert (await w.http.post("/api/admin/tick")).status_code == 200
        finally:
            settings.demo_mode = False
