"""
End to end: Telegram <-> bot <-> database <-> website API, with no network.

The real handlers, router, policy engine, outbox and HTTP API run unmodified.
Only Telegram (FakeBot) and the LLM (a scripted Coordinator) are stand-ins.
Each scenario checks all four sides: what the bot said, what the database holds,
what the website API returns, and what the live event stream announced.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.agents.schemas import BlockerOut, Interpretation
from app.config import settings
from app.core.escalation import run_escalations
from app.db import repo
from tests.e2e_world import World, update


def run(coro):
    return asyncio.run(coro)


async def events_settle() -> None:
    await asyncio.sleep(0.05)       # let the recorder drain the live stream


# ══════════════════════════════════════════════════════════════════════════════
#  The Kabir loop (spec G1.7, W4-W7), seen from Telegram and from the website
# ══════════════════════════════════════════════════════════════════════════════

def test_kabir_loop_telegram_to_website(tmp_path):
    run(_kabir_loop(tmp_path))


async def _kabir_loop(tmp_path):
    async with World(tmp_path) as w:
        pid = w.project_id
        w.understands("waiting for test credentials", lambda: Interpretation(updates=[update(
            "T3", "blocked", progress_note="API connected", evidence="connected, but waiting for test credentials",
            blocker=BlockerOut(description="test credentials", kind="task", suspected_task_key="T2", match_confidence=0.9),
        )]))
        w.understands("sandbox account is ready", lambda: Interpretation(updates=[update("T2", "complete")]))
        w.understands("tested end to end", lambda: Interpretation(updates=[
            update("T3", "complete", completion_evidence="PR #42")]))

        # ── onboarding: /start on Telegram flips the team panel on the website ──
        await w.onboard_everyone()
        await events_settle()
        people = (await w.http.get(f"/api/projects/{pid}/participants")).json()
        assert all(p["telegram_chat_id"] for p in people)
        assert {e["participant"] for e in w.events_of("participant.joined")} == {"Aanya", "Kabir", "Meera", "Rohan"}
        assert "Connect the payment API" in w.bot.last(102)["text"] or any(
            "Connect the payment API" in m["text"] for m in w.bot.to(102))

        # ── website: "Check in with everyone" → Kabir's phone ──────────────────
        checkin = await w.http.post("/api/admin/checkin", json={"project_id": pid})
        assert checkin.status_code == 200 and checkin.json()["tasks_targeted"] >= 3
        await w.deliver()
        ask = w.bot.last(102)
        assert "Connect the payment API" in ask["text"]
        assert w.bot.buttons(ask) == ["Done", "In progress", "Blocked"]

        # ── Telegram: Kabir reports the blocker ─────────────────────────────────
        await w.say("Kabir", "The API is connected, but I am waiting for test credentials.")
        await events_settle()
        tasks = await w.tasks()
        assert tasks["T3"]["status"] == "blocked"
        assert tasks["T3"]["blocker"] == "test credentials"
        assert tasks["T3"]["waiting_on"] == ["T2"]                      # runtime edge T2 -> T3
        assert "asked Rohan" in w.bot.last(102)["text"]                 # Kabir is told what happens next
        request = w.bot.last(104)                                       # Rohan is asked to unblock
        assert "Kabir is blocked" in request["text"] and "sandbox account" in request["text"]
        assert w.bot.buttons(request) == ["Working on it", "Already done", "Not mine"]
        # …and the website heard about all of it, tagged with this project
        assert {"message.in", "interpretation", "blocker.raised", "task.updated", "message.out"} <= set(w.event_names())
        assert all(e.get("project_id") == pid for _, e in w.events)
        decision = next(e for e in w.events_of("interpretation") if e.get("decision"))["decision"]
        assert any("R11" in line for line in decision)                  # the rule that fired is visible
        graph = (await w.http.get(f"/api/projects/{pid}/graph")).json()
        edge = next(e for e in graph["edges"] if e["upstream_key"] == "T2" and e["downstream_key"] == "T3")
        assert edge["source"] == "runtime" and edge["state"] == "active"

        # ── Telegram: Rohan taps "Working on it", Kabir is told ─────────────────
        await w.chat["Rohan"].press(request, "Working on it")
        await w.deliver()
        assert (await w.tasks())["T2"]["status"] == "in_progress"
        assert "Rohan is working on" in w.bot.last(102)["text"]

        # ── Telegram: Rohan finishes → Kabir is asked to confirm ────────────────
        await w.say("Rohan", "Sandbox account is ready, keys shared with Kabir")
        tasks = await w.tasks()
        assert tasks["T2"]["status"] == "complete"
        confirm = w.bot.last(102)
        assert "clear your blocker" in confirm["text"] and "Rohan" in confirm["text"]
        assert w.bot.buttons(confirm) == ["Yes unblocked", "Still blocked"]

        await w.chat["Kabir"].press(confirm, "Yes unblocked")
        await w.deliver()
        await events_settle()
        tasks = await w.tasks()
        assert tasks["T3"]["status"] == "in_progress" and tasks["T3"]["blocker"] is None
        assert "blocker.resolved" in w.event_names()

        # ── Telegram: Kabir finishes with a PR link ─────────────────────────────
        await w.say("Kabir", "Tested end to end, all good. PR #42")
        tasks = await w.tasks()
        assert tasks["T3"]["status"] == "complete"
        assert tasks["T3"]["completion_evidence"] == "PR #42"
        assert "Nice work" in w.bot.last(102)["text"]

        # ── website pages built from the same data ──────────────────────────────
        detail = (await w.http.get(f"/api/tasks/{tasks['T3']['id']}")).json()
        trail = [(e["event_type"], e["new_value"]) for e in detail["events"]]
        assert ("status_changed", "blocked") in trail and ("status_changed", "complete") in trail
        assert any(e.get("source_message_text") for e in detail["events"])   # every change points at a message
        assert detail["messages"], "the conversation shows in the task drawer"

        export = await w.http.get(f"/api/projects/{pid}/export.md")
        assert export.status_code == 200 and "text/markdown" in export.headers["content-type"]
        row = next(line for line in export.text.splitlines() if line.startswith("| T3 "))
        assert "Complete" in row and "Kabir" in row
        assert "## Recent changes" in export.text

        digest = (await w.http.post(f"/api/projects/{pid}/reports/digest?post=true")).json()
        assert digest["posted"] and "T3" in digest["content_md"]
        await w.deliver()
        assert "update" in w.bot.last(101)["text"] and "T3" in w.bot.last(101)["text"]   # lead's DM
        latest = (await w.http.get(f"/api/projects/{pid}/reports/latest?kind=digest")).json()
        assert latest["id"] == digest["id"]

        # ── website → Telegram: the lead overrides a task, the owner is told ────
        t5 = (await w.tasks())["T5"]
        saved = await w.http.patch(f"/api/tasks/{t5['id']}", json={
            "status": "in_progress", "reason": "Meera can start on the mock", "expected_version": t5["version"]})
        assert saved.status_code == 200, saved.text
        await w.deliver()
        notice = w.bot.last(103)
        assert "T5" in notice["text"] and "Meera can start on the mock" in notice["text"]
        stale = await w.http.patch(f"/api/tasks/{t5['id']}", json={
            "status": "pending", "reason": "x", "expected_version": t5["version"]})
        assert stale.status_code == 409                                  # optimistic locking

        # …and Meera's next message respects it
        assert (await w.tasks())["T5"]["status"] == "in_progress"


# ══════════════════════════════════════════════════════════════════════════════
#  "Done" is checked against GitHub (G3.6): website sets the username, Telegram makes the claim
# ══════════════════════════════════════════════════════════════════════════════

def test_done_claims_are_checked_against_github(tmp_path, monkeypatch):
    run(_git_claims(tmp_path, monkeypatch))


async def _git_claims(tmp_path, monkeypatch):
    from app.tools import git_checker
    from tests.test_git_checker import REPO, _commit, fake_github

    stamp = datetime.now(timezone.utc).isoformat()

    def github():          # a fresh client per check: the checker closes the one it is given
        return fake_github([
            _commit("aaa1111", "kabir", "T3: connect payment API", files=["api/payments.py"], date=stamp),
            _commit("bbb2222", "rohan", "T4 build checkout UI", files=["ui/checkout.jsx"], date=stamp),
        ])

    monkeypatch.setattr(git_checker, "make_client", github)

    async with World(tmp_path) as w:
        pid = w.project_id
        settings.github_repo = REPO
        w.understands("t3 is done", lambda: Interpretation(updates=[update("T3", "complete")]))
        w.understands("checkout ui is done", lambda: Interpretation(updates=[update("T4", "complete")]))
        w.understands("sandbox ready", lambda: Interpretation(updates=[update("T2", "complete")]))
        await w.onboard_everyone()
        await w.say("Rohan", "sandbox ready")             # so T3's upstream is finished

        # website: the lead links GitHub accounts
        people = {p["name"]: p for p in (await w.http.get(f"/api/projects/{pid}/participants")).json()}
        for name, login in (("Kabir", "kabir"), ("Meera", "meera")):
            r = await w.http.patch(f"/api/projects/{pid}/participants/{people[name]['id']}", json={"github_username": f"@{login}"})
            assert r.status_code == 200 and r.json()["github_username"] == login

        # Kabir really committed → verified, the commit is the evidence
        await w.say("Kabir", "T3 is done")
        t3 = (await w.tasks())["T3"]
        assert t3["status"] == "complete" and t3["verified"] is True
        assert t3["completion_evidence"].endswith("aaa1111")
        assert "needs_verification" not in t3["flags"]

        # Meera claims T4, but the only matching commit is Rohan's → unverified + the lead is told
        await w.say("Meera", "checkout UI is done")
        t4 = (await w.tasks())["T4"]
        assert t4["status"] == "complete" and t4["verified"] is False
        assert "needs_verification" in t4["flags"]
        warning = w.bot.last(103)
        assert "couldn't confirm" in warning["text"] and "@rohan" in warning["text"]
        assert any("authored by @rohan" in m["text"] for m in w.bot.to(101))      # Aanya's alert
        await w.chat["Meera"].press(warning, "No link")
        assert "unverified" in w.bot.last(103)["text"]

        export = (await w.http.get(f"/api/projects/{pid}/export.md")).text
        assert "✓ verified" in next(l for l in export.splitlines() if l.startswith("| T3 "))
        assert "(unverified)" in next(l for l in export.splitlines() if l.startswith("| T4 "))


# ══════════════════════════════════════════════════════════════════════════════
#  Buttons that used to loop or do nothing
# ══════════════════════════════════════════════════════════════════════════════

def test_conflict_and_reopen_buttons_do_not_loop(tmp_path):
    run(_confirmation_buttons(tmp_path))


async def _confirmation_buttons(tmp_path):
    async with World(tmp_path) as w:
        w.understands("t5 done", lambda: Interpretation(updates=[update("T5", "complete")]))
        w.understands("reopen t6", lambda: Interpretation(updates=[update("T6", "in_progress")]))
        await w.onboard_everyone()

        # Meera says T5 is done while T3 and T4 are not: she is asked, not believed
        await w.say("Meera", "T5 done")
        assert (await w.tasks())["T5"]["status"] == "pending"
        question = w.bot.last(103)
        assert "end-to-end" in question["text"] and w.bot.buttons(question) == ["Yes it works", "Not fully"]

        await w.chat["Meera"].press(question, "Yes it works")
        await w.deliver()
        t5 = (await w.tasks())["T5"]
        assert t5["status"] == "complete"                     # accepted once she confirmed, not asked again
        assert "needs_verification" in t5["flags"] and "dependency_conflict" in t5["flags"]
        again = [m for m in w.bot.to(103) if "end-to-end" in m["text"]]
        assert len(again) == 1

        # The risk report names it
        report = (await w.http.post(f"/api/projects/{w.project_id}/reports/risk")).json()
        assert report["content_md"].startswith("# Risk report: FestPass")

        # Reopening a finished task needs a yes, and a yes is enough
        await w.say("Aanya", "reopen T6")
        ask = w.bot.last(101)
        assert w.bot.buttons(ask) == ["Yes reopen", "No keep it done"]
        await w.chat["Aanya"].press(ask, "Yes reopen")
        await w.deliver()
        assert (await w.tasks())["T6"]["status"] == "in_progress"


# ══════════════════════════════════════════════════════════════════════════════
#  Silence and blockers escalate (G3.7)
# ══════════════════════════════════════════════════════════════════════════════

def test_escalation_ladder(tmp_path):
    run(_escalation(tmp_path))


async def _escalation(tmp_path):
    async with World(tmp_path) as w:
        pid = w.project_id
        w.understands("waiting for test credentials", lambda: Interpretation(updates=[update(
            "T3", "blocked", blocker=BlockerOut(description="test credentials", kind="task",
                                                 suspected_task_key="T2", match_confidence=0.9))]))
        await w.onboard_everyone()
        await w.http.post("/api/admin/checkin", json={"project_id": pid})
        await w.deliver()
        await w.say("Kabir", "waiting for test credentials")      # Kabir answers; Meera stays silent

        elapsed = 0.0

        async def pass_at(minutes: float) -> dict:
            """Run the ladder as if `minutes` had passed since the questions were asked.

            Time is simulated by ageing the stored timestamps, so the ladder and the outbox both
            keep using the real clock (a future-dated message would trip the quiet window)."""
            nonlocal elapsed
            shift, elapsed = timedelta(minutes=minutes - elapsed), minutes
            async with repo.db_context() as db:
                for table, column, where in (("pending_questions", "created_at", "status = 'open'"),
                                             ("blockers", "raised_at", "status = 'open'")):
                    for row in await (await db.execute(f"SELECT id, {column} FROM {table} WHERE {where}")).fetchall():
                        aged = datetime.fromisoformat(row[column]) - shift
                        await db.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (aged.isoformat(), row["id"]))
                result = await run_escalations(db)
            await w.deliver()
            return result

        before = len(w.bot.to(103))
        assert (await pass_at(0.2)) == {"nudges": 0, "silence_alerts": 0, "blocker_reminders": 0, "blocker_alerts": 0}

        first = await pass_at(1.5)                                 # N = 1 min
        assert first["nudges"] >= 1 and first["blocker_reminders"] == 1
        assert "any update on" in w.bot.last(103)["text"] and len(w.bot.to(103)) == before + 1
        assert any("still blocked" in m["text"] for m in w.bot.to(104)), [m["text"] for m in w.bot.to(104)]   # Rohan is reminded
        assert (await pass_at(1.5))["nudges"] == 0                  # idempotent

        second = await pass_at(2.5)
        assert second["nudges"] >= 1 and "let Aanya know" in w.bot.last(103)["text"]
        assert second["blocker_alerts"] == 1
        assert any("blocked for" in m["text"] for m in w.bot.to(101))   # Aanya hears about the blocker

        third = await pass_at(3.5)
        assert third["silence_alerts"] >= 1
        assert any("no reply from Meera" in m["text"] for m in w.bot.to(101))
        t4 = (await w.tasks())["T4"]
        assert "stale" in t4["flags"]
        assert any(e.get("task_key") == "T4" and "stale" in (e.get("flags") or []) for e in w.events_of("task.updated"))
        assert (await pass_at(4.5))["silence_alerts"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  /pause, the team group, /digest, /risk, handoffs
# ══════════════════════════════════════════════════════════════════════════════

def test_pause_group_digest_and_handoff(tmp_path):
    run(_commands(tmp_path))


async def _commands(tmp_path):
    from tests.fake_telegram import Chat

    async with World(tmp_path) as w:
        pid = w.project_id
        await w.onboard_everyone()
        w.understands("someone take", lambda: Interpretation(intent="handoff_request", updates=[update("T3")]))

        # /pause holds reminders back, /pause 0 releases them
        await w.say("Meera", "/pause 2")
        assert "Paused for 2 h" in w.bot.last(103)["text"]
        paused = {p["name"]: p for p in (await w.http.get(f"/api/projects/{pid}/participants")).json()}["Meera"]
        assert paused["paused_until"]
        held = len(w.bot.to(103))
        await w.http.post("/api/admin/checkin", json={"project_id": pid})
        await w.deliver()
        assert len(w.bot.to(103)) == held
        await w.say("Meera", "/pause 0")
        await w.deliver()
        assert "Connect" in w.bot.last(103)["text"] or "checkout" in w.bot.last(103)["text"].lower()

        # the lead links the team group; anyone there can ask for reports
        def in_group(user_id: int, name: str) -> Chat:
            return Chat(w.app, w.bot, -100777, name, kind="supergroup", user_id=user_id)

        await in_group(101, "Aanya").say("/linkgroup")
        assert "Linked" in w.bot.last(-100777)["text"]
        assert (await w.http.get(f"/api/projects/{pid}")).json()["project"]["group_chat_id"] == -100777

        stranger = in_group(999, "Visitor")       # not on the team, but in the linked group
        await stranger.say("/risk")
        assert "Risk report" in w.bot.last(-100777)["text"]
        await stranger.say("/digest")
        assert "update" in w.bot.last(-100777)["text"] and "complete" in w.bot.last(-100777)["text"]

        # outside a linked group, only the lead may ask
        await w.say("Kabir", "/digest")
        assert "Only the project lead" in w.bot.last(102)["text"]
        await w.say("Aanya", "/digest")
        assert "update" in w.bot.last(101)["text"]

        # the scheduled digest goes to the group and the lead's DM, once per day
        from app.scheduler.jobs import run_digests_all
        group_before, lead_before = len(w.bot.to(-100777)), len(w.bot.to(101))
        assert await run_digests_all() == 1
        await w.deliver()
        assert len(w.bot.to(-100777)) == group_before + 1 and len(w.bot.to(101)) == lead_before + 1
        await run_digests_all()
        await w.deliver()
        assert len(w.bot.to(-100777)) == group_before + 1          # deduped

        # handoff: the lead hears who fits (skills + load), not "TBD"
        await w.say("Kabir", "I'm sick, someone take T3")
        pitch = next(m for m in reversed(w.bot.to(101)) if "can't continue" in m["text"])
        assert "Rohan" in pitch["text"] and "backend" in pitch["text"]


# ══════════════════════════════════════════════════════════════════════════════
#  Website edits to the graph reach the board; the plan review honours rejections
# ══════════════════════════════════════════════════════════════════════════════

def test_dependency_editing_from_the_website(tmp_path):
    run(_dependencies(tmp_path))


async def _dependencies(tmp_path):
    async with World(tmp_path) as w:
        pid = w.project_id
        added = await w.http.post("/api/dependencies", json={
            "project_id": pid, "upstream_key": "T2", "downstream_key": "T4", "type": "hard", "reason": "needs sandbox"})
        assert added.status_code == 200, added.text
        edge = added.json()
        assert (edge["upstream_key"], edge["downstream_key"], edge["source"]) == ("T2", "T4", "manual")
        assert (await w.tasks())["T4"]["waiting_on"] == ["T2"]

        cycle = await w.http.post("/api/dependencies", json={
            "project_id": pid, "upstream_key": "T5", "downstream_key": "T3", "type": "hard"})
        assert cycle.status_code == 409 and "cycle" in cycle.json()["detail"]
        assert (await w.http.post("/api/dependencies", json={
            "project_id": pid, "upstream_key": "T3", "downstream_key": "T3"})).status_code == 400

        soft = await w.http.patch(f"/api/dependencies/{edge['id']}", json={"type": "soft"})
        assert soft.json()["type"] == "soft" and (await w.tasks())["T4"]["waiting_on"] == []
        gone = await w.http.delete(f"/api/dependencies/{edge['id']}")
        assert gone.status_code == 200
        await events_settle()
        assert len(w.events_of("dependency.changed")) >= 3
        graph = (await w.http.get(f"/api/projects/{pid}/graph")).json()
        assert not any(e["id"] == edge["id"] for e in graph["edges"])


def test_plan_commit_skips_rejected_edges(tmp_path):
    run(_plan_commit(tmp_path))


async def _plan_commit(tmp_path):
    from app.agents.schemas import PlanDraft, PlannedDependency, PlannedTask

    async with World(tmp_path) as w:
        created = (await w.http.post("/api/projects", json={"name": "Review me"})).json()
        pid = created["id"]
        draft = PlanDraft(
            project_name="Review me", summary="s",
            tasks=[PlannedTask(key=k, title=t, description=t, acceptance="ok") for k, t in
                   (("T1", "Design schema"), ("T2", "Build API"), ("T3", "Write docs"))],
            dependencies=[
                PlannedDependency(upstream="T1", downstream="T2", reason="schema first",
                                  evidence_quote="schema first", confidence=0.95),
                PlannedDependency(upstream="T2", downstream="T3", reason="docs follow",
                                  evidence_quote="docs follow", confidence=0.95),
            ],
        )
        async with repo.db_context() as db:
            draft_id = await repo.save_plan_draft(
                db, project_id=pid, plan_json=draft.model_dump_json(),
                validation_json="{}", llm_call_id=None, now=datetime.now(timezone.utc).isoformat())
        latest = (await w.http.get(f"/api/projects/{pid}/plan/latest")).json()
        assert latest["draft_id"] == draft_id and len(latest["draft"]["tasks"]) == 3

        committed = await w.http.post(f"/api/projects/{pid}/plan/{draft_id}/commit", json={
            "accepted_edge_pairs": [["T1", "T2"]], "rejected_edge_pairs": [["T2", "T3"]]})
        assert committed.status_code == 200, committed.text
        graph = (await w.http.get(f"/api/projects/{pid}/graph")).json()
        live = {(e["upstream_key"], e["downstream_key"]) for e in graph["edges"] if e["state"] == "active"}
        assert live == {("T1", "T2")}
        assert (await w.http.get(f"/api/projects/{pid}/plan/latest")).status_code == 404   # nothing left to review
