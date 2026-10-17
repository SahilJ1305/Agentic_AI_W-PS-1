#!/usr/bin/env python3
"""Builds the three architecture diagrams in docs/architecture/ (SVG, logos embedded).

    python docs/architecture/build_diagrams.py

Standard library only. If Pillow is installed it also warns when text would overflow a box.
Edit the text or layout here, re-run, and commit the regenerated SVGs.
"""
from __future__ import annotations

from pathlib import Path

from diagram_kit import FAINT, INK, MUTED, PAL, Doc

OUT = Path(__file__).parent


# =====================================================================================
#  Part 1: system architecture
# =====================================================================================
def part1() -> Doc:
    d = Doc(
        1560, 1310,
        "Cadence: system architecture",
        "Who talks to whom, and which technology runs each piece. Every box is a real module in this repo.",
        part="Part 1 of 3",
    )

    d.begin_shift(-85)
    # ---- people and Telegram (left column) --------------------------------------------
    d.card(30, 270, 190, 120, "Project lead", ["uses the web dashboard:", "creates projects, reviews", "plans, overrides tasks"],
           color="slate", header=40, size=12.5)
    d.browser(158, 8 + 270 - 2, 48, 26)
    d.card(30, 560, 190, 92, "Team members", ["chat with the bot on", "their Telegram app"],
           color="slate", header=40, size=12.5)
    d.person(192, 630, "#94A3B8", 0.55)
    d.card(30, 695, 190, 350, "Telegram", [], logos=("telegram",), color="blue", header=44)
    for i, t in enumerate(["Bot API in the cloud", "created with @BotFather", "", "The bot long-polls it,",
                           "so no public URL or", "webhook is needed", "", "Optional team group chat",
                           "receives the daily digest"]):
        d.text(46, 764 + i * 20, t, size=12.5, fill=INK)
    d.logo("telegram", 75, 920, 84)
    d.arrow([(125, 652), (125, 695)], "#229ED9")
    d.text(136, 678, "words, buttons", size=11, fill=MUTED, maxw=88)

    # ---- docker group -------------------------------------------------------------------
    d.group(260, 205, 960, 910, "Your server: Docker Compose (docker-compose.prod.yml)", "slate", logos=("docker",))

    # Row A: dashboard, Postgres, accounts
    A = 270
    d.card(290, A, 280, 200, "Dashboard", [
        "React 19 + Vite + Tailwind CSS 4", "served by nginx on port 80", "board, graph, activity feed,",
        "plan review, reports, team tab", "axios (REST) + EventSource (SSE)"],
        logos=("react", "vite", "tailwindcss"), color="sky", size=12.5)
    d.chip(304, A + 160, "nginx :80", logo="nginx", color="sky", size=12)
    d.card(600, A + 40, 280, 120, "PostgreSQL 16", ["users table only (logins)", "volume: pgdata"],
           logos=("postgresql",), color="data")
    d.card(910, A, 280, 200, "Accounts service", [
        "backend/ · FastAPI on :8001", "sign-up, login, Google sign-in,", "password-reset code by email",
        "SQLAlchemy models + Alembic", "signs a JWT with SECRET_KEY"],
        logos=("fastapi", "jsonwebtokens"), color="teal", size=12.5)
    d.arrow([(910, A + 100), (880, A + 100)], "#0F766E", both=True)

    # Cadence container
    C = 505
    d.rect(275, C, 930, 590, "#F5F7FF", PAL["indigo"][0], 1.8, rx=14)
    d.logo("python", 640, C + 8, 26)
    d.logo("fastapi", 672, C + 8, 26)
    d.text(1190, C + 27, "cadence container: python -m app.main, exactly ONE replica", size=13.5, weight=700,
           fill=PAL["indigo"][0], anchor="end")

    cx = [290, 600, 910]
    ry = [C + 45, C + 182, C + 319, C + 456]
    W, H = 280, 112
    sz = 12.5

    def box(col, row, title, lines, **kw):
        d.card(cx[col], ry[row], W, H, title, lines, size=sz, **kw)

    box(0, 0, "REST API + live stream", ["FastAPI :8000 · routes under /api", "verifies the login JWT", "SSE /stream pushes live events"],
        logos=("fastapi",), color="indigo")
    box(1, 0, "Scheduler", ["APScheduler: cron + interval", "check-ins 10:00 and 18:00", "digest 21:00 · ladder every 60 s"],
        logos=("python",), color="indigo")
    box(2, 0, "Planner agent", ["spec (+ task doc) → plan JSON", "tasks, owners, dependencies", "thinking on, up to 120 s"],
        logos=("pydantic",), color="purple")
    box(0, 1, "Telegram gateway", ["python-telegram-bot, long polling", "commands, buttons, group digest", "ONE running copy per bot token"],
        logos=("telegram", "python"), color="blue")
    box(1, 1, "Coordinator agent", ["message → JSON interpretation", "intent, task, status, confidence", "only proposes, never writes"],
        logos=("pydantic",), color="purple")
    box(2, 1, "LLM gateway", ["primary → OpenCode → buttons", "1 repair retry on bad JSON", "every call logged (llm_calls)"],
        color="purple")
    box(0, 2, "Router (the pipeline)", ["per-user lock, 1.5 s debounce", "one-word replies skip the LLM", "context → AI → rules → write"],
        logos=("python",), color="indigo")
    box(1, 2, "Policy engine R1–R16", ["pure code: no AI, no DB writes", "approve, ask a question or refuse", "records the rule that fired"],
        color="amber")
    box(2, 2, "Git claim checker", ["on “done”: finds THEIR commit/PR", "GitHub REST API via httpx", "verified · weak · mismatch"],
        logos=("github",), color="slate")
    box(0, 3, "Outbox worker", ["durable queue table in SQLite", "dedupe keys, no duplicate sends", "quiet window for nudges (R16)"],
        logos=("telegram",), color="blue")
    box(1, 3, "Engines (core/)", ["dependency graph + critical path", "escalation ladder, nudges", "digest, risk report, export.md"],
        color="amber")
    box(2, 3, "SQLite (WAL mode)", ["one file: tasks, events, messages…", "the single source of truth", "volume cadence_data: back it up"],
        logos=("sqlite",), color="data")

    # internal flow arrows (primary path)
    ink = "#334155"
    d.arrow([(cx[0] + 140, ry[1] + H), (cx[0] + 140, ry[2])], ink)                           # gateway -> router
    mid = 585
    d.arrow([(cx[0] + W, ry[2] + 56), (mid, ry[2] + 56), (mid, ry[1] + 56), (cx[1], ry[1] + 56)], ink)  # router -> coordinator
    d.arrow([(cx[1] + W, ry[1] + 56), (cx[2], ry[1] + 56)], "#7C3AED", both=True)             # coordinator <-> llm gw
    d.arrow([(cx[1] + 140, ry[1] + H), (cx[1] + 140, ry[2])], ink)                           # coordinator -> policy
    d.arrow([(cx[2], ry[2] + 56), (cx[1] + W, ry[2] + 56)], ink)                             # git -> policy
    d.arrow([(cx[1] + 140, ry[2] + H), (cx[1] + 140, ry[3])], ink)                           # policy -> engines
    d.arrow([(cx[1], ry[3] + 56), (cx[0] + W, ry[3] + 56)], ink)                             # engines -> outbox
    d.arrow([(cx[1] + W, ry[3] + 56), (cx[2], ry[3] + 56)], "#0369A1")                       # engines -> sqlite
    d.arrow([(cx[2] + 140, ry[0] + H), (cx[2] + 140, ry[1])], "#7C3AED", both=True)          # planner <-> llm gw

    # ---- right column: external services ---------------------------------------------------
    R = 1260
    d.service(R, A, 270, 60, "Google OAuth", "“Sign in with Google”", logo="google")
    d.service(R, A + 70, 270, 60, "Gmail SMTP", "password-reset codes", logo="gmail")
    d.service(R, A + 140, 270, 60, "Supabase Storage", "optional file uploads", logo="supabase")
    d.group(R, C + 15, 270, 285, "LLM providers", "purple", dashed=False)
    d.service(R + 10, C + 50, 250, 72, "Ollama", "own GPU server, reached", logo="ollama", color="purple",
              sub2="over an SSH tunnel :11435")
    d.service(R + 10, C + 130, 250, 72, "Azure AI Foundry", "coordinator + planner", logo="azure", color="purple",
              sub2="deployments")
    d.service(R + 10, C + 210, 250, 72, "OpenCode Console", "free-tier fallback model", monogram="OC", color="purple",
              sub2="used if the primary fails")
    d.service(R, C + 320, 270, 90, "GitHub", "commits and pull requests", logo="github", color="slate",
              sub2="read-only token (optional)")

    # arrows to externals
    for dy in (30, 100, 170):
        d.arrow([(1190, A + dy), (R, A + dy)], "#0F766E", dashed=True)
    d.arrow([(cx[2] + W, ry[1] + 56), (R, ry[1] + 56)], "#7C3AED", both=True)
    d.arrow([(cx[2] + W, ry[2] + 56), (R, C + 365)], "#475569")

    # ---- numbered paths --------------------------------------------------------------------
    d.arrow([(220, A + 60), (290, A + 60)], "#0284C7")
    d.badge(255, A + 60, 1)
    # dashboard -> accounts (sign in) goes over the top of PostgreSQL
    d.arrow([(430, A), (430, 246), (1050, 246), (1050, A)], "#0F766E")
    d.badge(740, 246, 2)
    d.arrow([(430, A + 200), (430, ry[0])], "#0284C7", both=True)
    d.badge(430, C + 15, 3)
    d.arrow([(1050, A + 200), (1050, C)], "#4F46E5", dashed=True)
    d.label(1050, A + 218, "same SECRET_KEY", "#4F46E5", size=11.5)
    d.arrow([(220, ry[1] + 56), (cx[0], ry[1] + 56)], "#229ED9", both=True)
    d.badge(255, ry[1] + 56, 4)
    d.arrow([(cx[0], ry[3] + 56), (220, ry[3] + 56)], "#229ED9")
    d.badge(255, ry[3] + 56, 5)
    d.badge(1235, ry[1] + 56, 6)
    d.badge(1235, ry[2] + 70, 7)
    d.badge(1235, A + 100, 8)

    # ---- legend ------------------------------------------------------------------------------
    LY = 1145
    d.rect(30, LY, 900, 222, "#F8FAFC", "#CBD5E1", 1.4, rx=14)
    d.text(50, LY + 28, "How to read it: the numbered arrows", size=15, weight=700)
    steps = [
        "The lead opens the dashboard (nginx serves the React app).",
        "Sign-in goes to the accounts service, which checks Postgres and returns a JWT.",
        "The dashboard calls the Cadence API with that JWT and listens to live events (SSE).",
        "A teammate messages the bot; the gateway receives it by long polling.",
        "Replies, check-ins and alerts leave through the outbox back to Telegram.",
        "Both agents ask an LLM through one gateway with a fallback chain.",
        "“Done” claims are checked against the person's own GitHub commits or PRs.",
        "The accounts service uses Google, Gmail and Supabase for sign-in, reset codes and files.",
    ]
    for i, s in enumerate(steps):
        y = LY + 54 + i * 20.5
        d.badge(60, y - 4, i + 1, "#1E293B", r=9)
        d.text(78, y, s, size=12.5, maxw=835)
    d.text(50, LY + 54 + 8 * 20.5 + 2, "Dashed teal = optional/auxiliary calls · dashed indigo = shared secret, not data",
           size=11.5, fill=MUTED)

    d.card(960, LY, 570, 100, "CI: GitHub Actions", ["on every push: pytest, dashboard build,", "docker compose build (nothing is pushed)"],
           logos=("githubactions", "docker", "python"), color="slate", header=40, size=12.5)
    d.rect(960, LY + 118, 570, 104, "#EEF2FF", PAL["indigo"][0], 1.8, rx=14)
    d.text(1245, LY + 150, "Agents propose, code decides", size=19, weight=800, fill=PAL["indigo"][0], anchor="middle")
    d.text(1245, LY + 176, "The LLM never writes to the database. Every change has a reason,", size=12.5,
           fill=INK, anchor="middle")
    d.text(1245, LY + 195, "a source message and a rule behind it, and is shown on the dashboard.", size=12.5,
           fill=INK, anchor="middle")
    d.end_shift()
    return d


