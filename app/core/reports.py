"""
app/core/reports.py — digest, risk report and the living task doc (spec §14.3-14.5).

Every report is built from DB state only (taskview), so it is identical however
it is requested: the scheduler, /digest on Telegram, or the dashboard. Text is
built twice from the same data: Markdown for the dashboard and stored in
`reports`, and escaped HTML for Telegram.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiosqlite

from app.api.sse import broadcaster
from app.config import settings
from app.core import risk as risk_rules
from app.core.taskview import ProjectView, load_view
from app.core.timeutil import human_duration, human_rel, parse_ts
from app.db import repo

log = logging.getLogger(__name__)

STATUS_LABEL = {"pending": "Pending", "in_progress": "In progress", "blocked": "Blocked", "complete": "Complete"}
LEVEL_ICON = {"high": "🔴", "medium": "🟠"}


def _local(now: datetime) -> datetime:
    try:
        return now.astimezone(ZoneInfo(settings.timezone))
    except Exception:
        return now


def _stamp(now: datetime) -> str:
    return _local(now).strftime("%d %b %Y, %H:%M")


def _label(task: dict, owner: bool = True) -> str:
    who = f" ({task['owner_name']})" if owner and task.get("owner_name") else ""
    return f"{task['key']} {task['title']}{who}"


def _clip(text: str | None, size: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= size else text[: size - 1] + "…"


def _cell(text) -> str:
    return str(text if text not in (None, "") else "—").replace("|", "/").replace("\n", " ")


# ═══════════════════════════════════════════════════════════════════════════
#  Digest
# ═══════════════════════════════════════════════════════════════════════════

async def _since(db: aiosqlite.Connection, project_id: int, now: datetime) -> datetime:
    last = await repo.get_latest_report(db, project_id, "digest")
    return parse_ts(last["created_at"]) if last else now - timedelta(hours=24)


def _summary_line(view: ProjectView) -> str:
    total = len(view.tasks)
    done = sum(t["status"] == "complete" for t in view.tasks)
    blocked = [t for t in view.tasks if t["status"] == "blocked"]
    parts = [f"{done} of {total} tasks are done"]
    if blocked:
        parts.append(f"{len(blocked)} blocked ({_clip(blocked[0].get('blocker') or blocked[0]['key'], 40)})")
    high = [r for r in view.risks if r.level == "high"]
    if high:
        parts.append(f"biggest risk: {high[0].task_key} — {_clip(high[0].reasons[0], 60)}")
    elif not blocked:
        parts.append("nothing is blocked")
    return "; ".join(parts) + "."


def _digest_sections(view: ProjectView, since: datetime, now: datetime) -> dict:
    done = [t for t in view.tasks if t["status"] == "complete"
            and (parse_ts(t.get("completed_at")) or now - timedelta(days=999)) >= since]
    open_tasks = [t for t in view.tasks if t["status"] != "complete"]
    upcoming = sorted(
        ((parse_ts(t.get("deadline")), t) for t in open_tasks if t.get("deadline")),
        key=lambda pair: pair[0] or now,
    )
    return {
        "done": done,
        "in_progress": [t for t in view.tasks if t["status"] == "in_progress"],
        "blocked": [t for t in view.tasks if t["status"] == "blocked"],
        "waiting": [t for t in open_tasks if t["waiting_on"] and t["status"] != "blocked"],
        "at_risk": view.risks,
        "next_deadline": upcoming[0] if upcoming else None,
        "complete": sum(t["status"] == "complete" for t in view.tasks),
        "total": len(view.tasks),
    }


def render_digest(view: ProjectView, since: datetime, now: datetime) -> tuple[str, str]:
    """Return (markdown, telegram_html)."""
    s = _digest_sections(view, since, now)
    name = view.project.get("name", "Project")

    def lines(items, fmt):
        return [fmt(i) for i in items] or ["none"]

    blocks = [
        ("Done since last update", lines(s["done"], lambda t: _label(t))),
        ("In progress", lines(s["in_progress"], lambda t: _label(t))),
        ("Blocked", lines(s["blocked"], lambda t: f"{_label(t)}: {t.get('blocker') or 'no reason given'}")),
        ("Waiting on others", lines(s["waiting"], lambda t: f"{_label(t)} ← {', '.join(t['waiting_on'])}")),
        ("At risk", lines(s["at_risk"], lambda r: f"{r.task_key} {r.task_title} — {r.why}")),
    ]
    nd = s["next_deadline"]
    footer = f"{s['complete']}/{s['total']} complete"
    if nd:
        footer += f" · next deadline: {nd[1]['key']} {human_rel(nd[0], now)}"
    summary = _summary_line(view)

    health_label = "🔴 Blocked / Attention Required" if s["blocked"] else ("🟠 At Risk / Monitor" if s["at_risk"] else "🟢 Healthy / On Track")
    pct = round((s["complete"] / s["total"]) * 100) if s["total"] else 0

    md = [
        f"# {name}: update",
        f"_{_stamp(now)}_ · Operational Status & Executive Digest",
        "",
        f"> **Executive Summary:** {summary}",
        f"> **Health Status:** {health_label} · {s['complete']}/{s['total']} complete ({pct}%)",
        "",
        "### 📊 Key Performance Indicators",
        "| Metric | Status | Details |",
        "|---|---|---|",
        f"| Progress | {pct}% | {s['complete']} of {s['total']} tasks complete |",
        f"| Active Work | {len(s['in_progress'])} in progress | Tasks actively being developed |",
        f"| Blockers | {len(s['blocked'])} blocked | Roadblocks requiring unblocking |",
        f"| At-Risk Items | {len(s['at_risk'])} flagged | Potential timeline or dependency slips |",
        f"| Next Milestone | {_cell(nd[1]['key'] if nd else 'None')} | {_cell(human_rel(nd[0], now) if nd else 'No upcoming deadlines')} |",
        "",
        "### 📋 Operational Breakdown",
    ]
    for title, items in blocks:
        md.append(f"**{title}**")
        md.extend(f"- {i}" for i in items)
        md.append("")
    md += [
        "---",
        "### 💡 Next Steps & Summary",
        summary,
        "",
        footer,
    ]

    tg = [f"<b>{html.escape(name)}: update</b> ({_stamp(now)})"]
    for title, items in blocks:
        tg.append(f"\n<b>{title}</b>")
        tg.extend(f"• {html.escape(i)}" for i in items)
    tg += ["", html.escape(summary), html.escape(footer)]
    return "\n".join(md), "\n".join(tg)


# ═══════════════════════════════════════════════════════════════════════════
#  Lead summary (/update_now, /update_every)
# ═══════════════════════════════════════════════════════════════════════════

def every_label(hours: float) -> str:
    return f"{round(hours * 60)} min" if hours < 1 else f"{hours:g} h"


def summary_fingerprint(view: ProjectView) -> str:
    tasks = "|".join(f"{t['key']}:{t['status']}:{t.get('blocker') or ''}" for t in sorted(view.tasks, key=lambda t: t["key"]))
    risks = "|".join(sorted(f"{r.task_key}:{r.level}" for r in view.risks))
    return f"{tasks}#{risks}"


def render_lead_summary(view: ProjectView, since: datetime | None, now: datetime, every_h: float) -> str:
    """Short Telegram summary for the lead: progress bar, counts, then only what needs attention."""
    esc = html.escape
    tasks = view.tasks
    total = len(tasks) or 1
    count = {s: sum(t["status"] == s for t in tasks) for s in STATUS_LABEL}
    filled = round(10 * count["complete"] / total)
    out = [
        f"📊 <b>{esc(view.project.get('name') or 'Project')}</b> · {_local(now).strftime('%H:%M')}",
        f"{'▰' * filled}{'▱' * (10 - filled)}  <b>{count['complete']}/{len(tasks)}</b> done",
        f"🔄 {count['in_progress']} in progress · 🚫 {count['blocked']} blocked · ⏳ {count['pending']} to do",
    ]

    def section(title: str, items: list[str]) -> None:
        if items:
            out.extend(["", title, *items[:3]])
            if len(items) > 3:
                out.append(f"   +{len(items) - 3} more")

    def who(t: dict) -> str:
        return f" · {esc(t['owner_name'])}" if t.get("owner_name") else ""

    blocked = [t for t in tasks if t["status"] == "blocked"]
    section("🚫 <b>Blocked</b>", [
        f"• <b>{esc(t['key'])}</b> {esc(_clip(t['title'], 40))}{who(t)}\n   <i>{esc(_clip(t.get('blocker') or 'no reason given', 60))}</i>"
        for t in blocked
    ])
    blocked_keys = {t["key"] for t in blocked}
    section("⚠️ <b>At risk</b>", [
        f"• <b>{esc(r.task_key)}</b> {esc(_clip(r.task_title, 40))}{' · ' + esc(r.owner_name) if r.owner_name else ''}"
        f"\n   <i>{esc(_clip(r.why, 60))}</i>"
        for r in view.risks if r.task_key not in blocked_keys
    ])
    cutoff = since or now - timedelta(hours=24)
    done = [t for t in tasks if t["status"] == "complete" and (parse_ts(t.get("completed_at")) or cutoff) > cutoff]
    when = f"since {_local(since).strftime('%H:%M')}" if since else "in the last 24 h"
    section(f"✅ <b>Done {when}</b>", [
        f"• <b>{esc(t['key'])}</b> {esc(_clip(t['title'], 40))}{who(t)}" for t in done
    ])
    upcoming = sorted(
        (pair for pair in ((parse_ts(t.get("deadline")), t) for t in tasks if t["status"] != "complete") if pair[0]),
        key=lambda pair: pair[0],
    )
    if upcoming:
        when, t = upcoming[0]
        out += ["", f"⏰ <b>Next deadline:</b> {esc(t['key'])} {esc(_clip(t['title'], 40))} · {human_rel(when, now)}"]
    if not blocked and not view.risks:
        out += ["", "✨ Nothing blocked or at risk."]
    footer = f"Every {every_label(every_h)} · /update_now · /update_every off" if every_h else "/update_every 2h for regular updates"
    out += ["", f"<i>{footer}</i>"]
    return "\n".join(out)


async def lead_summary(db: aiosqlite.Connection, project_id: int, now: datetime, *, force: bool = False) -> str | None:
    """The lead's summary, or None when nothing changed since the last one (unless forced)."""
    saved = await repo.get_project_settings(db, project_id)
    view = await load_view(db, project_id, now)
    fingerprint = summary_fingerprint(view)
    stamp = now.isoformat()
    if not force and fingerprint == saved.get("lead_summary_fp"):
        await repo.update_project_settings(db, project_id, lead_summary_at=stamp)
        return None
    since = parse_ts(saved.get("lead_summary_sent_at"))
    every = float(saved.get("lead_summary_every_h", settings.lead_summary_every_h) or 0)
    await repo.update_project_settings(db, project_id, lead_summary_at=stamp, lead_summary_sent_at=stamp,
                                       lead_summary_fp=fingerprint)
    return render_lead_summary(view, since, now, every)


