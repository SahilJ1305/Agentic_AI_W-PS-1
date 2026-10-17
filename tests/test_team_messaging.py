"""
Issues found while testing the bot with a real team (Aanya is the lead; Kabir, Meera, Rohan are members):

  1. The lead had no way to answer an issue: a reply was read as the lead's own status update.
  2. A member's message for the lead was dropped with "I only keep track of project tasks".
  3. The lead got the same reminder every 2 minutes.
  4. Resolving a blocker on the website told nobody: the teammate never heard it was cleared.
  5. Calling a teammate out by name or @mention did not reach them.
"""
from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta, timezone

from app.agents.schemas import BlockerOut, Interpretation, RelayOut
from app.core.escalation import run_escalations
from app.core.relay import parse_directed, parse_resolution
from app.db import repo
from tests.e2e_world import PEOPLE, World, update
from tests.fake_telegram import Chat

AANYA, KABIR, MEERA, ROHAN = (PEOPLE[n] for n in ("Aanya", "Kabir", "Meera", "Rohan"))


def run(coro):
    return asyncio.run(coro)


def said(w: World, chat_id: int) -> list[str]:
    return [html.unescape(m["text"]) for m in w.bot.to(chat_id)]


async def block_kabir(w: World) -> int:
    """Kabir reports an external blocker on T3; returns the blocker id."""
    w.understands("test credentials", lambda: Interpretation(intent="blocker_report", updates=[update(
        "T3", "blocked", blocker=BlockerOut(description="test credentials", kind="external", match_confidence=0.2))]))
    await w.say("Kabir", "still waiting for test credentials")
    blockers = (await w.http.get(f"/api/projects/{w.project_id}/blockers")).json()
    return next(b["id"] for b in blockers if b["task_key"] == "T3")


async def age_blockers(minutes: float) -> dict:
    async with repo.db_context() as db:
        for row in await (await db.execute("SELECT id, raised_at FROM blockers WHERE status = 'open'")).fetchall():
            aged = datetime.fromisoformat(row["raised_at"]) - timedelta(minutes=minutes)
            await db.execute("UPDATE blockers SET raised_at = ? WHERE id = ?", (aged.isoformat(), row["id"]))
        return await run_escalations(db)


# ══════════════════════════════════════════════════════════════════════════════
#  2 + 5. A message for the lead, or for a named teammate, reaches them
# ══════════════════════════════════════════════════════════════════════════════

def test_messages_to_the_lead_and_to_named_teammates_are_delivered(tmp_path):
    run(_delivery(tmp_path))


