"""
app/tools/git_checker.py — Git claim checker, a tool for the Coordinator pipeline.

When someone says a task is done, this checks GitHub for proof that *they* did
the work: a commit or pull request authored by their GitHub account, made after
the task existed, that plausibly matches the task.

Like the Coordinator itself it only proposes (spec D2). It returns a
GitVerification and the Policy Engine decides what happens (rules R7a/R7b).
It never writes to the DB and never raises on network or API failure: those
come back as status="error" so the message loop keeps working.

Lookup order:
  1. Explicit references in the message or completion_evidence
     (commit SHA, commit URL, PR URL, "PR #42") → check each one's author.
  2. Otherwise search: the claimant's commits on the default branch since the
     task was created, plus their pull requests (which covers feature-branch
     work), scored against the task key, title and claim text.
  3. If nothing of theirs matches, look for a matching commit by someone else
     and report it as author_mismatch.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from app.config import settings

log = logging.getLogger(__name__)

VerificationStatus = Literal[
    "verified",         # matching work authored by the claimant
    "weak_match",       # work by the claimant, but not clearly this task
    "author_mismatch",  # the referenced or matching work belongs to someone else
    "not_found",        # nothing by the claimant that matches
    "no_username",      # the person has no GitHub username on file; we never guess one
    "skipped",          # checker not configured
    "error",            # GitHub unreachable or returned an error
]

VERIFY_THRESHOLD = 0.5
WEAK_THRESHOLD = 0.2
MAX_CANDIDATES = 5      # commits whose file lists are fetched for scoring
MAX_EXPLICIT_REFS = 3   # explicit SHAs / PRs checked per claim


# ══════════════════════════════════════════════════════════════════════════════
#  Result models
# ══════════════════════════════════════════════════════════════════════════════

class CommitEvidence(BaseModel):
    sha: str
    url: str
    message: str                       # first line only
    author_login: str | None = None
    authored_at: str | None = None
    files: list[str] = []
    additions: int = 0
    deletions: int = 0
    signature_verified: bool = False   # GPG/SSH signature checked by GitHub
    score: float = 0.0

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


class PullRequestEvidence(BaseModel):
    number: int
    url: str
    title: str
    author_login: str | None = None
    state: str                         # open | closed
    merged: bool = False
    score: float = 0.0


class GitVerification(BaseModel):
    status: VerificationStatus
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason: str                        # lower-case clause; templates embed it mid-sentence
    repo: str | None = None
    github_username: str | None = None
    evidence_url: str | None = None
    commits: list[CommitEvidence] = []
    pull_request: PullRequestEvidence | None = None

    @property
    def is_verified(self) -> bool:
        return self.status == "verified"

    @property
    def checked(self) -> bool:
        """True when GitHub was actually consulted and gave an answer."""
        return self.status not in ("skipped", "error", "no_username")


class GitRefs(BaseModel):
    shas: list[str] = []
    pr_numbers: list[int] = []
    foreign_repos: list[str] = []      # GitHub links that point outside the configured repo


class GitHubError(Exception):
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  Reference extraction and scoring (pure functions)
# ══════════════════════════════════════════════════════════════════════════════

_COMMIT_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/commit/([0-9a-f]{7,40})", re.I)
_PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_ANY_URL = re.compile(r"https?://\S+", re.I)
_PR_REF = re.compile(r"(?:\bPR\s*#?|\bpull request\s*#?|(?<![\w/&])#)(\d{1,6})\b", re.I)
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)

_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "this", "that", "have", "has",
    "was", "are", "were", "been", "done", "finished", "completed", "complete",
    "update", "updated", "updates", "add", "added", "adds", "fix", "fixed",
    "fixes", "task", "file", "files", "just", "now", "all", "its", "our", "your",
    "also", "some", "made", "make", "changes", "changed", "change", "work",
    "working", "merge", "merged", "branch", "pull", "request", "commit",
    "main", "master", "wip", "final", "set", "setup", "bhai", "gaya", "hogaya",
}


def extract_refs(text: str | None, repo: str) -> GitRefs:
    """Pull commit SHAs and PR numbers out of free text, keeping only the configured repo."""
    refs = GitRefs()
    if not text:
        return refs
    repo_l = repo.lower()

    def _same_repo(found: str) -> bool:
        if found.lower() == repo_l:
            return True
        if found not in refs.foreign_repos:
            refs.foreign_repos.append(found)
        return False

    for found, sha in _COMMIT_URL.findall(text):
        if _same_repo(found) and sha.lower() not in refs.shas:
            refs.shas.append(sha.lower())
    for found, number in _PR_URL.findall(text):
        if _same_repo(found) and int(number) not in refs.pr_numbers:
            refs.pr_numbers.append(int(number))

    # Bare refs, with URLs removed so their path segments are not re-read.
    bare = _ANY_URL.sub(" ", text)
    for number in _PR_REF.findall(bare):
        if int(number) not in refs.pr_numbers:
            refs.pr_numbers.append(int(number))
    for sha in _SHA.findall(bare):
        # A SHA mixes digits and letters; this skips words like "deadbeef" and plain numbers.
        if any(c.isdigit() for c in sha) and any(c.isalpha() for c in sha):
            if sha.lower() not in refs.shas:
                refs.shas.append(sha.lower())
    return refs


def _tokens(text: str | None) -> set[str]:
    words = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS and not w.isdigit()}


def _overlap(wanted: set[str], have: set[str]) -> float:
    """Share of `wanted` tokens present in `have`; prefix match covers plurals and tenses."""
    if not wanted:
        return 0.0
    hits = 0
    for w in wanted:
        if w in have or any(
            min(len(w), len(h)) >= 4 and (h.startswith(w) or w.startswith(h)) for h in have
        ):
            hits += 1
    return hits / len(wanted)


def score_text(text: str, *, task_key: str, task_title: str, claim_text: str = "") -> float:
    """How strongly a commit message / PR title (+ file names) matches the task. 0–1."""
    score = 0.0
    if task_key and re.search(
        rf"(?<![A-Za-z0-9]){re.escape(task_key)}(?![A-Za-z0-9])", text, re.I
    ):
        score += 0.6
    have = _tokens(text)
    score += 0.6 * _overlap(_tokens(task_title), have)
    score += 0.3 * _overlap(_tokens(claim_text), have)
    return round(min(score, 1.0), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  GitHub access
# ══════════════════════════════════════════════════════════════════════════════

def make_client() -> httpx.AsyncClient:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return httpx.AsyncClient(
        base_url=settings.github_api_url,
        headers=headers,
        timeout=settings.github_timeout_s,
    )


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None):
    """GET a GitHub API path. Returns None for 404/422 (unknown SHA or PR)."""
    resp = await client.get(path, params=params)
    if resp.status_code in (404, 422):
        return None
    if resp.status_code == 401:
        raise GitHubError("GitHub rejected the token (401)")
    if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
        raise GitHubError("GitHub rate limit reached")
    if resp.status_code != 200:
        raise GitHubError(f"GitHub API returned {resp.status_code}")
    return resp.json()


def _same_login(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.lower() == b.lower())


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _github_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit_from_api(data: dict) -> CommitEvidence:
    commit = data.get("commit") or {}
    files = data.get("files") or []
    return CommitEvidence(
        sha=data["sha"],
        url=data.get("html_url") or "",
        message=(commit.get("message") or "").split("\n")[0],
        author_login=(data.get("author") or {}).get("login"),
        authored_at=(commit.get("author") or {}).get("date"),
        files=[f["filename"] for f in files],
        additions=sum(f.get("additions", 0) for f in files),
        deletions=sum(f.get("deletions", 0) for f in files),
        signature_verified=bool((commit.get("verification") or {}).get("verified")),
    )


def _pr_from_api(data: dict) -> PullRequestEvidence:
    return PullRequestEvidence(
        number=data["number"],
        url=data.get("html_url") or "",
        title=data.get("title") or "",
        author_login=(data.get("user") or {}).get("login"),
        state=data.get("state") or "open",
        merged=bool(data.get("merged_at")),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

async def verify_claim(
    *,
    task_key: str,
    task_title: str,
    github_username: str | None,
    claim_text: str = "",
    completion_evidence: str | None = None,
    since: datetime | None = None,
    repo: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> GitVerification:
    """
    Check whether `github_username` committed work matching this task.

    Args:
        task_key:            "T3". A word-boundary match in a commit message is strong evidence.
        task_title:          Task title; its words are matched against commits.
        github_username:     The claimant's GitHub login.
        claim_text:          What they said ("updated the title in the README").
        completion_evidence: Link or ref the Coordinator extracted, if any.
        since:               Ignore work older than this (task creation minus grace).
        repo:                "owner/repo"; defaults to GITHUB_REPO.
        client:              Reuse an httpx client (tests pass a MockTransport client).
    """
    repo = repo or settings.github_repo
    base = {"repo": repo or None, "github_username": github_username}
    if not repo:
        return GitVerification(status="skipped", reason="GITHUB_REPO is not set", **base)
    if not github_username:
        return GitVerification(
            status="no_username", reason="there is no GitHub username on file for this person", **base
        )
    username = github_username.lstrip("@")
    base["github_username"] = username

    refs = extract_refs(f"{completion_evidence or ''}\n{claim_text}", repo)
    owns_client = client is None
    client = client or make_client()
    try:
        if refs.shas or refs.pr_numbers:
            result = await _verify_explicit(
                client, repo=repo, username=username, refs=refs, since=since, base=base,
            )
        else:
            result = await _search(
                client, repo=repo, username=username, task_key=task_key,
                task_title=task_title, claim_text=claim_text, since=since, base=base,
            )
        if refs.foreign_repos and not result.is_verified:
            result.reason += f" (the link points at {', '.join(refs.foreign_repos)}, not {repo})"
        return result
    except (GitHubError, httpx.HTTPError) as exc:
        log.warning("Git check failed for %s/%s: %s", username, task_key, exc)
        return GitVerification(status="error", reason=str(exc) or type(exc).__name__, **base)
    finally:
        if owns_client:
            await client.aclose()


async def _verify_explicit(
    client: httpx.AsyncClient,
    *,
    repo: str,
    username: str,
    refs: GitRefs,
    since: datetime | None,
    base: dict,
) -> GitVerification:
    """The claimant pointed at specific commits or PRs: check who authored them."""
    results: list[GitVerification] = []

    for sha in refs.shas[:MAX_EXPLICIT_REFS]:
        data = await _get(client, f"/repos/{repo}/commits/{sha}")
        if not data:
            results.append(GitVerification(
                status="not_found", reason=f"commit {sha[:7]} is not in {repo}", **base,
            ))
            continue
        commit = _commit_from_api(data)
        authored = _parse_time(commit.authored_at)
        found = {"commits": [commit], "evidence_url": commit.url}
        if _same_login(commit.author_login, username):
            if since and authored and authored < since:
                results.append(GitVerification(
                    status="weak_match", confidence=0.4,
                    reason=f"commit {commit.short_sha} by @{username} predates the task",
                    **found, **base,
                ))
            else:
                results.append(GitVerification(
                    status="verified", confidence=0.95,
                    reason=f"commit {commit.short_sha} by @{username}: {commit.message}",
                    **found, **base,
                ))
        elif commit.author_login:
            results.append(GitVerification(
                status="author_mismatch", confidence=0.9,
                reason=f"commit {commit.short_sha} was authored by @{commit.author_login}, not @{username}",
                **found, **base,
            ))
        else:
            results.append(GitVerification(
                status="weak_match", confidence=0.3,
                reason=f"commit {commit.short_sha} uses an email that isn't linked to a GitHub account",
                **found, **base,
            ))

    for number in refs.pr_numbers[:MAX_EXPLICIT_REFS]:
        data = await _get(client, f"/repos/{repo}/pulls/{number}")
        if not data:
            results.append(GitVerification(
                status="not_found", reason=f"PR #{number} is not in {repo}", **base,
            ))
            continue
        pr = _pr_from_api(data)
        found = {"pull_request": pr, "evidence_url": pr.url}
        state = "merged" if pr.merged else pr.state
        if _same_login(pr.author_login, username):
            results.append(GitVerification(
                status="verified", confidence=0.9 if pr.merged else 0.8,
                reason=f"PR #{pr.number} by @{username} ({state}): {pr.title}",
                **found, **base,
            ))
        else:
            results.append(GitVerification(
                status="author_mismatch", confidence=0.85,
                reason=f"PR #{pr.number} was opened by @{pr.author_login}, not @{username}",
                **found, **base,
            ))

    rank = {"verified": 0, "author_mismatch": 1, "weak_match": 2, "not_found": 3}
    return min(results, key=lambda r: (rank.get(r.status, 9), -r.confidence))


async def _search(
    client: httpx.AsyncClient,
    *,
    repo: str,
    username: str,
    task_key: str,
    task_title: str,
    claim_text: str,
    since: datetime | None,
    base: dict,
) -> GitVerification:
    """No explicit reference: look through the claimant's recent commits and PRs."""
    params: dict = {"author": username, "per_page": 100}
    if since:
        params["since"] = _github_time(since)
    commits_raw, prs_raw = await asyncio.gather(
        _get(client, f"/repos/{repo}/commits", params),
        _get(client, f"/repos/{repo}/pulls", {"state": "all", "per_page": 50,
                                              "sort": "updated", "direction": "desc"}),
    )
    commits_raw = commits_raw or []
    score = lambda text: score_text(  # noqa: E731
        text, task_key=task_key, task_title=task_title, claim_text=claim_text,
    )

    # Commits: rank on the message, then fetch file lists for the top few and re-score.
    ranked = sorted(
        commits_raw,
        key=lambda c: score((c.get("commit") or {}).get("message", "")),
        reverse=True,
    )[:MAX_CANDIDATES]
    details = await asyncio.gather(*(_get(client, f"/repos/{repo}/commits/{c['sha']}") for c in ranked))
    candidates: list[CommitEvidence] = []
    for data in details:
        if not data:
            continue
        commit = _commit_from_api(data)
        commit.score = score(" ".join([data["commit"].get("message", ""), *commit.files]))
        candidates.append(commit)
    candidates.sort(key=lambda c: c.score, reverse=True)

    # Pull requests by the claimant, created or updated since the task existed.
    pr_best: PullRequestEvidence | None = None
    for raw in prs_raw or []:
        if not _same_login((raw.get("user") or {}).get("login"), username):
            continue
        updated = _parse_time(raw.get("updated_at"))
        if since and updated and updated < since:
            continue
        pr = _pr_from_api(raw)
        pr.score = score(f"{pr.title} {(raw.get('head') or {}).get('ref', '')}")
        if not pr_best or pr.score > pr_best.score:
            pr_best = pr

    best_commit = candidates[0] if candidates else None
    commit_score = best_commit.score if best_commit else 0.0
    pr_score = pr_best.score if pr_best else 0.0

    if max(commit_score, pr_score) >= VERIFY_THRESHOLD:
        if commit_score >= pr_score:
            return GitVerification(
                status="verified", confidence=commit_score,
                reason=f"commit {best_commit.short_sha} by @{username}: {best_commit.message}",
                evidence_url=best_commit.url, commits=candidates[:3], **base,
            )
        state = "merged" if pr_best.merged else pr_best.state
        return GitVerification(
            status="verified", confidence=pr_score,
            reason=f"PR #{pr_best.number} by @{username} ({state}): {pr_best.title}",
            evidence_url=pr_best.url, pull_request=pr_best, commits=candidates[:3], **base,
        )

    # Nothing of theirs matches well. Did someone else do it?
    other = await _matching_commit_by_someone_else(
        client, repo=repo, username=username, since=since, score=score,
    )
    if other:
        return GitVerification(
            status="author_mismatch", confidence=other.score,
            reason=f"the matching commit {other.short_sha} was authored by "
                   f"@{other.author_login}, not @{username}",
            evidence_url=other.url, commits=[other, *candidates[:2]], **base,
        )

    window = f" since {since:%d %b %H:%M} UTC" if since else ""
    if max(commit_score, pr_score) >= WEAK_THRESHOLD:
        best_desc = (
            f"commit {best_commit.short_sha} ({best_commit.message})"
            if commit_score >= pr_score else f"PR #{pr_best.number} ({pr_best.title})"
        )
        return GitVerification(
            status="weak_match", confidence=max(commit_score, pr_score),
            reason=f"the closest match by @{username} is {best_desc}, which doesn't clearly cover this task",
            evidence_url=best_commit.url if commit_score >= pr_score else pr_best.url,
            commits=candidates[:3], pull_request=pr_best, **base,
        )
    if not commits_raw and not pr_best:
        reason = f"there are no commits or PRs by @{username} in {repo}{window}"
    else:
        reason = f"none of the {len(commits_raw)} commits by @{username} in {repo}{window} match this task"
    return GitVerification(status="not_found", reason=reason, commits=candidates[:3], **base)


