"""Git claim checker: ref parsing, scoring, GitHub lookups (mocked), and policy rules R7a/R7b."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx

from app.agents.schemas import Interpretation, TaskUpdate
from app.config import settings
from app.core.policy import apply as policy_apply
from app.db import repo
from app.db.seed_demo import seed
from app.tools.git_checker import (
    GitVerification,
    extract_refs,
    score_text,
    verify_claim,
    verify_updates,
)

REPO = "team/festpass"
SINCE = datetime(2026, 10, 15, tzinfo=timezone.utc)


# ── fake GitHub ────────────────────────────────────────────────────────────────

def _commit(sha, login, message, files=(), date="2026-10-16T10:00:00Z"):
    return {
        "sha": sha,
        "html_url": f"https://github.com/{REPO}/commit/{sha}",
        "author": {"login": login} if login else None,
        "commit": {
            "message": message,
            "author": {"name": login or "someone", "date": date},
            "verification": {"verified": False},
        },
        "files": [{"filename": f, "additions": 3, "deletions": 1} for f in files],
    }


def _pr(number, login, title, branch="feature", merged=True):
    return {
        "number": number,
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "title": title,
        "user": {"login": login},
        "state": "closed" if merged else "open",
        "merged_at": "2026-10-16T12:00:00Z" if merged else None,
        "updated_at": "2026-10-16T12:00:00Z",
        "head": {"ref": branch},
    }


def fake_github(commits: list[dict], prs: list[dict] | None = None) -> httpx.AsyncClient:
    by_sha = {c["sha"]: c for c in commits}
    by_pr = {p["number"]: p for p in prs or []}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{path}?{request.url.query.decode()}")
        prefix = f"/repos/{REPO}"
        if path == f"{prefix}/commits":
            author = request.url.params.get("author")
            listed = [c for c in commits if not author or (c["author"] or {}).get("login") == author]
            return httpx.Response(200, json=[{k: v for k, v in c.items() if k != "files"} for c in listed])
        if path.startswith(f"{prefix}/commits/"):
            sha = path.rsplit("/", 1)[1]
            match = by_sha.get(sha) or next((c for s, c in by_sha.items() if s.startswith(sha)), None)
            return httpx.Response(200, json=match) if match else httpx.Response(404, json={})
        if path == f"{prefix}/pulls":
            return httpx.Response(200, json=list(by_pr.values()))
        if path.startswith(f"{prefix}/pulls/"):
            pr = by_pr.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=pr) if pr else httpx.Response(404, json={})
        return httpx.Response(404, json={})

    client = httpx.AsyncClient(base_url="https://api.github.test", transport=httpx.MockTransport(handler))
    client.calls = calls  # type: ignore[attr-defined]
    return client


def _check(client, **kwargs) -> GitVerification:
    defaults = dict(task_key="T3", task_title="Connect the payment API", github_username="kabir",
                    since=SINCE, repo=REPO, client=client)
    return asyncio.run(verify_claim(**{**defaults, **kwargs}))


# ── pure helpers ───────────────────────────────────────────────────────────────

def test_extract_refs():
    refs = extract_refs(
        "done! https://github.com/team/festpass/commit/abc1234def and PR #42, "
        "also https://github.com/other/fork/pull/7",
        REPO,
    )
    assert refs.shas == ["abc1234def"]
    assert refs.pr_numbers == [42]
    assert refs.foreign_repos == ["other/fork"]
    # words made only of hex letters, and plain numbers, are not SHAs
    assert extract_refs("deadbeef facade 1234567", REPO).shas == []
    assert extract_refs("see https://github.com/team/festpass/pull/9", REPO).pr_numbers == [9]


def test_score_text():
    title = "Connect the payment API"
    assert score_text("T3: wire razorpay", task_key="T3", task_title=title) >= 0.5
    assert score_text("connect payment api client", task_key="T3", task_title=title) >= 0.5
    assert score_text("T30 unrelated", task_key="T3", task_title=title) < 0.2
    assert score_text("style navbar", task_key="T3", task_title=title) == 0
    # file names count, and the claim text helps
    assert score_text("Edit title README.md", task_key="T9", task_title="Update project title",
                      claim_text="updated the project title in the README") >= 0.5


# ── GitHub lookups ─────────────────────────────────────────────────────────────

def test_search_finds_own_commit():
    client = fake_github([
        _commit("aaa1111", "kabir", "style tweaks"),
        _commit("bbb2222", "kabir", "T3 connect payment API", files=["api/payments.py"]),
    ])
    result = _check(client, claim_text="payment api connected")
    assert result.status == "verified"
    assert result.evidence_url.endswith("bbb2222")
    assert result.commits[0].files == ["api/payments.py"]
    assert any("author=kabir" in call and "since=2026-10-15" in call for call in client.calls)


def test_search_finds_pr_from_feature_branch():
    client = fake_github([], prs=[_pr(42, "kabir", "Payment API integration", branch="t3-payment-api")])
    result = _check(client)
    assert result.status == "verified"
    assert result.pull_request.number == 42


def test_someone_elses_commit_is_author_mismatch():
    client = fake_github([_commit("ccc3333", "rohan", "T3: connect payment API")])
    result = _check(client, claim_text="done")
    assert result.status == "author_mismatch"
    assert "@rohan" in result.reason and "@kabir" in result.reason


def test_nothing_found():
    client = fake_github([_commit("ddd4444", "kabir", "fix navbar colours")])
    result = _check(client)
    assert result.status == "not_found"
    assert "none of the 1 commits by @kabir" in result.reason


def test_explicit_sha_checks_author_and_date():
    commits = [
        _commit("abc1234ff", "kabir", "payments"),
        _commit("bcd2345ff", "rohan", "payments"),
        _commit("cde3456ff", "kabir", "old work", date="2026-09-01T00:00:00Z"),
    ]
    assert _check(fake_github(commits), completion_evidence="abc1234").status == "verified"
    assert _check(fake_github(commits), completion_evidence="bcd2345").status == "author_mismatch"
    assert _check(fake_github(commits), completion_evidence="cde3456").status == "weak_match"
    assert _check(fake_github(commits), completion_evidence="fff9999").status == "not_found"


def test_explicit_pr():
    prs = [_pr(42, "kabir", "Payments"), _pr(43, "rohan", "Payments")]
    assert _check(fake_github([], prs), claim_text="done, PR #42").status == "verified"
    assert _check(fake_github([], prs), claim_text="see PR 43").status == "author_mismatch"


def test_skip_and_error_paths():
    # No username on file is its own outcome: we never guess one, and we never call GitHub for it.
    nobody = fake_github([])
    result = _check(nobody, github_username=None)
    assert result.status == "no_username" and not result.checked and nobody.calls == []
    saved, settings.github_repo = settings.github_repo, ""
    try:
        assert _check(fake_github([]), repo="").status == "skipped"
    finally:
        settings.github_repo = saved

    def boom(request):
        raise httpx.ConnectError("offline")

    broken = httpx.AsyncClient(base_url="https://api.github.test", transport=httpx.MockTransport(boom))
    result = _check(broken)
    assert result.status == "error" and not result.checked

    limited = httpx.AsyncClient(
        base_url="https://api.github.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(403, headers={"x-ratelimit-remaining": "0"})),
    )
    assert "rate limit" in _check(limited).reason


def test_verify_updates_picks_completion_claims():
    settings.github_repo = REPO
    try:
        tasks = [
            {"id": 1, "key": "T3", "title": "Connect the payment API", "status": "in_progress",
             "requires_evidence": 1, "created_at": "2026-10-16 08:00:00"},
            {"id": 2, "key": "T7", "title": "Record demo video", "status": "pending",
             "requires_evidence": 0, "created_at": "2026-10-16 08:00:00"},
        ]
        interp = Interpretation(raw_message="T3 done, video done too", updates=[
            TaskUpdate(task_key="T3", status="complete"),
            TaskUpdate(task_key="T7", status="complete"),        # no evidence needed → not checked
        ])
        client = fake_github([_commit("bbb2222", "kabir", "T3 connect payment API")])
        result = asyncio.run(verify_updates(
            interp, sender={"name": "Kabir", "github_username": "kabir"}, sender_tasks=tasks, client=client,
        ))
        assert list(result) == ["T3"]
        assert result["T3"].is_verified
        # the task's creation time (minus the grace window) bounds the search
        assert any("since=2026-10-15T08" in call for call in client.calls)
    finally:
        settings.github_repo = ""


# ── Policy Engine ──────────────────────────────────────────────────────────────

def test_policy_git_rules(tmp_path):
    settings.database_path = str(tmp_path / "git.db")
    asyncio.run(_policy_rules())


async def _policy_rules():
    await seed(force=True)
    now = "2026-10-16T15:00:00+00:00"
    async with repo.db_context() as db:
        project_id = (await (await db.execute(
            "SELECT id FROM projects WHERE name = 'FestPass'"
        )).fetchone())["id"]
        people = {p["name"]: p for p in await repo.list_participants(db, project_id)}
        kabir = people["Kabir"]

        def claim(**check):
            return dict(
                interpretation=Interpretation(
                    intent="status_update", raw_message="T3 done",
                    updates=[TaskUpdate(task_key="T3", status="complete", status_confidence=0.95)],
                ),
                sender=kabir, project_id=project_id, source_message_id=None, db=db, now=now,
                verifications={"T3": GitVerification(**check)} if check else None,
            )

        # R7a: verified → complete + verified, evidence is the commit URL
        ok = await policy_apply(**claim(
            status="verified", confidence=0.9, reason="commit bbb2222 by @kabir: T3 payments",
            evidence_url="https://github.com/team/festpass/commit/bbb2222",
        ))
        assert ok.approved and ok.approved[0].rule_fired == "R7a"
        assert ok.approved[0].verified is True
        assert ok.approved[0].completion_evidence.endswith("bbb2222")
        assert "needs_verification" in ok.approved[0].flags_to_remove
        assert not ok.clarifications

        # R7b: not found on an evidence-required task → complete, unverified, ask for a link
        missing = await policy_apply(**claim(status="not_found", reason="no commits by @kabir"))
        assert missing.approved[0].rule_fired == "R7b"
        assert missing.approved[0].verified is False
        assert missing.approved[0].flags_to_add == ["needs_verification"]
        templates = [m.template_key for m in missing.notifications._messages]
        assert templates == ["GIT_UNVERIFIED"]

        # R7b: someone else's commit also alerts the lead
        disputed = await policy_apply(**claim(
            status="author_mismatch", reason="commit ccc3333 was authored by @rohan, not @kabir",
        ))
        recipients = {m.template_key: m.participant_id for m in disputed.notifications._messages}
        assert recipients["GIT_UNVERIFIED"] == kabir["id"]
        assert recipients["GIT_CLAIM_MISMATCH"] == people["Aanya"]["id"]

        # GitHub down → old R7 path (complete unverified, VERIFY_COMPLETION), loop keeps going
        down = await policy_apply(**claim(status="error", reason="GitHub API returned 502"))
        assert down.approved[0].rule_fired == "R7"
        assert [m.template_key for m in down.notifications._messages] == ["VERIFY_COMPLETION"]

        # Executing R7a writes verified=1, the evidence URL, and a "verified" event
        from app.telegram.router import _execute_update

        async def _sse(*_):
            return None

        await _execute_update(ok.approved[0], project_id, kabir["id"], None, db, now, _sse)
        task = await repo.get_task_by_key(db, project_id, "T3")
        assert task["status"] == "complete" and task["verified"] == 1
        assert task["completion_evidence"].endswith("bbb2222")
        assert "needs_verification" not in json.loads(task["flags_json"])
        events = [e["event_type"] for e in await repo.list_task_events(db, task["id"])]
        assert "verified" in events


def test_old_database_gets_github_column(tmp_path):
    import aiosqlite

    path = str(tmp_path / "old.db")

    async def run():
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "CREATE TABLE participants (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
                "name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', skills TEXT, "
                "telegram_chat_id INTEGER UNIQUE, telegram_username TEXT, invite_code TEXT NOT NULL UNIQUE, "
                "onboarded_at TEXT, last_seen_at TEXT, paused_until TEXT)"
            )
            await db.commit()
        await repo.init_db(path)
        async with aiosqlite.connect(path) as db:
            cols = {row[1] for row in await (await db.execute("PRAGMA table_info(participants)")).fetchall()}
        assert "github_username" in cols

    asyncio.run(run())
