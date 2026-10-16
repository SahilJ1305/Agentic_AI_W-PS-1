"""
Connect Cadence to a (new) Telegram bot and configure it.

    # 1. In Telegram, open @BotFather → /newbot → copy the token it gives you.
    # 2. Then:
    .venv/bin/python -m scripts.setup_bot <TOKEN>      # saves the token into .env
    .venv/bin/python -m scripts.setup_bot              # re-check the token already in .env

What it does:
  - verifies the token with Telegram (getMe) and prints the bot's @username
  - writes TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME into .env (token is never printed)
  - removes any webhook (the app uses polling) and clears the old command menu
  - publishes the command menu and the bot's description
  - warns if another program is already polling this token (the 409 Conflict)

Stop the app before running it: the conflict check polls Telegram once.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

COMMANDS = [
    ("start", "Join your project with your invite link"),
    ("mytasks", "Your tasks"),
    ("next", "Your next ready task"),
    ("status", "Project overview"),
    ("done", "Mark a task done: /done T3"),
    ("blocked", "Report a blocker: /blocked T3 reason"),
    ("undo", "Undo your last update"),
    ("pause", "Pause reminders: /pause 3 (hours)"),
    ("digest", "Post the project digest"),
    ("risk", "Post the risk report"),
    ("help", "What I understand"),
]
DESCRIPTION = (
    "Cadence keeps your group project moving. Tell me how your tasks are going in plain words "
    "(\"done\", \"stuck on X\", \"kal tak ho jayega\") and I update the board, chase blockers and "
    "warn your lead about risks."
)
TOKEN_SHAPE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


def call(token: str, method: str, **payload) -> dict:
    response = httpx.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=20)
    data = response.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram rejected {method}: {data.get('description', response.status_code)}")
    return data["result"]


def read_env_token() -> str:
    if ENV.exists():
        match = re.search(r"^TELEGRAM_BOT_TOKEN=([^\s#]+)", ENV.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    return ""


def write_env(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{key}=.*$", re.M)
    text = pattern.sub(lambda _: line, text) if pattern.search(text) else text.rstrip("\n") + f"\n{line}\n"
    ENV.write_text(text, encoding="utf-8")


def main() -> None:
    token = (sys.argv[1] if len(sys.argv) > 1 else read_env_token()).strip()
    if not token:
        raise SystemExit("No token. Create a bot with @BotFather, then run: python -m scripts.setup_bot <TOKEN>")
    if not TOKEN_SHAPE.match(token):
        raise SystemExit("That doesn't look like a bot token (expected 123456789:AA...). Copy it from @BotFather.")

    me = call(token, "getMe")
    username = me["username"]
    print(f"Bot verified: @{username} ({me['first_name']})")

    if len(sys.argv) > 1:
        write_env("TELEGRAM_BOT_TOKEN", token)
        print("Saved TELEGRAM_BOT_TOKEN to .env")
    write_env("TELEGRAM_BOT_USERNAME", username)
    print(f"Saved TELEGRAM_BOT_USERNAME={username} to .env")

    hook = call(token, "getWebhookInfo")
    if hook.get("url"):
        call(token, "deleteWebhook", drop_pending_updates=False)
        print("Removed an existing webhook (Cadence uses polling).")

    call(token, "deleteMyCommands")
    call(token, "setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
    call(token, "setMyDescription", description=DESCRIPTION)
    call(token, "setMyShortDescription", short_description="Cadence keeps your group project on track.")
    print(f"Published {len(COMMANDS)} commands and the description.")

    # When two programs poll one token, Telegram ends the OLDER request with 409. So hold one
    # request open for 12 s: a competing client's next poll would knock it out.
    print("Checking that nobody else is polling this token (12 s)...")
    try:
        probe = httpx.post(f"https://api.telegram.org/bot{token}/getUpdates",
                           json={"timeout": 12, "limit": 1}, timeout=25)
        if probe.status_code == 409:
            print("WARNING: another program is polling this token (409 Conflict). Stop the other copy,")
            print("         or revoke the token in @BotFather (/revoke) and run this script with the new one.")
        else:
            print("No competing poller seen.")
    except httpx.HTTPError as exc:
        print(f"(skipped the conflict check: {exc})")

    print("\nNext steps")
    print(f"  1. Start Cadence:        .venv/bin/python -m app.main")
    print(f"  2. Open the dashboard, create a project, and copy each teammate's invite link:")
    print(f"       https://t.me/{username}?start=<invite-code>")
    print( "  3. Optional, for the daily digest in your team group: add the bot to the group,")
    print( "     then the lead sends /linkgroup in that group.")
    print( "  4. In @BotFather you may also run /setjoingroups → Enable if the bot must join groups.")


if __name__ == "__main__":
    main()