# =====================================================================================
#  Part 2: one message, end to end
# =====================================================================================
def part2() -> Doc:
    d = Doc(
        1610, 1435,
        "One message, end to end",
        "What happens when Kabir sends the bot: “stuck on test credentials”. Follow the numbers (the path snakes).",
        part="Part 2 of 3",
    )
    X = [30, 570, 1110]
    Y = [110, 424, 738, 1052]
    W, H = 470, 272

    steps = [
        # (num, title, logos, color, lines)
        (1, "Someone messages the bot", ("telegram",), "blue", [
            "“stuck on test credentials”, “kal tak ho jayega”,",
            "a button tap, or a command like /done T3.",
            "",
            "Telegram's Bot API holds it until our bot",
            "asks for it (long polling): no public URL,",
            "no webhook, no inbound firewall rule.",
        ]),
        (2, "Telegram gateway", ("telegram", "python"), "blue", [
            "python-telegram-bot receives the update.",
            "Buttons and /commands skip the LLM and",
            "go straight to the Policy engine (step 8).",
            "",
            "Privacy: personal commands work only in a",
            "private chat; only team members get answers.",
        ]),
        (3, "Router: save, merge, lock", ("sqlite", "python"), "indigo", [
            "Stores the raw text in SQLite (messages).",
            "Waits 1.5 s and merges a burst of lines.",
            "One lock per person: no racing updates.",
            "Tells the dashboard (message.in event).",
            "Bare “done” with several open tasks?",
            "→ asks “which one?” with buttons, no LLM.",
        ]),
        (4, "Build the context packet", ("sqlite",), "data", [
            "Read from SQLite, about 2k tokens:",
            "• the sender's tasks (+ open blocker text)",
            "• the question the bot last asked, if any",
            "• the last 6 messages with this person",
            "• titles of everyone else's tasks, so a",
            "  blocker can be matched to a real task",
        ]),
        (5, "Fast path or Coordinator?", ("pydantic",), "purple", [
            "One plain word (done, ok, blocked …) that",
            "matches one task → FAST PATH: no LLM call,",
            "instant answer (skips step 6).",
            "Anything else → Coordinator agent: system",
            "prompt + examples (Hinglish, multi-task,",
            "undo) + the context packet.",
        ]),
        (6, "LLM gateway", ("ollama", "azure"), "purple", [
            "Primary: Ollama (SSH tunnel) or Azure AI",
            "Foundry, picked by LLM_PROVIDER.",
            "Bad JSON → one repair retry, same provider.",
            "Still failing → OpenCode Console fallback.",
            "Reply is checked against a Pydantic schema",
            "(an Interpretation). Every call → llm_calls.",
            ("All providers down → R15: buttons, no guessing", PAL["red"][0], 700),
        ]),
        (7, "Git claim checker", ("github",), "slate", [
            "Runs only if the update says “complete”.",
            "Looks for a commit or PR by THEIR GitHub",
            "account (explicit link first, else a search",
            "since the task was created, scored against",
            "the task title and what they said).",
            "Result: verified · weak · mismatch · error.",
            "A GitHub outage never blocks the loop.",
        ]),
        (8, "Policy engine decides", (), "amber", [
            "Rules R1–R16, in order: pure code, no AI.",
            "R1–R3  wrong task or low confidence → ask",
            "R4  “done” + blocker → blocked (Kabir rule)",
            "R6  done while upstream open → confirm",
            "R7  git verified → verified, else flagged",
            "R8  reopen / undo · R10  blocked, no reason",
            "R11  blocker names a task → new dependency",
            "Output: approved updates, messages, rule log.",
        ]),
        (9, "Execute the approved updates", ("sqlite",), "data", [
            "Version-checked write to tasks (no lost updates).",
            "Append-only task_events: old → new, the",
            "reason, rule fired, source message, confidence.",
            "Blocker opened or resolved; a runtime",
            "dependency edge added when one is named.",
            "Undo works for 30 minutes (marked reverted).",
        ]),
        (10, "Dependency engine propagates", (), "amber", [
            "Task done → downstream tasks recomputed:",
            "waiting → ready, owners told “you're unblocked”.",
            "Blocker raised → the person who can fix it is",
            "asked (owner of the linked task, a named",
            "person, or the lead if it is external).",
            "Critical path and risk flags refreshed.",
        ]),
        (11, "Outbox sends the replies", ("telegram", "sqlite"), "blue", [
            "Messages are queued in the outbox table first.",
            "Worker polls every 0.25 s; replies go at once.",
            "Nudges wait out the quiet window (R16).",
            "Dedupe keys + claim-before-send: a message is",
            "never sent twice. Kabir gets his ack, the helper",
            "and the lead get their alerts.",
        ]),
        (12, "Dashboard updates live", ("react",), "sky", [
            "SSE broadcaster → the browser's EventSource.",
            "Events: message.in, interpretation,",
            "task.updated, blocker.raised, dependency.changed.",
            "Board, graph and feed refresh in well under 1 s.",
            "The feed says WHY: the rule that fired and the",
            "exact quote it came from.",
        ]),
    ]
    EX = {
        1: ["Kabir types “stuck on test credentials”;", "he owns T3 “Connect the payment API”."],
        2: ["Kabir joined with his invite link and is", "in a private chat, so he is accepted."],
        3: ["Saved as message #412. Nothing else arrives", "within 1.5 s, so the burst is one line."],
        4: ["Kabir owns T3 “Connect the payment API”.", "Others: T2 “Set up payment sandbox” (Rohan)…"],
        5: ["Not a one-word status, so the Coordinator", "agent is called."],
        6: ["Returns: T3 = blocked, blocker “test", "credentials”, suspected task T2 (0.8)."],
        7: ["Status is blocked, not complete → skipped."],
        8: ["R11: blocker matches T2 with confidence ≥ 0.7", "→ T3 blocked + new edge T2 → T3."],
        9: ["T3 → blocked; a blocker_raised event keeps the", "quote; runtime edge T2 → T3 is saved."],
        10: ["Rohan (owner of T2) is asked to unblock;", "T5 (Meera) keeps waiting behind T3."],
        11: ["Kabir: “Noted, I've asked Rohan.” Rohan gets", "an unblock request with buttons."],
        12: ["T3 turns red with “waiting on T2”; the graph", "shows the new edge; the feed cites R11."],
    }
    pos = {}
    for i, s in enumerate(steps):
        row, k = divmod(i, 3)
        col = k if row % 2 == 0 else 2 - k
        pos[s[0]] = (X[col], Y[row])
    for num, title, logos, color, lines in steps:
        x, y = pos[num]
        d.card(x, y, W, H, title, lines, logos=logos, color=color, num=num, size=13, example=EX[num])

    # arrows between consecutive cards
    for n in range(1, 12):
        (x1, y1), (x2, y2) = pos[n], pos[n + 1]
        col = "#334155"
        if y1 == y2:   # same row
            if x2 > x1:
                d.arrow([(x1 + W, y1 + H / 2), (x2, y2 + H / 2)], col, width=2.6)
            else:
                d.arrow([(x1, y1 + H / 2), (x2 + W, y2 + H / 2)], col, width=2.6)
        else:          # next row, same column
            d.arrow([(x1 + W / 2, y1 + H), (x2 + W / 2, y2)], col, width=2.6)

    # footer legend
    FY = 1355
    d.rect(30, FY, 1550, 62, "#F8FAFC", "#CBD5E1", 1.4, rx=12)
    x = 48
    for name, color, label in [("blue", "blue", "Telegram"), ("data", "data", "SQLite data"), ("indigo", "indigo", "Cadence code"),
                               ("purple", "purple", "LLM / agents"), ("amber", "amber", "Deterministic rules"),
                               ("sky", "sky", "Dashboard"), ("red", "red", "Failure path")]:
        stroke, bg = PAL[color]
        d.rect(x, FY + 20, 22, 22, bg, stroke, 1.6, rx=6)
        d.text(x + 30, FY + 36, label, size=12.5)
        x += 30 + len(label) * 8 + 24
    d.text(1565, FY + 28, "Latency: one-word reply ≈ instant · reply that needs the LLM ≈ 3–8 s", size=12,
           fill=MUTED, anchor="end")
    d.text(1565, FY + 48, "Dashboard push: well under 1 s", size=12, fill=MUTED, anchor="end")
    return d


