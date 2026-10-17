"""
A real session with the ShelfShare spec (docs/shelfshare-spec.md), where Priya is the lead:

  1. The bot must know she IS the lead: it must not say "I'll flag it to the lead", and must not
     later "escalate" her own blocker to her.
  2. People with no GitHub username on the website are flagged before anything is checked (we never
     guess a username), their "done" is accepted but unverified, and once the lead adds the username
     they can ask the bot to recheck, which runs the Git checker.
"""
from __future__ import annotations

import asyncio
import html
import pathlib
from datetime import datetime, timedelta, timezone

import httpx

from app.agents.schemas import BlockerOut, Interpretation
from app.config import settings
from app.core.escalation import run_escalations
from app.db import repo
from tests.e2e_world import World, update
from tests.fake_telegram import Chat

SPEC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "shelfshare-spec.md"
PEOPLE = {"Priya": 301, "Dev": 302, "Leela": 303, "Omar": 304, "Noor": 305}


def run(coro):
    return asyncio.run(coro)


async def import_shelfshare(w: World) -> int:
    """Upload the spec as a new project, exactly as the dashboard does."""
    pid = (await w.http.post("/api/projects", json={"name": "ShelfShare"})).json()["id"]
    r = await w.http.post(f"/api/projects/{pid}/documents", data={"kind": "spec"},
                          files={"file": ("shelfshare-spec.md", SPEC.read_bytes(), "text/markdown")})
    assert r.status_code == 200 and r.json()["imported"]["tasks"] == 11, r.text
    return pid


async def join_everyone(w: World, pid: int) -> None:
    people = (await w.http.get(f"/api/projects/{pid}/participants")).json()
    for person in people:
        chat = Chat(w.app, w.bot, PEOPLE[person["name"]], person["name"])
        w.chat[person["name"]] = chat
        await chat.say(f"/start {person['invite_code']}")
    await w.deliver()


async def tasks_of(w: World, pid: int) -> dict[str, dict]:
    return {t["key"]: t for t in (await w.http.get(f"/api/projects/{pid}/tasks")).json()}


def said(w: World, who: str) -> list[str]:
    """What the person reads: Telegram turns entities like &#x27; back into the character."""
    return [html.unescape(m["text"]) for m in w.bot.to(PEOPLE[who])]


async def age_blockers(minutes: float) -> dict:
    """Pretend `minutes` passed since every open blocker was raised, then run the escalation ladder."""
    async with repo.db_context() as db:
        for row in await (await db.execute("SELECT id, raised_at FROM blockers WHERE status = 'open'")).fetchall():
            aged = datetime.fromisoformat(row["raised_at"]) - timedelta(minutes=minutes)
            await db.execute("UPDATE blockers SET raised_at = ? WHERE id = ?", (aged.isoformat(), row["id"]))
        return await run_escalations(db)


# ══════════════════════════════════════════════════════════════════════════════
#  The importer builds the board the spec promises
# ══════════════════════════════════════════════════════════════════════════════

def test_shelfshare_imports_the_board_the_spec_describes(tmp_path):
    run(_import(tmp_path))


async def _import(tmp_path):
    async with World(tmp_path) as w:
        pid = await import_shelfshare(w)
        t = await tasks_of(w, pid)
        by = lambda **f: sorted(k for k, v in t.items() if all(v[a] == b for a, b in f.items()))
        assert by(status="complete") == ["T1", "T7"]
        assert by(status="in_progress") == ["T2"]
        assert by(status="blocked") == ["T4"]
        assert by(status="pending", readiness="ready") == ["T10", "T11", "T3"]
        assert by(status="pending", readiness="waiting") == ["T5", "T6", "T8", "T9"]
        assert (t["T5"]["waiting_on"], sorted(t["T6"]["waiting_on"]), t["T8"]["waiting_on"]) == (
            ["T2"], ["T3", "T5"], ["T6"])
        assert t["T11"]["owner_id"] is None                      # left unassigned on purpose
        assert t["T10"]["waiting_on"] == []                      # a soft link never blocks
        people = {p["name"]: p["role"] for p in (await w.http.get(f"/api/projects/{pid}/participants")).json()}
        assert people["Priya"] == "lead" and len(people) == 5


# ══════════════════════════════════════════════════════════════════════════════
#  Priya is the lead: nobody above her to flag things to
# ══════════════════════════════════════════════════════════════════════════════

def test_a_lead_is_never_told_the_bot_will_flag_it_to_the_lead(tmp_path):
    run(_lead_blocked(tmp_path))