async def _matching_commit_by_someone_else(
    client: httpx.AsyncClient,
    *,
    repo: str,
    username: str,
    since: datetime | None,
    score,
) -> CommitEvidence | None:
    params: dict = {"per_page": 50}
    if since:
        params["since"] = _github_time(since)
    best: CommitEvidence | None = None
    for raw in await _get(client, f"/repos/{repo}/commits", params) or []:
        login = (raw.get("author") or {}).get("login")
        if not login or _same_login(login, username):
            continue
        commit = _commit_from_api(raw)
        commit.score = score((raw.get("commit") or {}).get("message", ""))
        if commit.score >= VERIFY_THRESHOLD and (not best or commit.score > best.score):
            best = commit
    return best


async def verify_updates(
    interpretation,
    *,
    sender: dict,
    sender_tasks: list[dict],
    open_question: dict | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, GitVerification]:
    """
    Run the checker for every completion claim in a Coordinator Interpretation.

    Checks a task when the sender claims it complete, or sends evidence for a
    task that is already complete (the VERIFY_COMPLETION follow-up), and the
    task either requires evidence or the message carries a link/ref. Non-code
    tasks without evidence (slides, video) are left alone.

    Returns {task_key: GitVerification}, ready for policy.apply(verifications=...).
    """
    if not settings.git_check_enabled:
        return {}
    tasks = {t["key"]: t for t in sender_tasks}
    pq_key = None
    if open_question and open_question.get("task_id"):
        pq_key = next((t["key"] for t in sender_tasks if t["id"] == open_question["task_id"]), None)

    jobs: dict[str, dict] = {}
    for update in interpretation.updates:
        key = update.task_key or pq_key
        task = tasks.get(key or "")
        if not task or key in jobs:
            continue
        claims_done = update.status == "complete" or (
            update.status is None and task["status"] == "complete" and update.completion_evidence
        )
        if not claims_done:
            continue
        if not (task.get("requires_evidence") or update.completion_evidence):
            continue
        created = _parse_time(task.get("created_at"))
        jobs[key] = dict(
            task_key=key,
            task_title=task["title"],
            github_username=sender.get("github_username"),
            claim_text=interpretation.raw_message or update.evidence or "",
            completion_evidence=update.completion_evidence,
            since=created - timedelta(hours=settings.git_check_grace_hours) if created else None,
        )
    if not jobs:
        return {}

    owns_client = client is None
    client = client or make_client()
    try:
        results = await asyncio.gather(
            *(verify_claim(client=client, **job) for job in jobs.values())
        )
    finally:
        if owns_client:
            await client.aclose()
    for key, result in zip(jobs, results):
        log.info("Git check %s for %s: %s (%s)", key, sender.get("name"), result.status, result.reason)
    return dict(zip(jobs, results))