# =====================================================================================
#  Part 3: project lifecycle, automation, data
# =====================================================================================
def part3() -> Doc:
    d = Doc(
        1610, 1580,
        "Setup, automation and data",
        "How a project is created, what the bot does on its own every day, and where everything is stored.",
        part="Part 3 of 3",
    )

    def band(y, title, sub, color):
        stroke, bg = PAL[color]
        d.rect(30, y, 1550, 38, bg, stroke, 1.6, rx=10)
        d.text(48, y + 25, title, size=17, weight=800, fill=stroke)
        d.text(1562, y + 25, sub, size=12.5, fill=MUTED, anchor="end")

    # ---- A: setup --------------------------------------------------------------------
    band(100, "A  ·  Day 0: set up a project (the lead, on the dashboard)", "once per project", "teal")
    X = [30, 570, 1110]
    W, H = 470, 218
    A = [
        (1, "Sign up or log in", ("postgresql", "google", "jsonwebtokens"), "teal", [
            "Email + password, or “Sign in with Google”.",
            "The accounts service checks PostgreSQL and",
            "returns a JWT (HS256, SECRET_KEY, 12 h).",
            "Forgot password: a code is emailed (Gmail",
            "SMTP). The Cadence API verifies the same JWT",
            "and stores no passwords at all.",
        ]),
        (2, "Create the project, upload the spec", ("react", "sqlite"), "sky", [
            "spec.md + the roster table (name, role, skills);",
            "optionally a task table (“task doc”).",
            "Originals are stored unchanged with a SHA-256",
            "(source_documents, UTF-8 text files).",
            "Team members are created from the roster, each",
            "with a unique invite code.",
        ]),
        (3, "Planner agent drafts the plan", ("pydantic", "ollama", "azure"), "purple", [
            "Spec + roster → a PlanDraft (JSON): tasks,",
            "owners, deadlines, dependencies, with a reason",
            "and a confidence for every edge.",
            "Thinking mode on, up to 120 s, so it runs as a",
            "background task.",
            "Task table supplied? It is imported directly.",
        ]),
        (4, "Validate, then the lead reviews", ("react",), "sky", [
            "Graph checks: unknown keys dropped, cycles",
            "broken (weakest edge), redundant edges marked.",
            "Edge confidence ≥ 0.8 is accepted, 0.5–0.8 is",
            "only proposed, below 0.5 is dropped.",
            "Plan review: the lead rejects or edits edges;",
            "rejected edges stay rejected.",
        ]),
        (5, "Commit the plan", ("sqlite",), "data", [
            "Tasks, milestones and dependencies are written.",
            "Every task is waiting or ready; the critical",
            "path is marked; the project becomes active.",
            "Each step is an audit event with its reason.",
        ]),
        (6, "Onboard the team", ("telegram",), "blue", [
            "Team tab: invite link + QR code per person",
            "(t.me/<bot>?start=<code>).",
            "/start links their Telegram chat to the project.",
            "Optional: /linkgroup in the team group for the",
            "daily digest; add each person's GitHub username",
            "for the “done” checker.",
        ]),
    ]
    pos = {1: (X[0], 155), 2: (X[1], 155), 3: (X[2], 155), 4: (X[2], 405), 5: (X[1], 405), 6: (X[0], 405)}
    for num, title, logos, color, lines in A:
        x, y = pos[num]
        d.card(x, y, W, H, title, lines, logos=logos, color=color, num=num, size=13)
    for n in range(1, 6):
        (x1, y1), (x2, y2) = pos[n], pos[n + 1]
        if y1 == y2 and x2 > x1:
            d.arrow([(x1 + W, y1 + H / 2), (x2, y2 + H / 2)], "#334155", width=2.6)
        elif y1 == y2:
            d.arrow([(x1, y1 + 115), (x2 + W, y2 + 115)], "#334155", width=2.6)
        else:
            d.arrow([(x1 + W / 2, y1 + H), (x2 + W / 2, y2)], "#334155", width=2.6)

    # ---- B: automation -----------------------------------------------------------------
    BY = 655
    band(BY, "B  ·  Every day: the bot acts on its own (APScheduler, no human message needed)",
         "DEMO_MODE shrinks every timer for a live demo", "indigo")
    cw, gap = 370, 23.3
    colx = [30 + i * (cw + gap) for i in range(4)]
    cy, ch = BY + 55, 290
    d.card(colx[0], cy, cw, ch, "Check-ins", [
        "Cron: 10:00 and 18:00 (FOLLOWUP_CRON).",
        "Each person with open tasks gets a message",
        "with buttons: Done · In progress · Blocked.",
        "",
        "Skipped while the last question is still",
        "unanswered, so nobody is asked twice.",
        "Replies feed the same pipeline as Part 2.",
        "",
        "/pause 3 silences reminders for 3 hours.",
    ], logos=("python",), color="indigo", size=12.5)
    d.card(colx[1], cy, cw, ch, "Silence ladder", [
        "Checks every 60 s (15 s in demo mode).",
        "A question nobody answered, N = 2 h:",
    ], logos=("python",), color="amber", size=12.5)
    d.card(colx[2], cy, cw, ch, "Blocker ladder", [
        "A blocker nobody has cleared, E = 3 h:",
    ], logos=("python",), color="amber", size=12.5)
    d.card(colx[3], cy, cw, ch, "Daily digest + risk", [
        "Cron 21:00 (DIGEST_CRON), once per day.",
        "Digest: done, in progress, blocked, at risk.",
        "Posted to the team group chat and the lead.",
        "",
        "Risk report: critical path, overdue and",
        "stalled tasks. Both also on demand with",
        "/digest and /risk, or from the dashboard.",
        "",
        "export.md = the living task document.",
    ], logos=("telegram",), color="indigo", size=12.5)

    def ladder(x, steps_, color):
        stroke = PAL[color][0]
        top = cy + 108 if color == "amber" else cy + 80
        d.arrow([(x + 38, top - 6), (x + 38, top + 3 * 62 - 22)], stroke, width=2.4)
        for i, (when, what, sub) in enumerate(steps_):
            y = top + i * 62
            d.badge(x + 38, y + 14, when, stroke, r=15)
            d.text(x + 66, y + 14, what, size=13, weight=700, fill=INK, maxw=cw - 80)
            d.text(x + 66, y + 32, sub, size=12, fill=MUTED, maxw=cw - 80)

    ladder(colx[1], [("N", "NUDGE_1 to the person", "a gentle reminder"),
                     ("2N", "NUDGE_2 to the person", "warns that the lead will be told"),
                     ("3N", "ESCALATE_SILENCE to the lead", "question marked escalated, task “stale”")], "amber")
    ladder(colx[2], [("E", "BLOCKER_REMINDER", "to whoever can unblock it; external → lead"),
                     ("2E", "BLOCKER_ESCALATED to the lead", "one reminder per person, deduped"),
                     ("✓", "Blocker resolved", "dependents are told they are ready")], "amber")

    # shared outbox bar
    OY = cy + ch + 22
    d.rect(30, OY, 1550, 56, "#E6F4FC", PAL["blue"][0], 1.6, rx=12)
    d.logo("telegram", 48, OY + 13, 30)
    d.text(90, OY + 24, "Everything above is queued in the outbox, sent by the outbox worker, and shown in the dashboard feed.",
           size=13.5, weight=700, fill=PAL["blue"][0])
    d.text(90, OY + 44, "Nudges and alerts respect the quiet window and people who paused; replies to something a person just said never wait.",
           size=12.5, fill=INK)

    # ---- C: lead overrides --------------------------------------------------------------
    CY = OY + 56 + 30
    band(CY, "C  ·  Anytime: the lead steers from the dashboard", "every action is an audit event with actor = lead", "sky")
    cards = [
        ("Override a task", ("react",), [
            "Change status, owner or deadline with a",
            "reason (version-checked). Logged as actor",
            "= lead; the owner gets a Telegram notice.",
        ]),
        ("Resolve or nudge", ("react",), [
            "Mark a blocker resolved, or send a follow-",
            "up to the owner now. Revert a status",
            "change: the old value comes back.",
        ]),
        ("Edit the graph", ("react",), [
            "Add, re-type or remove a dependency (a",
            "cycle is refused). Readiness and critical",
            "path are recomputed on the spot.",
        ]),
        ("Reports and export", ("react",), [
            "Generate a digest or risk report and",
            "post it to Telegram; download",
            "export.md; read the full timeline.",
        ]),
    ]
    for i, (t, lg, ls) in enumerate(cards):
        d.card(colx[i], CY + 52, cw, 124, t, ls, logos=lg, color="sky", size=12.5)

    # ---- D: data model ------------------------------------------------------------------
    DY = CY + 52 + 124 + 30
    band(DY, "D  ·  Where the data lives", "SQLite holds the project; PostgreSQL holds only logins", "data")
    groups = [
        ("People and documents", "sqlite", "data", ["projects", "participants", "source_documents"]),
        ("The plan", "sqlite", "data", ["plan_drafts", "milestones", "tasks", "dependencies"]),
        ("Conversation", "sqlite", "data", ["messages", "pending_questions", "outbox"]),
        ("Truth and audit", "sqlite", "data", ["task_events", "blockers", "reports", "llm_calls"]),
        ("Accounts (separate DB)", "postgresql", "teal", ["users"]),
    ]
    gw, ggap = 296, 17.5
    for i, (title, lg, color, tables) in enumerate(groups):
        gx = 30 + i * (gw + ggap)
        gy = DY + 52
        d.rect(gx, gy, gw, 170, "#FFFFFF", PAL[color][0], 1.8, rx=12)
        d.logo(lg, gx + 12, gy + 8, 26)
        d.text(gx + 46, gy + 27, title, size=14.5, weight=700, fill=PAL[color][0], maxw=gw - 56)
        cxp, cyp = gx + 12, gy + 48
        for t in tables:
            w = d.chip(cxp, cyp, t, color=color, size=12, mono=True)
            if cxp + w > gx + gw - 8:
                pass
            cxp += w + 8
            if cxp > gx + gw - 110:
                cxp, cyp = gx + 12, cyp + 36
        if title == "Truth and audit":
            d.text(gx + 12, gy + 130, "task_events is append-only: every", size=11.5, fill=MUTED)
            d.text(gx + 12, gy + 146, "change keeps its reason and source.", size=11.5, fill=MUTED)
        if title == "The plan":
            d.text(gx + 12, gy + 130, "tasks.version = optimistic locking", size=11.5, fill=MUTED)
        if title == "Conversation":
            d.text(gx + 12, gy + 130, "outbox: queued → sent / failed", size=11.5, fill=MUTED)
        if title == "People and documents":
            d.text(gx + 12, gy + 130, "originals are never edited", size=11.5, fill=MUTED)
        if title.startswith("Accounts"):
            d.text(gx + 12, gy + 98, "email, password hash, reset code", size=11.5, fill=MUTED)
            d.text(gx + 12, gy + 130, "JWT carries user_id; projects", size=11.5, fill=MUTED)
            d.text(gx + 12, gy + 146, "store it as owner_user_id.", size=11.5, fill=MUTED)
    return d


if __name__ == "__main__":
    for name, fn in (("1-system-architecture", part1), ("2-message-flow", part2), ("3-lifecycle-and-data", part3)):
        doc = fn()
        doc.save(OUT / f"{name}.svg")
