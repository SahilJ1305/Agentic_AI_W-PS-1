"""
Create your own .env from .env.example, with fresh random secrets.

    python -m scripts.init_env               # login service on Postgres (Docker)
    python -m scripts.init_env --no-docker   # login service on a local SQLite file, no Docker needed

It fills in the values that are yours alone (SECRET_KEY, POSTGRES_PASSWORD), never overwrites an
existing .env, and tells you what is still empty. Your .env is git-ignored: never commit it, and never
copy another person's, because the Telegram token and AI key in it are shared secrets.
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def set_value(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{key}=[^\n#]*", re.M)
    if pattern.search(text):
        return pattern.sub(lambda _: f"{key}={value}", text, count=1)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-docker", action="store_true", help="run the login service on SQLite instead of Postgres")
    parser.add_argument("--out", default=str(ROOT / ".env"), help="where to write (default: .env in the repo root)")
    args = parser.parse_args()

    target = Path(args.out)
    template = ROOT / ".env.example"
    if target.exists():
        print(f"{target} already exists, so I left it alone. Delete it first if you want a fresh one.")
        return 1
    if not template.exists():
        print(".env.example is missing; run this from a full checkout.")
        return 1

    text = template.read_text(encoding="utf-8")
    text = set_value(text, "SECRET_KEY", secrets.token_urlsafe(48))
    text = set_value(text, "POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    if args.no_docker:
        text = set_value(text, "DATABASE_URL", "sqlite:///./accounts.db")
    target.write_text(text, encoding="utf-8")

    print(f"Created {target} with a fresh SECRET_KEY" + (" and a SQLite login database." if args.no_docker else "."))
    print("\nStill empty, and what each one unlocks:")
    print("  TELEGRAM_BOT_TOKEN   your OWN bot from @BotFather (never the team's); without it the dashboard and")
    print("                       API still run, the bot just stays off. Then: python -m scripts.setup_bot <TOKEN>")
    print("  AZURE_AI_* / models  the AI that reads messages and plans projects. Ask the project owner for access")
    print("                       (through a password manager, not chat) or use your own. Without it the bot falls")
    print("                       back to button questions, and one-word replies like 'done' still work.")
    print("  GITHUB_REPO/TOKEN    optional: verify 'done' claims against commits")
    print("\nNext: see 'Develop on your own machine' in the README.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