# ═══════════════════════════════════════════════════════════════════════════
#  Risk report
# ═══════════════════════════════════════════════════════════════════════════

def render_risk(view: ProjectView, now: datetime) -> tuple[str, str]:
    name = view.project.get("name", "Project")
    md = [f"# Risk report: {name} ({_stamp(now)})", ""]
    tg = [f"<b>Risk report: {html.escape(name)}</b> ({_stamp(now)})"]

    high_count = sum(1 for r in view.risks if r.level == "high")
    med_count = sum(1 for r in view.risks if r.level == "medium")

    if view.risks:
        md += [
            f"> **Risk Overview:** {len(view.risks)} tasks flagged ({high_count} high severity, {med_count} medium).",
            "> **Recommendation:** Prioritize high-risk items on the critical path to prevent delivery slips.",
            "",
            "### 🚨 Risk Assessment Matrix",
            "| Task | Owner | Risk | Why | Suggested action |",
            "|---|---|---|---|---|",
        ]
        for r in view.risks:
            md.append(
                f"| {_cell(r.task_key + ' ' + r.task_title)} | {_cell(r.owner_name)} | "
                f"{r.level.capitalize()} | {_cell(r.why)} | {_cell(r.action)} |"
            )
            tg.append(
                f"\n{LEVEL_ICON.get(r.level, '•')} <b>{html.escape(r.task_key)} {html.escape(r.task_title)}</b>"
                f" ({html.escape(r.owner_name or 'unassigned')})\n{html.escape(r.why)}\n→ {html.escape(r.action)}"
            )
        md += [
            "",
            "### 🛠️ Lead Action Items",
            "- Reach out to task owners on Telegram for blocked dependencies.",
            "- Reassign or split tasks that have unresolved external blockers.",
        ]
    else:
        md.append("> **Risk Overview:** All tasks are healthy with no active risks flagged.")
        md.append("")
        md.append("No tasks are at risk right now.")
        tg.append("\nNo tasks are at risk right now.")
    rules = risk_rules.rules_line()
    md += ["", "---", rules]
    tg += ["", html.escape(rules)]
    return "\n".join(md), "\n".join(tg)


