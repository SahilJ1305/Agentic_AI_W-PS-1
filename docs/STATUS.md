# Project status

Measured against the goals in the spec (§2). "Tested" means an automated test covers it; the end-to-end
tests use a pretend Telegram and a scripted model, so they prove the wiring and the rules, not the AI's
reading of real messages. Update this file as things change.

## Done

| Goal | State |
|---|---|
| G1.1 Seed from a spec (with or without a task doc), originals stored unchanged | Done, tested. Planner run on a real spec with the Azure model. |
| G1.2 Onboard on Telegram via invite link | Done, tested; live on the real bot |
| G1.3 Follow-ups (button, scheduler) | Done, tested. Repeats are skipped while a check-in is unanswered |
| G1.4 Interpret replies | Done. Real model spot-checked; one-word replies skip the model |
| G1.5 Audit trail with reason and source message | Done, tested |
| G1.6 Live board (< 2 s) | Done: 35 ms measured on a real server |
| G1.7 The Kabir loop | Done, tested end to end |
| G2.1-G2.9 Clarify, disambiguate, multi-task, undo, peer claims, Hinglish, override, LLM fallback, bursts | Done, tested (Hinglish and multi-task rely on the model) |
| G3.1 Dependency graph with evidence, review before commit | Done; rejected edges are honoured |
| G3.2-G3.5 Propagation, next task, blocker routing and follow-through | Done, tested |
| G3.6 "Done" verification | Done, plus the **Git checker** (below) |
| G3.7 Escalation ladder | Done, tested; one reminder per person |
| G3.8 Daily digest, G3.9 risk and critical path, G3.10 `export.md` | Done, tested |
| G3.11 Handoff with suggested owner | Done, tested |

**Git checker** (`app/tools/git_checker.py`): when someone claims a task is done, it looks for a commit or PR
by *their* GitHub account that matches the task (explicit link or search since the task was created).
Verified work is marked verified with the commit as evidence; someone else's commit, or none, leaves the task
"complete (unverified)", asks for a link and tells the lead. Needs `GITHUB_REPO` and each person's GitHub
username. With no username on file the bot flags it (on joining and on "done"), takes the task as complete but
unverified, tells the lead once, and never guesses; once the username is added the person can `/recheck`. Commit authorship can be faked with a git email setting, so treat it as a strong hint, not proof.

**Invites**: if a person's Telegram username is saved, only that account can use their invite link, and
they can also join by opening the bot and tapping Start. Without a username the first account to open the
link joins and the lead is told who it was; "Unlink & new link" on the Team tab undoes a wrong join.
`DEMO_MODE=true` skips the username check.

Also built: dashboard (board, drawer, graph, activity feed with the rule behind each change, plan review,
reports, team), Telegram commands, `scripts/setup_bot.py`, Docker deployment, CI, privacy rules (personal
commands only in a private chat, `/status` only for members).

## Remaining

**Needs a person**
- Deploy to a server and run exactly one bot instance (compose file is ready; nothing is deployed yet).
- Set `DEMO_MODE=false` on the deployed instance.
- Look at the dashboard in a browser and tune the UX: it builds and its API is tested, but nobody has reviewed it visually.
**Not built**
- Stretch goals: reading the group chat (S1), meeting slots (S2), Slack (S3), voice notes (S4), re-plan diff (S5).
- Interpreter eval set and model comparison (spec §17.2): `evals/` is empty, so the AI's accuracy on real
  messages, especially Hinglish, has not been measured.
- Edited messages, photos, files and voice from members are ignored.
- One Telegram account can be in only one project at a time.
- Project time zone is a single global setting; deadline wording assumes it.
- Digest summary line is rule-based (the spec allows an AI sentence).

**Quality and operations**
- Replies take about 3-8 s when the model is involved (the AI call is the floor); one-word replies are instant.
- `npm run lint` is broken by the existing `eslint.config.js`; the dashboard bundle is ~520 kB and not split.
- No UI tests, metrics, alerts, rate limiting or automated database backups.
- Database upgrades use a small list of `ALTER TABLE`s, not a migration tool.
- The shared demo project can be edited by any logged-in user.
