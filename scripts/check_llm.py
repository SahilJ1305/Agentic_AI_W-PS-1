"""
Send one real coordinator call and one real planner call to the configured provider.

    .venv/bin/python -m scripts.check_llm            # both agents
    .venv/bin/python -m scripts.check_llm coordinator

Uses a throwaway database, so llm_calls in data/cadence.db are untouched.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]


def _describe() -> None:
    print(f"LLM_PROVIDER={settings.llm_provider}")
    if settings.llm_provider == "azure":
        print(f"  endpoint     {settings.azure_ai_endpoint or '(empty)'}")
        print(f"  api version  {settings.azure_ai_api_version or '(none)'}")
        print(f"  api key      {'set' if settings.azure_ai_api_key else '(empty)'}")
        print(f"  coordinator  {settings.azure_coordinator_deployment or '(empty)'}")
        print(f"  planner      {settings.azure_planner_deployment or '(empty)'}")
    else:
        print(f"  ollama       {settings.ollama_base_url}")
        print(f"  coordinator  {settings.coordinator_model or '(empty)'}")
        print(f"  planner      {settings.planner_model or '(empty)'}")


async def _coordinator(db) -> None:
    from app.agents.coordinator import run_coordinator

    started = time.monotonic()
    result = await run_coordinator(
        now="2026-10-17T14:05:00+05:30",
        sender_name="Kabir",
        pending_question={"kind": "status_check", "task_key": "T3", "created_at": "14:00"},
        sender_tasks=[{
            "key": "T3", "title": "Connect the payment API", "status": "pending",
            "deadline": "2026-10-17T20:00:00+05:30",
        }],
        task_index=[
            {"key": "T1", "title": "Set up backend and database", "owner_name": "Rohan", "status": "complete"},
            {"key": "T2", "title": "Set up payment gateway sandbox account", "owner_name": "Rohan", "status": "pending"},
        ],
        recent_messages=[],
        message_text="The API is connected, but I am waiting for test credentials.",
        db=db,
    )
    elapsed = time.monotonic() - started
    update = result.updates[0] if result.updates else None
    blocker = update.blocker.description if update and update.blocker else None
    linked = update.blocker.suspected_task_key if update and update.blocker else None
    print(f"coordinator OK in {elapsed:.1f}s")
    print(f"  intent={result.intent} task={update.task_key if update else None} "
          f"status={update.status if update else None} blocker={blocker!r} linked_task={linked}")
    print("  expected: status=blocked (policy also forces this), blocker about test credentials, linked_task=T2")


async def _planner(db) -> None:
    from app.agents.planner import run_planner

    spec = (ROOT / "docs" / "demo-spec.md").read_text()
    started = time.monotonic()
    draft = await run_planner(
        project_name="FestPass",
        now="2026-10-17T10:00:00+05:30",
        timezone=settings.timezone,
        roster=[
            {"name": "Aanya", "role": "lead", "skills": "design,slides,pitching"},
            {"name": "Kabir", "role": "member", "skills": "backend,apis"},
            {"name": "Meera", "role": "member", "skills": "frontend"},
            {"name": "Rohan", "role": "member", "skills": "backend,devops"},
        ],
        spec_text=spec,
        db=db,
    )
    elapsed = time.monotonic() - started
    keys = [task.key for task in draft.tasks]
    owners = {task.key: task.owner_name for task in draft.tasks}
    print(f"planner OK in {elapsed:.1f}s")
    print(f"  tasks={len(draft.tasks)} {keys}")
    print(f"  T3 owner={owners.get('T3')} dependencies={len(draft.dependencies)} warnings={len(draft.warnings)}")
    print("  expected: 8 tasks T1-T8, T3 owned by Kabir")


async def main(which: list[str]) -> int:
    from app.db import repo
    from app.llm.gateway import LLMFailure

    _describe()
    tmp = tempfile.mkdtemp(prefix="cadence-llm-")
    settings.database_path = str(Path(tmp) / "check.db")
    await repo.init_db()
    failed = 0
    for name, run in (("coordinator", _coordinator), ("planner", _planner)):
        if which and name not in which:
            continue
        print()
        try:
            async with repo.db_context() as db:
                await run(db)
        except LLMFailure as exc:
            failed += 1
            print(f"{name} FAILED: {exc}")
        async with repo.db_context() as db:
            cursor = await db.execute(
                "SELECT provider, model, parsed_ok, latency_ms, error FROM llm_calls "
                "WHERE agent = ? ORDER BY id",
                (name,),
            )
            for row in await cursor.fetchall():
                err = (row["error"] or "")[:160]
                print(f"  call: {row['provider']} {row['model']} parsed={bool(row['parsed_ok'])} "
                      f"{row['latency_ms']}ms {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
