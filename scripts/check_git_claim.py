"""
Run the Git claim checker against the real GitHub repo, without the bot or DB.

    .venv/bin/python -m scripts.check_git_claim <github_user> <task_key> "<task title>" ["<claim text>"]
    .venv/bin/python -m scripts.check_git_claim mayuresh T1 "Update project title in README" \
        "I have updated the project title in the README file"
    .venv/bin/python -m scripts.check_git_claim mayuresh T1 "README title" "done, see PR #12"

Options:
    --repo owner/repo   override GITHUB_REPO
    --days N            only count work from the last N days (default 14)
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.tools.git_checker import verify_claim


async def _main(args: argparse.Namespace) -> int:
    repo = args.repo or settings.github_repo
    print(f"repo   {repo or '(GITHUB_REPO empty)'}")
    print(f"token  {'set' if settings.github_token else '(none: public repos only, 60 req/h)'}")
    print(f"claim  @{args.user} says {args.task_key} '{args.title}' is done: {args.claim!r}\n")

    result = await verify_claim(
        task_key=args.task_key,
        task_title=args.title,
        github_username=args.user,
        claim_text=args.claim,
        since=datetime.now(timezone.utc) - timedelta(days=args.days),
        repo=repo,
    )
    print(f"status      {result.status} (confidence {result.confidence:.2f})")
    print(f"reason      {result.reason}")
    if result.evidence_url:
        print(f"evidence    {result.evidence_url}")
    if result.pull_request:
        pr = result.pull_request
        print(f"PR          #{pr.number} {pr.title} by @{pr.author_login} ({'merged' if pr.merged else pr.state})")
    for commit in result.commits:
        signed = ", signed" if commit.signature_verified else ""
        print(f"commit      {commit.short_sha} score {commit.score:.2f} by @{commit.author_login}{signed}: {commit.message}")
        for name in commit.files[:10]:
            print(f"              {name}")
    return 0 if result.is_verified else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user", help="claimant's GitHub login")
    parser.add_argument("task_key", help='task key, e.g. "T3"')
    parser.add_argument("title", help="task title")
    parser.add_argument("claim", nargs="?", default="", help="what the person said")
    parser.add_argument("--repo", default="")
    parser.add_argument("--days", type=float, default=14)
    raise SystemExit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
