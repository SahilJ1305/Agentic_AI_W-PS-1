"""
app/core/risk.py — deterministic deadline-risk rules (spec W11, G3.9).

No LLM. A task is at risk when any of these hold:
  - blocked longer than RISK_BLOCKED_MIN
  - ETA is after the deadline, or the deadline has passed
  - the owner of a critical-path task has gone silent
  - it is still waiting on an upstream task but due within 6 hours
  - it was marked done without verification within 6 hours of the final deadline
  - an open dependency conflict (done while an upstream task is not)

`assess` is a pure function over a ProjectView, so reports, the dashboard and
tests all see the same answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.config import settings
from app.core.timeutil import human_duration, human_rel, parse_ts

RULES_LINE = (
    "Rules applied: blocked > {blocked} min · ETA after deadline · overdue · silent owner on "
    "critical path · waiting but due soon · unverified completion < 6 h before final deadline · "
    "open dependency conflict"
)
DUE_SOON = timedelta(hours=6)


@dataclass
class Risk:
    task_key: str
    task_title: str
    owner_name: str | None
    level: str                       # "high" | "medium"
    reasons: list[str] = field(default_factory=list)
    action: str = ""
    score: int = 0

    @property
    def why(self) -> str:
        return "; ".join(self.reasons)

    def as_dict(self) -> dict:
        return {
            "task_key": self.task_key,
            "task_title": self.task_title,
            "owner_name": self.owner_name,
            "level": self.level,
            "why": self.why,
            "action": self.action,
        }


def rules_line() -> str:
    return RULES_LINE.format(blocked=int(settings.effective_risk_blocked_min))


def final_deadline(view) -> datetime | None:
    """The project deadline, else the latest task deadline."""
    project_deadline = parse_ts((view.project or {}).get("deadline"))
    if project_deadline:
        return project_deadline
    deadlines = [d for d in (parse_ts(t.get("deadline")) for t in view.tasks) if d]
    return max(deadlines) if deadlines else None


def assess(view, now: datetime) -> list[Risk]:
    """Return risks sorted high first, then by deadline."""
    risks: list[Risk] = []
    final = final_deadline(view)
    silent_after = timedelta(minutes=settings.effective_nudge_after_min * 3)

    for task in view.tasks:
        key = task["key"]
        status = task["status"]
        deadline = parse_ts(task.get("deadline"))
        owner = task.get("owner_name")
        reasons: list[str] = []
        actions: list[str] = []
        score = 0

        if status == "complete":
            unverified = task.get("requires_evidence") and not task.get("verified")
            if unverified and final and timedelta(0) <= final - now <= DUE_SOON:
                reasons.append(f"Marked done without verification, final deadline {human_rel(final, now)}")
                actions.append(f"Ask {owner or 'the owner'} for a commit or PR link")
                score += 1
            if key in view.conflicts:
                reasons.append(f"Reported done while {', '.join(view.waiting_on.get(key) or ['an upstream task'])} is not finished")
                actions.append("Verify end-to-end before relying on it")
                score += 1
        else:
            for blocker in view.open_blockers.get(task["id"], []):
                raised = parse_ts(blocker.get("raised_at"))
                if raised and now - raised > timedelta(minutes=settings.effective_risk_blocked_min):
                    reasons.append(f"Blocked {human_duration(now - raised)} on {blocker['description']}")
                    linked = view.owner_of_task(blocker.get("linked_task_id"))
                    actions.append(
                        f"Ask {linked} for an ETA or find a workaround" if linked
                        else "Find a workaround or escalate the blocker"
                    )
                    score += 2
                    break

            if deadline and deadline < now:
                reasons.append(f"Overdue by {human_duration(now - deadline)}")
                actions.append(f"Check scope with {owner or 'the owner'} or reassign")
                score += 2
            else:
                eta = parse_ts(task.get("eta"))
                if eta and deadline and eta > deadline:
                    reasons.append(f"ETA is {human_duration(eta - deadline)} after the deadline")
                    actions.append("Cut scope or add help")
                    score += 1
                if deadline and task.get("readiness") == "waiting" and deadline - now <= DUE_SOON:
                    upstream = ", ".join(view.waiting_on.get(key) or []) or "an upstream task"
                    reasons.append(f"Due {human_rel(deadline, now)} but still waiting on {upstream}")
                    actions.append(f"Chase {upstream}")
                    score += 1

            followup = parse_ts(task.get("last_followup_at"))
            reply = parse_ts(task.get("last_reply_at"))
            if followup and (reply is None or reply < followup) and now - followup > silent_after:
                reasons.append(f"{owner or 'Owner'} has not replied for {human_duration(now - followup)}")
                actions.append(f"Ping {owner or 'the owner'} directly or reassign")
                score += 2 if task.get("on_critical_path") else 1

            if key in view.conflicts:
                reasons.append("Dependency conflict is waiting for an answer")
                actions.append("Verify end-to-end")
                score += 1

        if score and task.get("on_critical_path"):
            reasons.append("On the critical path")
            score += 1
        if not score:
            continue
        risks.append(Risk(
            task_key=key,
            task_title=task["title"],
            owner_name=owner,
            level="high" if score >= 3 else "medium",
            reasons=reasons,
            action=actions[0] if actions else "Check in with the owner",
            score=score,
        ))

    far = datetime.max.replace(tzinfo=now.tzinfo)
    deadlines = {t["key"]: parse_ts(t.get("deadline")) or far for t in view.tasks}
    risks.sort(key=lambda r: (r.level != "high", -r.score, deadlines[r.task_key]))
    return risks
