"""Live stream isolation, risk rules, and the digest / risk / export formats."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from app.api import sse
from app.config import settings
from app.core import reports
from app.core.taskview import load_view
from app.db import repo
from app.db.seed_demo import seed


# ── live stream ───────────────────────────────────────────────────────────────

def test_stream_only_carries_its_own_project(monkeypatch):
    async def go():
        hub = sse.SSEBroadcaster()
        got: dict[int, list[str]] = {1: [], 2: []}

        async def listen(pid: int):
            async for chunk in hub.stream(pid):
                match = re.search(r"event: (\S+)", chunk)
                if match and match.group(1) not in ("connected", "ping"):
                    got[pid].append(chunk)

        tasks = [asyncio.create_task(listen(1)), asyncio.create_task(listen(2))]
        await asyncio.sleep(0.01)
        await hub.publish("task.updated", {"project_id": 1, "task_key": "T3"})
        await hub.publish("task.updated", {"project_id": 2, "task_key": "T9"})
        await hub.publish("plan.ready", {"draft_id": 5}, project_id=2)      # project given separately
        await asyncio.sleep(0.01)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert len(got[1]) == 1 and "T3" in got[1][0] and "T9" not in got[1][0]
        assert len(got[2]) == 2 and '"project_id": 2' in got[2][1]
        assert hub.subscriber_count == 0                                    # cleaned up on disconnect

    asyncio.run(go())


def test_stream_keeps_alive_instead_of_ending(monkeypatch):
    monkeypatch.setattr(sse, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(sse, "MAX_LIFETIME_S", 0.4)

    async def go():
        hub = sse.SSEBroadcaster()
        names = [re.search(r"event: (\S+)", c).group(1) async for c in hub.stream(1)]
        assert names[0] == "connected" and names.count("ping") >= 3        # several pings, same connection

    asyncio.run(go())


def test_slow_client_loses_oldest_event_not_its_connection():
    async def go():
        hub = sse.SSEBroadcaster()
        stream = hub.stream(1)
        await stream.__anext__()                                            # connected
        for i in range(250):                                                # queue holds 200
            await hub.publish("task.updated", {"project_id": 1, "n": i})
        first = await stream.__anext__()
        assert '"n": 50' in first                                           # oldest 50 dropped
        await stream.aclose()

    asyncio.run(go())


# ── risk rules and reports ────────────────────────────────────────────────────

def test_risk_rules_and_report_formats(tmp_path):
    settings.database_path = str(tmp_path / "risk.db")
    saved = settings.demo_mode, settings.risk_blocked_min
    settings.demo_mode, settings.risk_blocked_min = False, 120
    try:
        asyncio.run(_risk_and_reports())
    finally:
        settings.demo_mode, settings.risk_blocked_min = saved


async def _risk_and_reports():
    await seed(force=True)
    now = datetime.now(timezone.utc)
    ago = lambda **kw: (now - timedelta(**kw)).isoformat()
    async with repo.db_context() as db:
        pid = (await (await db.execute("SELECT id FROM projects LIMIT 1")).fetchone())["id"]
        t = {x["key"]: x for x in await repo.list_tasks(db, pid)}
        calm = await load_view(db, pid, now)
        assert not any(r.level == "high" for r in calm.risks)

        # T3 blocked for 5 h on the critical path, T4 overdue and its owner silent
        await db.execute("UPDATE tasks SET status='blocked', on_critical_path=1 WHERE id=?", (t["T3"]["id"],))
        await repo.create_blocker(db, task_id=t["T3"]["id"], description="test credentials", kind="task",
                                  linked_task_id=t["T2"]["id"], now=ago(hours=5))
        await db.execute("UPDATE tasks SET deadline=?, last_followup_at=? WHERE id=?",
                         (ago(hours=1), ago(hours=9), t["T4"]["id"]))
        view = await load_view(db, pid, now)
        risks = {r.task_key: r for r in view.risks}
        assert risks["T3"].level == "high"
        assert "Blocked 5 h on test credentials" in risks["T3"].why and "critical path" in risks["T3"].why
        assert "Rohan" in risks["T3"].action                                  # names who can unblock it
        assert "Overdue by 60 min" in risks["T4"].why and "has not replied" in risks["T4"].why
        assert [r.level for r in view.risks[:2]] == ["high", "high"]           # high risks come first, ties by deadline
        assert view.risks[0].task_key == "T4"                                  # T4's deadline already passed
        board = {x["key"]: x for x in view.tasks}
        assert board["T3"]["risk"]["level"] == "high" and board["T3"]["waiting_on"] == []

        md = (await reports.generate_report(db, pid, "risk", now=now))["content_md"]
        assert md.startswith("# Risk report: FestPass")
        row = next(line for line in md.splitlines() if line.startswith("| T3 "))
        assert row.count("|") == 6 and "High" in row and "Rohan" in row
        assert "Rules applied: blocked > 120 min" in md

        digest = await reports.generate_report(db, pid, "digest", now=now)
        for heading in ("Done since last update", "In progress", "Blocked", "Waiting on others", "At risk"):
            assert f"**{heading}**" in digest["content_md"]
        assert "T3 Connect the payment API (Kabir): test credentials" in digest["content_md"]
        assert "2/8 complete" in digest["content_md"]
        assert "<b>FestPass: update</b>" in digest["telegram_html"] and "&" not in digest["telegram_html"].replace("&amp;", "")
        # the next digest only reports what finished since this one
        second = await reports.generate_report(db, pid, "digest", now=now + timedelta(minutes=1))
        assert "**Done since last update**\n- none" in second["content_md"]

        export = await reports.build_export_md(db, pid, now)
        assert export.splitlines()[0] == "# FestPass: task status"
        assert "Critical path: " in export and "## Open blockers" in export
        assert "- T3 · test credentials · linked to T2 (Rohan) · open 5 h" in export
