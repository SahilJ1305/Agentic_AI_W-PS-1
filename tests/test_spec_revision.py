"""Meeting notes → spec v2: the notes are read, and applying v2 adds tasks without resetting live statuses."""
from __future__ import annotations

import asyncio
import json
import pathlib

from app.core import spec_revision
from app.core.spec_revision import SpecChange, SpecRevision, meeting_notes
from tests.e2e_world import World

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"


def test_meeting_notes_reads_the_summary_export():
    notes = meeting_notes(json.loads((DOCS / "cadence_meeting_summary.json").read_text()))
    assert "Dependency Review Bot" in notes and "[00:29:13]" in notes and "## Action items" in notes


def test_apply_v2_adds_tasks_and_keeps_live_status(tmp_path, monkeypatch):
    asyncio.run(_apply(tmp_path, monkeypatch))


async def _apply(tmp_path, monkeypatch):
    v1 = (DOCS / "depguard_spec_detailed.md").read_text()
    row = "| T16 | Sandbox the fuzzing runner | Priya | pending | | T9 | yes | M2 | Done means: fuzzers run in a container. |"
    v2 = v1.replace("| T15 |", row + "\n| T15 |", 1).replace("| T3 | Build Dependency Review Bot API | Neha", "| T3 | Build Dependency Review Bot API | Vikram")

    async def fake_llm(*_args, **_kw):
        return SpecRevision(spec_md=v2, changes=[SpecChange(kind="added", section="Tasks", summary="T16")])
    monkeypatch.setattr(spec_revision, "call_llm", fake_llm)

    async with World(tmp_path) as w:
        pid = (await w.http.post("/api/projects", json={"name": "DepGuard"})).json()["id"]
        await w.http.post(f"/api/projects/{pid}/documents", data={"kind": "spec"},
                          files={"file": ("depguard.md", v1.encode(), "text/markdown")})
        t3 = next(t for t in (await w.http.get(f"/api/projects/{pid}/tasks")).json() if t["key"] == "T3")
        await w.http.patch(f"/api/tasks/{t3['id']}", json={"status": "complete", "reason": "x", "expected_version": t3["version"]})

        preview = (await w.http.post(f"/api/projects/{pid}/meeting", files={"file": ("m.json", b'{"executive_summary": "x"}')})).json()
        assert preview["filename"] == "depguard-v2.md" and preview["version"] == 2
        await w.http.post(f"/api/projects/{pid}/documents", data={"kind": "spec"},
                          files={"file": (preview["filename"], preview["spec_md"].encode(), "text/markdown")})

        tasks = {t["key"]: t for t in (await w.http.get(f"/api/projects/{pid}/tasks")).json()}
        assert tasks["T16"]["owner_name"] == "Priya"
        assert tasks["T3"]["status"] == "complete" and tasks["T3"]["owner_name"] == "Vikram"
