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

## Deploy it (the bot runs in ONE place, not on laptops)

On any Linux server or VM with Docker (a small cloud VM is enough):

```bash
git clone https://github.com/SahilJ1305/Cadence.git && cd Cadence
cp .env.example .env        # then fill in the values below
docker compose -f docker-compose.prod.yml up -d --build
```

Fill in `.env`:

| Setting | What to put |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The token from @BotFather (see below). **Only on this server.** |
| `SECRET_KEY` | One long random value: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | Any strong password for the login database |
| `LLM_PROVIDER` + keys | `azure` with `AZURE_AI_*`, or `ollama` with `OLLAMA_BASE_URL` and model names |
| `FRONTEND_URL`, `PUBLIC_AUTH_API_URL`, `PUBLIC_CADENCE_API_URL` | The public addresses of the dashboard and the two APIs |
| `DEMO_MODE` | `false` for a real team (see below) |
| `GITHUB_REPO`, `GITHUB_TOKEN` | Optional: lets Cadence check "done" claims against commits |

Then `python -m scripts.setup_bot` once (from any machine that has the token) to publish the bot's menu
and confirm nobody else is polling it. The dashboard is on port 80, the API on 8000, logins on 8001; put
a reverse proxy with HTTPS in front for real use. Back up the `cadence_data` volume (the project database).

GitHub Actions (`.github/workflows/ci.yml`) runs the tests and builds every image on each push, so
nothing needs to be run locally to know the code is healthy.

### Run it on your own machine (teammates)

Everyone can run the whole project independently from a fresh clone. You need **Python 3.11+** and
**Node 20+**; Docker is optional. Your copy has its own database, its own logins and its own bot (or none).

```bash
git clone https://github.com/SahilJ1305/Cadence.git && cd Cadence
python -m venv .venv                                   # Windows: .venv\Scriptsctivate
.venv/bin/pip install -r requirements.txt              # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m scripts.init_env                   # creates your .env with fresh secrets
```

Then start the three pieces (each in its own terminal):

| Piece | With Docker | Without Docker |
|---|---|---|
| Login service (:8001) | `DB_PORT=5433 docker compose up -d db backend` (skip `DB_PORT` unless 5432 is taken) | `python -m scripts.init_env --no-docker`, then `pip install -r backend/requirements.txt` and `cd backend && uvicorn main:app --port 8001` |
| Cadence API (:8000) | `python -m app.db.seed_demo` (optional demo project), then `python -m app.main` | same |
| Dashboard (:5173) | `cd frontend && npm install && npm run dev` | same |

Open http://localhost:5173, sign up with any email, and you will see the demo project. To check your
setup without starting anything: `python -m pytest -q` (49 tests, no keys or bot needed).

What you can and cannot do without secrets:

| You have | You get |
|---|---|
| Nothing extra | The dashboard, API, demo project, every test |
| An AI key (ask the project owner through a password manager, or use your own) | The bot understands free-text replies and the planner turns a spec into tasks. Without it the bot falls back to button questions, and one-word replies like "done" still work |
| **Your own** Telegram bot (free, from @BotFather) | The live bot on your machine. Never use the team bot's token on a laptop |

The team's bot runs on the server only. Two copies sharing a token answer every message twice.
Your `.env` is git-ignored. Never commit it, and never copy someone else's.

### Create the Telegram bot (2 minutes, a person has to do this)

1. In Telegram open **@BotFather**, send `/newbot`, pick a name, and copy the token.
2. Run `python -m scripts.setup_bot <TOKEN>`. It checks the token, saves it to `.env`, publishes the
   command menu and description, removes any webhook, and tells you if another program already polls it.
3. Each teammate opens their invite link from the **Team** tab (`https://t.me/<bot>?start=<code>`).
4. Optional: add the bot to your team group, and the lead sends `/linkgroup` there for the daily digest.

**One token, one running copy.** If two copies poll the same token, Telegram answers both with
`409 Conflict`; messages are answered twice, or by a copy whose database has different data. This is
the usual cause of "everyone got duplicate messages" and "I see someone else's tasks". Never share the
token, never paste logs that contain it, and `/revoke` it in BotFather if it leaks.

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