# ═══════════════════════════════════════════════════════════════════════════
#  Living task doc (export.md)
# ═══════════════════════════════════════════════════════════════════════════

async def build_export_md(db: aiosqlite.Connection, project_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    view = await load_view(db, project_id, now)
    name = view.project.get("name", "Project")
    total = len(view.tasks)
    complete = sum(t["status"] == "complete" for t in view.tasks)
    blocked = sum(t["status"] == "blocked" for t in view.tasks)
    waiting = sum(1 for t in view.tasks if t["waiting_on"] and t["status"] != "complete")

    out = [
        f"# {name}: task status",
        f"Generated {_stamp(now)} · Progress {complete}/{total} complete · {blocked} blocked · {waiting} waiting",
    ]
    if view.critical_path:
        out.append("Critical path: " + " → ".join(view.critical_path))
    out += ["", "| Key | Task | Owner | Status | Waiting on | Blocker | ETA | Last update |",
            "|---|---|---|---|---|---|---|---|"]
    for t in view.tasks:
        status = STATUS_LABEL.get(t["status"], t["status"])
        if t["status"] == "complete" and t.get("verified"):
            status += " ✓ verified"
        elif t["status"] == "complete" and "needs_verification" in t["flags"]:
            status += " (unverified)"
        last = t.get("last_update")
        last_text = f"{_local(parse_ts(last['at'])).strftime('%H:%M')} “{_clip(last['text'], 60)}”" if last and last.get("text") else None
        out.append(
            f"| {t['key']} | {_cell(t['title'])} | {_cell(t.get('owner_name'))} | {status} | "
            f"{_cell(', '.join(t['waiting_on']))} | {_cell(t.get('blocker'))} | {_cell(t.get('eta'))} | {_cell(last_text)} |"
        )

    out += ["", "## Open blockers"]
    any_blocker = False
    for task_id, blockers in view.open_blockers.items():
        task = view.task_by_id(task_id)
        for b in blockers:
            any_blocker = True
            linked = view.task_by_id(b.get("linked_task_id"))
            link = f" · linked to {linked['key']}{' (' + linked['owner_name'] + ')' if linked and linked.get('owner_name') else ''}" if linked else ""
            raised = parse_ts(b.get("raised_at"))
            age = f" · open {human_duration(now - raised)}" if raised else ""
            out.append(f"- {task['key']} · {b['description']}{link}{age}")
    if not any_blocker:
        out.append("- none")

    cur = await db.execute(
        """SELECT e.*, t.key AS task_key FROM task_events e JOIN tasks t ON t.id = e.task_id
           WHERE t.project_id = ? ORDER BY e.created_at DESC, e.id DESC LIMIT 10""",
        (project_id,),
    )
    out += ["", "## Recent changes"]
    events = [dict(r) for r in await cur.fetchall()]
    for e in events:
        when = parse_ts(e["created_at"])
        stamp = _local(when).strftime("%H:%M") if when else "—"
        change = f"{e['old_value']} → {e['new_value']}" if e.get("old_value") else (e.get("new_value") or "")
        reason = f" ({_clip(e['reason'], 80)})" if e.get("reason") else ""
        out.append(f"- {stamp} {e['task_key']} {e['event_type'].replace('_', ' ')}: {change}{reason}")
    if not events:
        out.append("- none yet")
    return "\n".join(out) + "\n"


# ═══════════════════════════════════════════════════════════════════════════
#  Generate + post
# ═══════════════════════════════════════════════════════════════════════════

async def generate_report(
    db: aiosqlite.Connection,
    project_id: int,
    kind: str,
    *,
    post: bool = False,
    now: datetime | None = None,
    dedupe: str | None = None,
) -> dict:
    """Build, store and optionally post a digest or risk report."""
    if kind not in ("digest", "risk"):
        raise ValueError("kind must be 'digest' or 'risk'")
    now = now or datetime.now(timezone.utc)
    view = await load_view(db, project_id, now)
    if kind == "digest":
        md, tg = render_digest(view, await _since(db, project_id, now), now)
    else:
        md, tg = render_risk(view, now)

    report_id = await repo.save_report(db, project_id=project_id, kind=kind, content_md=md, now=now.isoformat())
    recipients = await _post(db, view, kind, tg, now, dedupe) if post else 0
    await broadcaster.publish("report.created", {"project_id": project_id, "kind": kind, "report_id": report_id})
    return {
        "id": report_id,
        "kind": kind,
        "content_md": md,
        "posted": recipients > 0,
        "recipients": recipients,
        "created_at": now.isoformat(),
        "telegram_html": tg,
    }


async def _post(db, view: ProjectView, kind: str, text: str, now: datetime, dedupe: str | None) -> int:
    """Queue the report for the team group chat and the lead's DM. Returns chats queued."""
    project_id = view.project["id"]
    group = view.project.get("group_chat_id") or settings.telegram_group_chat_id
    lead = await repo.get_lead(db, project_id)
    targets: list[tuple[int, int | None]] = []
    if group:
        targets.append((int(group), None))
    if lead and lead.get("telegram_chat_id") and lead["telegram_chat_id"] != group:
        targets.append((lead["telegram_chat_id"], lead["id"]))

    queued = 0
    for chat_id, participant_id in targets:
        outbox_id = await repo.enqueue_message(
            db,
            participant_id=participant_id,
            project_id=project_id,
            chat_id=chat_id,
            template_key="DIGEST" if kind == "digest" else "RISK_REPORT",
            text=text[:4000],
            dedupe_key=f"report:{kind}:{project_id}:{chat_id}:{dedupe}" if dedupe else None,
            now=now.isoformat(),
        )
        queued += outbox_id is not None
    if not targets:
        log.info("Report %s for project %s has nobody to post to (no group chat, lead not on Telegram)", kind, project_id)
    return queued