async def _lead_blocked(tmp_path):
    from app.telegram import router

    async with World(tmp_path) as w:
        pid = await import_shelfshare(w)
        await join_everyone(w, pid)

        seen_roles = []
        real = w._coordinator

        async def spy(**kwargs):
            seen_roles.append((kwargs.get("sender_name"), kwargs.get("sender_role")))
            return await real(**kwargs)

        router.run_coordinator = spy
        # What the model really answered to "Stuck on T9": it invented a reason.
        w.understands("stuck on t9", lambda: Interpretation(intent="blocker_report", updates=[update(
            "T9", "blocked", blocker=BlockerOut(description="Unspecified issue with T9", kind="external", match_confidence=0.2))]))
        w.understands("hosting account", lambda: Interpretation(intent="blocker_report", updates=[update(
            "T9", "blocked", blocker=BlockerOut(description="department hosting account", kind="external", match_confidence=0.2))]))
        w.understands("college login is down", lambda: Interpretation(intent="blocker_report", updates=[update(
            "T3", "blocked", blocker=BlockerOut(description="college login is down", kind="external", match_confidence=0.2))]))
        w.understands("take t9", lambda: Interpretation(intent="handoff_request", updates=[update("T9")]))

        # 1. A placeholder is not a reason: she is asked what is blocking T9, not told "Unspecified issue".
        await w.say("Priya", "Stuck on T9")
        assert (await tasks_of(w, pid))["T9"]["status"] == "pending"
        assert "What's blocking" in said(w, "Priya")[-1]
        assert not any("Unspecified" in m for m in said(w, "Priya"))
        assert ("Priya", "lead") in seen_roles                    # the model is told she is the lead

        # 2. Her real answer blocks the task; the acknowledgement does not pretend there is someone above her.
        await w.say("Priya", "waiting on the department hosting account")
        t9 = (await tasks_of(w, pid))["T9"]
        assert t9["status"] == "blocked" and t9["blocker"] == "department hosting account"
        ack = said(w, "Priya")[-1]
        assert "no one above you to flag this to" in ack and "flag it to the lead" not in ack

        # 3. The escalation ladder never "escalates" her blocker to her. She gets one self-reminder.
        before = len(w.bot.to(PEOPLE["Priya"]))
        first = await age_blockers(1.5)
        await w.deliver()
        assert first["blocker_alerts"] == 0 and first["blocker_reminders"] == 1
        mine = said(w, "Priya")[before:]
        assert len(mine) == 1 and "no one above you to escalate to" in mine[0]
        assert not any("Can you help unblock it" in m for m in said(w, "Priya"))
        await age_blockers(5)
        await w.deliver()
        assert len(said(w, "Priya")) == before + 1                 # and it does not repeat

        # 4. A member's blocker still goes up to the lead, as before.
        await w.say("Omar", "my college login is down")
        assert "flag it to the lead" in said(w, "Omar")[-1]
        await age_blockers(1.5)
        await w.deliver()
        heads_up = [m for m in said(w, "Priya") if "Owner: Omar" in m]
        assert len(heads_up) == 1

        # 5. If the lead asks for a handoff she gets the suggestion herself, not an alert about herself.
        await w.say("Priya", "can someone take T9")
        offer = said(w, "Priya")[-1]
        assert offer.startswith("You asked for help with") and "Suggested new owner:" in offer
        assert "can't continue" not in offer


# ══════════════════════════════════════════════════════════════════════════════
#  No GitHub username: flag it, accept the claim as unverified, recheck once it is added
# ══════════════════════════════════════════════════════════════════════════════

def test_missing_github_username_is_flagged_never_guessed_and_can_be_rechecked(tmp_path, monkeypatch):
    run(_github_username_flow(tmp_path, monkeypatch))


