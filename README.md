# Cadence: AI group project coordinator

Your team talks to a Telegram bot in plain words ("done", "stuck on credentials", "kal tak ho jayega").
Cadence turns that into task updates, chases blockers, warns about risk, and shows all of it live on a
website. The lead can also act from the website, and the team hears about it on Telegram.

```
 Telegram ──► bot ──► Coordinator (LLM) ──► Policy Engine ──► SQLite ──► live stream ──► website
    ▲                       proposes            decides           │                        │
    └──────── outbox ◄── notifications ◄── dependency engine ◄────┴──── REST API ◄─────────┘
```

Agents propose, code decides: the LLM never writes to the database. Every change has a reason, a
source message and a rule behind it, and is shown on the dashboard.

## Run it

You need Python 3.11+, Node 20+, and Docker (for the login database). Copy `.env.example` to `.env`.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\...
docker compose up -d                  # Postgres, login API (:8001) and the website (:5173)
.venv/bin/python -m app.db.seed_demo  # optional: the FestPass demo project
.venv/bin/python -m app.main          # Cadence API, bot and scheduler (:8000)
```

Open http://localhost:5173, sign up, and the board is there. `SECRET_KEY` in `.env` must be the same
random value for the login API and Cadence.

### Create the Telegram bot (2 minutes, you have to do this part)

1. In Telegram open **@BotFather**, send `/newbot`, pick a name, and copy the token.
2. Run `python -m scripts.setup_bot <TOKEN>`. It checks the token, saves it to `.env`, publishes the
   command menu and description, removes any webhook, and tells you if another program is already
   using the token.
3. Start the app. Each teammate opens their invite link from the **Team** tab, which looks like
   `https://t.me/<bot>?start=<code>`.
4. Optional: add the bot to your team group, and the lead sends `/linkgroup` there for the daily digest.

**One token, one running copy.** Telegram lets only one program poll a bot. If two copies run, both
get `409 Conflict`. Give every developer their own bot, or revoke the token in BotFather
(`/revoke`) if it has leaked. Never paste logs that contain the token.

## What the team can do on Telegram

| | |
|---|---|
| Plain messages | "done", "stuck on test credentials", "slides done, video left", Hinglish |
| Buttons | answer any question the bot asks; they never go through the LLM |
| `/mytasks` `/next` `/status` | see your tasks, your next ready task, the overview |
| `/done T3` `/blocked T3 why` `/undo` | explicit updates, still checked by the Policy Engine |
| `/pause 3` | no reminders for 3 hours (`/pause 0` resumes) |
| `/digest` `/risk` | post a report (the lead anywhere, anyone in the linked team group) |
| `/linkgroup` | the lead sends this in the team group |

## What the website shows (updates in well under a second)

Board with owner, "waiting on" badges, blockers, flags and the last quote · task drawer with the full
timeline, conversation and lead override · dependency graph with the critical path · live activity feed
that explains *why* each change happened (the policy rule that fired) · plan review · digest and risk
reports (post to Telegram from the page) · `export.md` living task doc · team panel with invite links,
QR codes and GitHub usernames.

## "Done" is checked against GitHub

When someone says a task is done, Cadence looks for a commit or pull request **by their GitHub
account** that matches the task. Set `GITHUB_REPO` (and a read-only `GITHUB_TOKEN`) in `.env` and give
each teammate a GitHub username on the Team tab. A match marks the task *verified* and keeps the commit
as evidence. Someone else's commit, or no commit, leaves it *complete (unverified)*, asks for a link,
and tells the lead. Try it: `python -m scripts.check_git_claim <user> T3 "task title" "what they said"`.

## How it maps to the spec

Tier 1 (the required loop), Tier 2 (clarify, undo, multi-task, manual override, LLM fallback) and Tier 3
(dependencies and propagation, blocker routing, escalation ladder, digest, risk and critical path,
living task doc, handoffs, "done" verification) are all implemented. Spec: `Cadence_ AI Group Project
Coordinator — Spec v0.1.md`. Not built: stretch goals S1-S5 (group chat reading, meeting slots, Slack,
voice notes, re-plan diff).

## Tests

```bash
.venv/bin/python -m pytest -q
```

`tests/test_e2e_telegram_website.py` runs the real bot, policy engine, outbox and HTTP API against a
pretend Telegram (`tests/fake_telegram.py`) and a scripted Coordinator, and checks all four sides of each
scenario: what the bot said, the database, the website API and the live event stream. No network, no
token and no LLM are needed.
