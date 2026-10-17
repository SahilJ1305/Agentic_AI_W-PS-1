"""The lead hears about every task change, can unblock from the alert, and controls the team summary."""
from __future__ import annotations

import asyncio

from app.telegram.gateway import parse_every
from tests.e2e_world import World


def test_parse_every():
    assert parse_every("2h") == 2 and parse_every("0.5h") == 0.5 and parse_every("0.2") == 0.2
    assert parse_every("30m") == 0.5 and parse_every("off") == 0 and parse_every("0") == 0
    assert parse_every("0,5h") == 0.5 and parse_every("2 h") == 2
    assert parse_every("soon") is None and parse_every("100h") is None and parse_every("1m") is None


def test_lead_alert_unblock_button_and_summary(tmp_path):
    asyncio.run(_flow(tmp_path))


async def _flow(tmp_path):
    async with World(tmp_path) as w:
        await w.onboard_everyone()
        await w.say("Kabir", "/blocked T3 test credentials missing")

        alert = w.bot.last(101)
        assert "Kabir" in alert["text"] and "T3" in alert["text"] and "Blocked" in alert["text"]
        assert w.bot.buttons(alert) == ["✅ Unblock Kabir"]

        await w.chat["Aanya"].press(alert, "✅ Unblock Kabir")
        await w.deliver()
        assert "Cleared the blocker on T3" in w.bot.last(101)["text"]
        assert "cleared your blocker" in w.bot.last(102)["text"]
        assert (await w.tasks())["T3"]["status"] == "in_progress"

        await w.say("Aanya", "/update_every 0.2h")
        assert "12 min" in w.bot.last(101)["text"]
        await w.say("Aanya", "/update_now")
        summary = w.bot.last(101)["text"]
        assert "done" in summary and "Every 12 min" in summary

        await w.say("Kabir", "/update_now")
        assert "go to the lead" in w.bot.last(102)["text"]

        # /undo is reported too, and the lead's own changes are not echoed back to them.
        await w.say("Kabir", "/done T3")
        assert "→ <b>Done</b>" in w.bot.last(101)["text"]
        await w.say("Kabir", "/undo")
        assert w.bot.last(101)["text"].startswith("↩️")
        before = len(w.bot.to(101))
        await w.say("Aanya", "/blocked T1 venue not confirmed")
        assert not any("Aanya</b> ·" in m["text"] for m in w.bot.to(101)[before:])