async def _delivery(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()

        # member -> lead, in plain words: no model involved (it would answer "off topic")
        await w.say("Kabir", "tell the lead the payment gateway is down, I need an extension")
        got = said(w, AANYA)[-1]
        assert "Kabir" in got and "payment gateway is down, I need an extension" in got
        assert said(w, KABIR)[-1] == "Sent to Aanya."
        assert not any("only keep track" in m for m in said(w, KABIR))

        # @mention and "Name, ..." and Hinglish all reach the person called out
        await w.say("Meera", "@Rohan can you share the sandbox keys?")
        assert "Meera" in said(w, ROHAN)[-1] and "sandbox keys" in said(w, ROHAN)[-1]
        await w.say("Meera", "Rohan, also please merge the PR")
        assert "merge the PR" in said(w, ROHAN)[-1]
        await w.say("Kabir", "Rohan ko bolo ki API ka PR merge kar de")
        assert "API ka PR merge kar de" in said(w, ROHAN)[-1]
        await w.say("Kabir", "ask Meera to review my UI before 6")
        assert "review my UI before 6" in said(w, MEERA)[-1]

        # the lead answers: it is marked as coming from the lead, and says how to reply
        await w.say("Aanya", "tell Kabir to use the shared key from the drive")
        reply = said(w, KABIR)[-1]
        assert "Aanya</b> (lead) says" in reply and "shared key from the drive" in reply and 'Reply "tell Aanya' in reply
        assert said(w, AANYA)[-1] == "Sent to Kabir."

        # ...and Kabir can answer back
        await w.say("Kabir", "tell Aanya got it, thanks")
        assert "got it, thanks" in said(w, AANYA)[-1]


def test_unknown_names_and_whole_team_messages_get_a_clear_answer(tmp_path):
    run(_bad_targets(tmp_path))


async def _bad_targets(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        await w.say("Kabir", "tell Zubin the build is broken")
        assert "I don't know who" in said(w, KABIR)[-1] and "Aanya" in said(w, KABIR)[-1]

        await w.say("Kabir", "tell everyone standup moved to 5")                  # members cannot broadcast
        assert "Only the lead can message the whole team" in said(w, KABIR)[-1]
        assert not any("standup moved" in m for m in said(w, MEERA))

        await w.say("Aanya", "tell everyone standup moved to 5")                   # the lead can
        for chat_id in (KABIR, MEERA, ROHAN):
            assert "standup moved to 5" in said(w, chat_id)[-1]


def test_the_model_can_return_messages_next_to_status_updates(tmp_path):
    run(_model_messages(tmp_path))


async def _model_messages(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        # a fuzzy line the rules do not catch: the model returns an update AND a message
        w.understands("api is connected", lambda: Interpretation(
            intent="status_update",
            updates=[update("T3", "in_progress")],
            messages=[RelayOut(to="Aanya", text="the API is connected, please review")],
        ))
        await w.say("Kabir", "api is connected, aanya please review")
        assert "please review" in said(w, AANYA)[-1]
        assert (await w.tasks())["T3"]["status"] == "in_progress"

        # a reply to a relayed message goes back to whoever sent it
        w.understands("sent it just now", lambda: Interpretation(
            intent="message_relay", messages=[RelayOut(to="Aanya", text="sent it just now")]))
        await w.say("Kabir", "sent it just now")
        assert "sent it just now" in said(w, AANYA)[-1]
        assert said(w, KABIR)[-1] == "Sent to Aanya."


def test_a_call_out_in_the_team_group_is_also_sent_privately(tmp_path):
    run(_group_mention(tmp_path))


async def _group_mention(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        async with repo.db_context() as db:
            await repo.set_project_group(db, w.project_id, -100777)
        group = Chat(w.app, w.bot, -100777, "Team", kind="group", user_id=KABIR, username="kabir")
        before = len(said(w, ROHAN))

        await group.say("lunch at 2?")                        # ordinary chatter is ignored
        await group.say("@rohan can you check the webhook?")
        await w.deliver()
        got = said(w, ROHAN)[before:]
        assert len(got) == 1 and "Kabir" in got[0] and "in the team group" in got[0] and "check the webhook" in got[0]
        assert not any("lunch" in m for m in said(w, ROHAN))


# ══════════════════════════════════════════════════════════════════════════════
#  4. Clearing a blocker (website or Telegram) tells the teammate and moves the task on
# ══════════════════════════════════════════════════════════════════════════════

def test_resolving_a_blocker_on_the_website_tells_the_teammate(tmp_path):
    run(_website_resolve(tmp_path))


async def _website_resolve(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        bid = await block_kabir(w)
        assert (await w.tasks())["T3"]["status"] == "blocked"

        r = await w.http.post(f"/api/blockers/{bid}/resolve", json={"reason": "use the shared sandbox key"})
        assert r.status_code == 200 and r.json()["task_status"] == "in_progress" and r.json()["owner_notified"]
        await w.deliver()

        note = said(w, KABIR)[-1]
        assert "cleared your blocker" in note and "shared sandbox key" in note and "In progress" in note
        t3 = (await w.tasks())["T3"]
        assert t3["status"] == "in_progress" and not t3["blocker"]
        assert "blocker.resolved" in w.event_names()
        assert any(e["task_key"] == "T3" and e.get("status") == "in_progress" for e in w.events_of("task.updated"))

        # the button's own default text is not shown as if the lead had written it
        bid2 = await block_kabir_again(w)
        await w.http.post(f"/api/blockers/{bid2}/resolve", json={"reason": "Resolved from the dashboard"})
        await w.deliver()
        assert "They said" not in said(w, KABIR)[-1]

        # nothing is chased afterwards
        before = len(said(w, AANYA))
        result = await age_blockers(10)
        await w.deliver()
        assert result["blocker_alerts"] == 0 and result["blocker_reminders"] == 0
        assert len(said(w, AANYA)) == before


async def block_kabir_again(w: World) -> int:
    await w.say("Kabir", "still waiting for test credentials, again")
    blockers = (await w.http.get(f"/api/projects/{w.project_id}/blockers")).json()
    return next(b["id"] for b in blockers if b["task_key"] == "T3")


def test_the_lead_can_clear_a_blocker_from_telegram(tmp_path):
    run(_telegram_resolve(tmp_path))


async def _telegram_resolve(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        await block_kabir(w)

        await w.say("Aanya", "unblock Kabir, the shared key is in the drive")
        assert said(w, KABIR)[-1].startswith("Good news: Aanya cleared your blocker")
        assert "shared key is in the drive" in said(w, KABIR)[-1]
        assert (await w.tasks())["T3"]["status"] == "in_progress"
        events = [e["event_type"] for e in (await w.http.get(f"/api/tasks/{(await w.tasks())['T3']['id']}")).json()["events"]]
        assert "blocker_resolved" in events

        # a member cannot clear someone else's blocker by saying so: it is only passed on as a message
        await block_kabir_again(w)
        await w.say("Meera", "unblock Kabir")
        assert (await w.tasks())["T3"]["status"] == "blocked"

        # nothing to clear -> the lead is told, nobody is messaged
        await w.say("Aanya", "unblock Rohan")
        assert "no open blocker" in said(w, AANYA)[-1]


def test_moving_a_blocked_task_on_from_the_override_form_closes_its_blocker(tmp_path):
    run(_override_closes_blocker(tmp_path))


async def _override_closes_blocker(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()
        await block_kabir(w)
        t3 = (await w.tasks())["T3"]
        r = await w.http.patch(f"/api/tasks/{t3['id']}", json={
            "status": "in_progress", "reason": "key sent", "expected_version": t3["version"]})
        assert r.status_code == 200
        await w.deliver()
        assert "key sent" in said(w, KABIR)[-1]                              # the owner is told
        open_blockers = (await w.http.get(f"/api/projects/{w.project_id}/blockers")).json()
        assert not [b for b in open_blockers if b["task_key"] == "T3"]       # and it is not chased any more
        before = len(said(w, AANYA))
        await age_blockers(10)
        await w.deliver()
        assert len(said(w, AANYA)) == before


# ══════════════════════════════════════════════════════════════════════════════
#  3. The lead is not reminded again and again
# ══════════════════════════════════════════════════════════════════════════════

def test_the_lead_is_told_about_a_blocker_once_and_not_nagged_about_unanswered_clarifications(tmp_path):
    run(_no_repeats(tmp_path))


async def _no_repeats(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.deliver()

        # a line the bot cannot place leaves a clarification open for the lead...
        w.understands("hmm whatever", lambda: Interpretation(intent="status_update", updates=[]))
        await w.say("Aanya", "hmm whatever")
        assert said(w, AANYA)[-1].startswith("I didn't quite catch that")
        mine = len(said(w, AANYA))
        # ...which used to come back as "any update on ...?" after N minutes, then again, then escalate.
        async with repo.db_context() as db:
            for row in await (await db.execute("SELECT id, created_at FROM pending_questions WHERE status = 'open'")).fetchall():
                aged = datetime.fromisoformat(row["created_at"]) - timedelta(minutes=30)
                await db.execute("UPDATE pending_questions SET created_at = ? WHERE id = ?", (aged.isoformat(), row["id"]))
            result = await run_escalations(db)
        await w.deliver()
        assert result["nudges"] == 0 and len(said(w, AANYA)) == mine

        # a member's blocker reaches the lead exactly once, however long it stays open
        await block_kabir(w)
        await age_blockers(1.5)
        await w.deliver()
        await age_blockers(3)
        await w.deliver()
        await age_blockers(30)
        await w.deliver()
        alerts = [m for m in said(w, AANYA) if "blocked for" in m and "Owner: Kabir" in m]
        assert len(alerts) == 1


def test_a_lead_check_in_is_chased_once_and_never_sent_to_themselves(tmp_path):
    run(_lead_checkin(tmp_path))


async def _lead_checkin(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.http.post("/api/admin/checkin", json={"project_id": w.project_id})
        await w.deliver()
        before = len(said(w, AANYA))
        async with repo.db_context() as db:
            for row in await (await db.execute("SELECT id, created_at FROM pending_questions WHERE status = 'open'")).fetchall():
                aged = datetime.fromisoformat(row["created_at"]) - timedelta(minutes=2.5)
                await db.execute("UPDATE pending_questions SET created_at = ? WHERE id = ?", (aged.isoformat(), row["id"]))
            await run_escalations(db)
        await w.deliver()
        new = said(w, AANYA)[before:]
        assert not any("let Aanya know" in m or "I'll let" in m for m in new)    # "I'll tell the lead" never goes to the lead
        async with repo.db_context() as db:
            for row in await (await db.execute("SELECT id, created_at FROM pending_questions WHERE status = 'open'")).fetchall():
                aged = datetime.fromisoformat(row["created_at"]) - timedelta(minutes=10)
                await db.execute("UPDATE pending_questions SET created_at = ? WHERE id = ?", (aged.isoformat(), row["id"]))
            await run_escalations(db)
        await w.deliver()
        assert len([m for m in said(w, AANYA)[before:] if "any update on" in m]) <= 1


# ══════════════════════════════════════════════════════════════════════════════
#  The rules do not swallow ordinary status updates
# ══════════════════════════════════════════════════════════════════════════════

TEAM = [
    {"id": 1, "name": "Aanya", "role": "lead", "telegram_username": "aanya", "joined_username": None},
    {"id": 2, "name": "Kabir", "role": "member", "telegram_username": "kabir_k", "joined_username": None},
    {"id": 3, "name": "Meera", "role": "member", "telegram_username": None, "joined_username": "meera_m"},
    {"id": 4, "name": "Rohan", "role": "member", "telegram_username": "rohan", "joined_username": None},
]
KABIR_ROW, AANYA_ROW = TEAM[1], TEAM[0]


def test_status_updates_are_not_mistaken_for_messages():
    for text in [
        "done", "T3 is done", "Meera done", "stuck on T9", "kal tak ho jayega", "Kabir, done",     # Kabir is the sender
        "done with the API @Meera please review", "waiting on Rohan", "I'll tell you tomorrow",
        "update: T3 is 90% done", "let me finish this first", "mark T3 as done", "/done T3",
        "can someone take this", "remind me tomorrow",
    ]:
        assert parse_directed(text, TEAM, KABIR_ROW) is None, text


def test_addressed_messages_are_recognised():
    def target(text, sender=KABIR_ROW):
        parsed = parse_directed(text, TEAM, sender)
        assert parsed is not None, text
        return parsed.messages[0].to, parsed.messages[0].text

    assert target("tell the lead I need help with T3") == ("the lead", "I need help with T3")
    assert target("Tell Aanya that the demo is ready") == ("Aanya", "the demo is ready")
    assert target("please ask Rohan to send the keys") == ("Rohan", "send the keys")
    assert target("let Meera know the UI is merged") == ("Meera", "the UI is merged")
    assert target("@Rohan can you check the webhook?") == ("@Rohan", "can you check the webhook?")
    assert target("@meera_m ping") == ("@meera_m", "ping")                      # her Telegram handle, not her name
    assert target("Hey Rohan, are you free at 5?") == ("Rohan", "are you free at 5?")
    assert target("lead: gateway is down") == ("lead", "gateway is down")
    assert target("Rohan ko bolo ki PR merge kar de") == ("Rohan", "PR merge kar de")
    assert target("lead ko batao ki API ready hai") == ("lead", "API ready hai")
    assert target("tell everyone standup moved to 5", AANYA_ROW) == ("everyone", "standup moved to 5")


def test_only_the_lead_can_use_the_clearing_phrases():
    assert parse_resolution("unblock Kabir", TEAM, KABIR_ROW) is None
    for text, who in [("unblock Kabir", "Kabir"), ("Kabir is unblocked, use the new key", "Kabir"), ("resolved T3", None),
                      ("T3 fixed", None), ("ok fixed Rohan's blocker", "Rohan")]:
        got = parse_resolution(text, TEAM, AANYA_ROW)
        assert got is not None and got.messages[0].resolves_blocker, text
        assert (got.messages[0].to or None) == who or got.messages[0].task_key == "T3"
    assert parse_resolution("fixed the login page", TEAM, AANYA_ROW) is None