async def _github_username_flow(tmp_path, monkeypatch):
    from app.tools import git_checker
    from tests.test_git_checker import REPO, _commit, fake_github

    stamp = datetime.now(timezone.utc).isoformat()
    clients: list = []

    def github():
        client = fake_github([
            _commit("aaa1111", "omar-dev", "T3: build the listing endpoints", files=["api/listings.py"], date=stamp),
            _commit("bbb2222", "mallory", "T2: design the browse screens", files=["ui/browse.jsx"], date=stamp),
        ])
        clients.append(client)
        return client

    monkeypatch.setattr(git_checker, "make_client", github)

    async with World(tmp_path) as w:
        settings.github_repo = REPO
        pid = await import_shelfshare(w)
        w.understands("t3 is done", lambda: Interpretation(updates=[update("T3", "complete")]))
        w.understands("t2 is done", lambda: Interpretation(updates=[update("T2", "complete")]))

        # ── when the invite links are used, each person is told if they have no username ──
        await join_everyone(w, pid)
        welcome = {name: said(w, name)[0] for name in PEOPLE}
        assert "GitHub username" in welcome["Omar"] and "won't guess" in welcome["Omar"]
        assert "Ask Priya to add it" in welcome["Omar"]                    # a member is pointed at the lead
        assert "add it on the Cadence website" in welcome["Priya"] and "Ask Priya" not in welcome["Priya"]
        summary = (await w.http.get(f"/api/projects/{pid}")).json()
        assert summary["git_check"] == {"enabled": True, "repo": REPO}     # the website shows the same warning
        people = {p["name"]: p for p in (await w.http.get(f"/api/projects/{pid}/participants")).json()}
        assert all(not p["github_username"] for p in people.values())

        # ── Omar says T3 is done with no username on file ──
        await w.say("Omar", "T3 is done")
        t3 = (await tasks_of(w, pid))["T3"]
        assert t3["status"] == "complete" and t3["verified"] is False       # taken as done, but unverified
        assert "needs_verification" in t3["flags"]
        notice = w.bot.last(PEOPLE["Omar"])
        assert "unverified" in notice["text"] and "won't guess" in notice["text"] and "Ask Priya" in notice["text"]
        assert w.bot.buttons(notice) == ["Recheck my tasks"]
        assert all(c.calls == [] for c in clients), "GitHub was never asked about a username we do not have"
        priya_alerts = [m for m in said(w, "Priya") if "has no GitHub username" in m]
        assert len(priya_alerts) == 1 and "Omar" in priya_alerts[0]
        await w.say("Omar", "/done T3")                                      # claiming again must not nag the lead again
        assert len([m for m in said(w, "Priya") if "Omar marked" in m]) == 1
        await w.say("Leela", "T2 is done")
        assert len([m for m in said(w, "Priya") if "has no GitHub username" in m]) == 2   # one per person

        # ── the website: only a logged-in user may set a username ──
        anonymous = httpx.AsyncClient(transport=w.http._transport, base_url="http://cadence.test")
        denied = await anonymous.patch(f"/api/projects/{pid}/participants/{people['Omar']['id']}", json={"github_username": "evil"})
        await anonymous.aclose()
        assert denied.status_code == 401
        assert (await w.http.get(f"/api/projects/{pid}/participants")).json()[3]["github_username"] is None

        # /recheck before it is set: honest answer and the button again
        await w.say("Noor", "/recheck")
        assert "still don't have your GitHub username" in said(w, "Noor")[-1]
        assert w.bot.buttons(w.bot.last(PEOPLE["Noor"])) == ["Recheck my tasks"]

        # ── the lead adds Omar's username on the website: Omar is told and gets a Recheck button ──
        completed_at = (await tasks_of(w, pid))["T3"]["completed_at"]
        saved = await w.http.patch(f"/api/projects/{pid}/participants/{people['Omar']['id']}", json={"github_username": "@omar-dev"})
        assert saved.status_code == 200 and saved.json()["github_username"] == "omar-dev"
        await w.deliver()
        linked = w.bot.last(PEOPLE["Omar"])
        assert "@omar-dev" in linked["text"] and w.bot.buttons(linked) == ["Recheck my tasks"]

        # ── Omar taps Recheck: the Git checker runs and finds his commit ──
        await w.chat["Omar"].press(linked, "Recheck my tasks")
        await w.deliver()
        t3 = (await tasks_of(w, pid))["T3"]
        assert t3["verified"] is True and "needs_verification" not in t3["flags"]
        assert t3["completion_evidence"].endswith("aaa1111")
        assert t3["completed_at"] == completed_at                           # rechecking does not restart the clock
        result = said(w, "Omar")[-1]
        assert "T3: verified" in result and "@omar-dev" in result
        assert any(c.calls for c in clients)                                 # GitHub was asked this time
        events = [e["event_type"] for e in (await w.http.get(f"/api/tasks/{t3['id']}")).json()["events"]]
        assert "verified" in events

        # ── Leela gets a username, but the matching commit is someone else's: stays unverified, with the reason ──
        await w.http.patch(f"/api/projects/{pid}/participants/{people['Leela']['id']}", json={"github_username": "leela-ui"})
        await w.deliver()
        await w.say("Leela", "/recheck")
        verdict = said(w, "Leela")[-1]
        assert "T2: still unverified" in verdict and "@mallory" in verdict
        t2 = (await tasks_of(w, pid))["T2"]
        assert t2["verified"] is False and "needs_verification" in t2["flags"]

        # ── nothing left to recheck for Omar ──
        await w.say("Omar", "/recheck")
        assert "Nothing to recheck" in said(w, "Omar")[-1]


def test_no_notice_when_github_checking_is_off(tmp_path):
    run(_checker_off(tmp_path))


async def _checker_off(tmp_path):
    async with World(tmp_path) as w:                                          # github_repo is empty
        pid = await import_shelfshare(w)
        w.understands("t3 is done", lambda: Interpretation(updates=[update("T3", "complete")]))
        await join_everyone(w, pid)
        assert "GitHub" not in said(w, "Omar")[0]                              # nothing to warn about
        assert (await w.http.get(f"/api/projects/{pid}")).json()["git_check"]["enabled"] is False
        await w.say("Omar", "T3 is done")
        assert not any("GitHub" in m for m in said(w, "Omar"))
        await w.say("Omar", "/recheck")
        assert "switched off" in said(w, "Omar")[-1]
