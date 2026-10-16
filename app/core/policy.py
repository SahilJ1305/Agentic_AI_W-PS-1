"""
app/core/policy.py — Policy Engine.

Takes a Coordinator Interpretation and a sender, applies rules R1–R16 in order,
and returns a PolicyDecision describing what should be written to the DB and
what messages should be queued.

No LLM calls here. No DB writes here.
The caller (router) is responsible for actually executing the decision.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite

from app.agents.schemas import Interpretation, TaskUpdate
from app.config import settings
from app.db import repo
from app.core.notifications import NotificationBatch
from app.tools.git_checker import GitVerification

log = logging.getLogger(__name__)


@dataclass
class ApprovedUpdate:
    """One approved status change or note, ready to write to the DB."""
    task_id: int
    task_key: str
    new_status: str | None
    old_status: str
    progress_note: str | None = None
    eta: str | None = None
    completion_evidence: str | None = None
    verified: bool | None = None          # None = leave tasks.verified unchanged
    blocker_description: str | None = None
    blocker_kind: str | None = None
    blocker_linked_task_id: int | None = None
    blocker_linked_participant_id: int | None = None
    blocker_resolved: bool = False
    flags_to_add: list[str] = field(default_factory=list)
    flags_to_remove: list[str] = field(default_factory=list)
    reason: str = ""
    rule_fired: str = ""
    confidence: float = 1.0


@dataclass
class PolicyDecision:
    approved: list[ApprovedUpdate] = field(default_factory=list)
    notifications: NotificationBatch = field(default_factory=NotificationBatch)
    clarifications: list[dict] = field(default_factory=list)  # pending questions to create
    rule_log: list[str] = field(default_factory=list)         # for the "why" panel
    revert: bool = False


async def apply(
    interpretation: Interpretation,
    sender: dict,          # participant row
    project_id: int,
    source_message_id: int,
    db: aiosqlite.Connection,
    now: str,
    verifications: dict[str, GitVerification] | None = None,
    confirmed: frozenset[str] = frozenset(),
) -> PolicyDecision:
    """
    Run rules R1–R16 in order against the Interpretation.
    Returns a PolicyDecision. Does NOT write to the DB.

    `verifications` holds Git claim checker results keyed by task key
    (app/tools/git_checker.verify_updates); rules R7a/R7b use them.

    `confirmed` names rules the owner has just answered ("R6" = yes it works end to end,
    "R8" = yes reopen), so the engine does not ask the same question again.
    """
    decision = PolicyDecision()

    # Load sender's tasks (for validation)
    sender_tasks_list = await repo.list_tasks_for_owner(db, sender["id"])
    sender_task_map = {t["key"]: t for t in sender_tasks_list}

    # Load open pending question for this sender
    open_pq = await repo.get_open_question(db, sender["id"])

    # Off-topic / question intents: no task updates, polite reply
    if interpretation.intent in ("off_topic", "question"):
        decision.rule_log.append("R0: intent=off_topic/question → OFF_TOPIC reply")
        decision.notifications.add(
            participant_id=sender["id"],
            template_key="OFF_TOPIC",
            context={"name": sender["name"]},
        )
        return decision

    # Handoff request (G3.11): tell the lead, with a suggested new owner
    if interpretation.intent == "handoff_request":
        decision.rule_log.append("R13: handoff_request → notify lead")
        lead = await repo.get_lead(db, project_id)
        open_mine = [t for t in sender_tasks_list if t["status"] != "complete"]
        named = next((sender_task_map[u.task_key] for u in interpretation.updates
                      if u.task_key in sender_task_map), None)
        handoff_task = named or (open_mine[0] if open_mine else None)
        if lead and lead.get("telegram_chat_id") and lead["id"] != sender["id"]:
            from app.core.handoff import suggest_owner

            pick = await suggest_owner(db, project_id, handoff_task, sender["id"]) if handoff_task else None
            decision.rule_log.append(
                f"R13: suggested {pick['name']} (skill matches {pick['skill_hits']}, {pick['open_count']} open)"
                if pick else "R13: nobody to suggest"
            )
            decision.notifications.add(
                participant_id=lead["id"],
                template_key="HANDOFF_TO_LEAD",
                context={
                    "name": sender["name"],
                    "task": handoff_task or {},
                    "reason": interpretation.raw_message,
                    "suggested_owner": pick["name"] if pick else "nobody free",
                    "skills": pick["skills"] if pick else "",
                    "open_count": pick["open_count"] if pick else "",
                },
            )
        return decision

    # Correction intent — revert the sender's latest status change. No new status is applied.
    if interpretation.intent == "correction":
        decision.rule_log.append("correction: revert the sender's latest status change")
        decision.revert = True
        return decision

    # If the LLM said needs_clarification from the start
    if interpretation.needs_clarification and not interpretation.updates:
        decision.rule_log.append("R15: LLM requested clarification")
        _add_clarify_task(decision, sender, sender_tasks_list, source_message_id)
        return decision

    for update in interpretation.updates:
        await _apply_update(
            update=update,
            sender=sender,
            sender_task_map=sender_task_map,
            open_pq=open_pq,
            project_id=project_id,
            source_message_id=source_message_id,
            db=db,
            now=now,
            decision=decision,
            verifications=verifications or {},
            confirmed=confirmed,
        )

    # If nothing was approved and nothing was clarified, send NOT_UNDERSTOOD
    if not decision.approved and not decision.clarifications:
        decision.rule_log.append("R15: no approved updates → NOT_UNDERSTOOD")
        if sender_tasks_list:
            decision.notifications.add(
                participant_id=sender["id"],
                template_key="NOT_UNDERSTOOD",
                context={"task_title": sender_tasks_list[0]["title"]},
                question_kind="clarify_status",
                question_task_id=sender_tasks_list[0]["id"],
            )

    return decision


async def _apply_update(
    *,
    update: TaskUpdate,
    sender: dict,
    sender_task_map: dict,
    open_pq: dict | None,
    project_id: int,
    source_message_id: int,
    db: aiosqlite.Connection,
    now: str,
    decision: PolicyDecision,
    verifications: dict[str, GitVerification],
    confirmed: frozenset[str] = frozenset(),
) -> None:
    """Apply rules R1–R16 to a single TaskUpdate."""

    # R14: open pending question — interpret as answer first
    if open_pq and open_pq.get("task_id"):
        pq_task = await repo.get_task(db, open_pq["task_id"])
        if pq_task and update.task_key in (pq_task["key"], ""):
            decision.rule_log.append(f"R14: answering pending question {open_pq['kind']} for {pq_task['key']}")
            update.task_key = pq_task["key"]

    # R1 / R5: unknown key, or a claim about someone else's task
    task = sender_task_map.get(update.task_key)
    if not task:
        other = None
        if update.task_key:
            other = await repo.get_task_by_key(db, project_id, update.task_key)
        if other and other.get("owner_id") and other["owner_id"] != sender["id"]:
            decision.rule_log.append(
                f"R5: {sender['name']} claimed {other['key']} owned by someone else → PEER_CLAIM_CONFIRM"
            )
            decision.notifications.add(
                participant_id=other["owner_id"],
                template_key="PEER_CLAIM_CONFIRM",
                context={
                    "reporter": sender["name"],
                    "task_title": other["title"],
                    "claimed_status": update.status or "updated",
                    "task": other,
                    "_claimed_status": update.status or "complete",
                },
                question_kind="confirm_peer_claim",
                question_task_id=other["id"],
            )
            decision.clarifications.append({"kind": "confirm_peer_claim", "task_id": other["id"]})
            return
        decision.rule_log.append(f"R1: task_key={update.task_key} not in sender's tasks → CLARIFY_TASK")
        _add_clarify_task(decision, sender, list(sender_task_map.values()), source_message_id)
        return

    # R2: Low task-match confidence
    if update.task_match_confidence < settings.clarify_threshold:
        decision.rule_log.append(f"R2: task_match_confidence={update.task_match_confidence:.2f} < {settings.clarify_threshold} → CLARIFY_TASK")
        _add_clarify_task(decision, sender, list(sender_task_map.values()), source_message_id)
        return

    # R3: Low status confidence
    if update.status and update.status_confidence < settings.clarify_threshold:
        decision.rule_log.append(f"R3: status_confidence={update.status_confidence:.2f} → CLARIFY_STATUS")
        decision.notifications.add(
            participant_id=sender["id"],
            template_key="CLARIFY_STATUS",
            context={"task_title": task["title"]},
            question_kind="clarify_status",
            question_task_id=task["id"],
        )
        decision.clarifications.append({"kind": "clarify_status", "task_id": task["id"]})
        return

    # R4: Blocked + complete in same update → force blocked (Kabir rule)
    if update.status == "complete" and update.blocker:
        decision.rule_log.append(f"R4: complete+blocker → forced to blocked (Kabir rule)")
        update.status = "blocked"

    # R6: complete while a hard upstream is incomplete → ask before completing
    carried_flags: list[str] = []
    if update.status == "complete":
        conflict_task = await _check_dependency_conflict(task, db)
        if conflict_task and "R6" in confirmed:
            decision.rule_log.append(
                f"R6: owner confirmed it works although {conflict_task['key']} is {conflict_task['status']} → complete, needs_verification"
            )
            carried_flags += ["needs_verification", "dependency_conflict"]
        elif conflict_task:
            decision.rule_log.append(f"R6: complete while {conflict_task['key']} incomplete → DEPENDENCY_CONFLICT")
            decision.notifications.add(
                participant_id=sender["id"],
                template_key="DEPENDENCY_CONFLICT",
                context={
                    "task_title": task["title"],
                    "upstream_title": conflict_task["title"],
                    "upstream_status": conflict_task["status"],
                },
                question_kind="dependency_conflict",
                question_task_id=task["id"],
            )
            decision.clarifications.append({"kind": "dependency_conflict", "task_id": task["id"]})
            return

    # R7a / R7b: the Git claim checker looked for the sender's commit or PR
    check = verifications.get(task["key"])
    claims_done = update.status == "complete" or (
        update.status is None and task["status"] == "complete"
    )
    if check and claims_done:
        if await _apply_git_check(check, update, task, sender, decision, db):
            return

    # R7: complete on requires_evidence task without evidence
    if update.status == "complete" and task.get("requires_evidence") and not update.completion_evidence:
        decision.rule_log.append(f"R7: complete on evidence-required task without evidence → VERIFY_COMPLETION")
        decision.notifications.add(
            participant_id=sender["id"],
            template_key="VERIFY_COMPLETION",
            context={"task_title": task["title"]},
            question_kind="verify_completion",
            question_task_id=task["id"],
        )
        decision.approved.append(ApprovedUpdate(
            task_id=task["id"],
            task_key=task["key"],
            new_status="complete",
            old_status=task["status"],
            flags_to_add=list(dict.fromkeys(["needs_verification", *carried_flags])),
            reason="Completed — evidence required but not provided",
            rule_fired="R7",
            confidence=update.status_confidence,
        ))
        return

    # R8: Moving away from complete without correction intent
    if task["status"] == "complete" and update.status and update.status != "complete" and "R8" not in confirmed:
        if interpretation_intent_is_not_correction := True:  # caller already checked intent
            decision.rule_log.append("R8: moving away from complete → ask CONFIRM_REOPEN")
            decision.notifications.add(
                participant_id=sender["id"],
                template_key="CONFIRM_REOPEN",
                context={"task_title": task["title"]},
                question_kind="confirm_reopen",
                question_task_id=task["id"],
            )
            decision.clarifications.append({"kind": "confirm_reopen", "task_id": task["id"]})
            return

    # R9: Same status with a note/ETA — append note, no status event
    if update.status == task["status"] and (update.progress_note or update.eta):
        decision.rule_log.append(f"R9: same status={task['status']} with note/ETA → note only")
        decision.approved.append(ApprovedUpdate(
            task_id=task["id"],
            task_key=task["key"],
            new_status=None,  # no status change
            old_status=task["status"],
            progress_note=update.progress_note,
            eta=update.eta,
            reason="Progress note added",
            rule_fired="R9",
            confidence=update.status_confidence,
        ))
        return

    # R10: blocked with empty blocker description
    if update.status == "blocked" and (not update.blocker or not update.blocker.description):
        decision.rule_log.append("R10: blocked with no blocker → ASK_BLOCKER")
        decision.notifications.add(
            participant_id=sender["id"],
            template_key="ASK_BLOCKER",
            context={"task_title": task["title"]},
            question_kind="ask_blocker",
            question_task_id=task["id"],
        )
        decision.clarifications.append({"kind": "ask_blocker", "task_id": task["id"]})
        return

    # R11: Blocker with suspected_task_key and confidence ≥ threshold → runtime edge
    blocker_linked_task_id: int | None = None
    blocker_linked_participant_id: int | None = None
    if update.blocker and update.blocker.suspected_task_key:
        if update.blocker.match_confidence >= settings.runtime_edge_min:
            linked = await repo.get_task_by_key(db, task["project_id"], update.blocker.suspected_task_key)
            if linked:
                blocker_linked_task_id = linked["id"]
                decision.rule_log.append(
                    f"R11: blocker linked to {update.blocker.suspected_task_key} "
                    f"(confidence {update.blocker.match_confidence:.2f}) → runtime edge"
                )
        else:
            decision.rule_log.append(
                f"R11: blocker match confidence {update.blocker.match_confidence:.2f} < "
                f"{settings.runtime_edge_min} → will ask confirmation"
            )

    if update.blocker and update.blocker.suspected_person:
        from app.db.repo import list_participants
        participants = await list_participants(db, task["project_id"])
        for p in participants:
            if p["name"].lower() == update.blocker.suspected_person.lower():
                blocker_linked_participant_id = p["id"]
                break

    # R12: ETA past deadline → flag at_risk
    flags_to_add: list[str] = list(carried_flags)
    if update.eta and task.get("deadline"):
        try:
            eta_dt = datetime.fromisoformat(update.eta)
            dl_dt = datetime.fromisoformat(task["deadline"])
            if eta_dt > dl_dt:
                flags_to_add.append("at_risk")
                decision.rule_log.append("R12: ETA past deadline → flag at_risk")
        except Exception:
            pass

    # R16: quiet window — checked by outbox worker, not here

    # ── All rules passed — approve the update ────────────────────────────────
    decision.rule_log.append(
        f"Approved: {task['key']} {task['status']} → {update.status or 'note'}"
    )
    decision.approved.append(ApprovedUpdate(
        task_id=task["id"],
        task_key=task["key"],
        new_status=update.status,
        old_status=task["status"],
        progress_note=update.progress_note,
        eta=update.eta,
        completion_evidence=update.completion_evidence,
        blocker_description=update.blocker.description if update.blocker else None,
        blocker_kind=update.blocker.kind if update.blocker else None,
        blocker_linked_task_id=blocker_linked_task_id,
        blocker_linked_participant_id=blocker_linked_participant_id,
        blocker_resolved=update.blocker_resolved,
        flags_to_add=flags_to_add,
        reason=update.evidence or interpretation_reason(update),
        rule_fired=", ".join(decision.rule_log[-3:]),
        confidence=update.status_confidence,
    ))


# ── helpers ────────────────────────────────────────────────────────────────────

async def _apply_git_check(
    check: GitVerification,
    update: TaskUpdate,
    task: dict,
    sender: dict,
    decision: PolicyDecision,
    db: aiosqlite.Connection,
) -> bool:
    """
    Decide a completion claim from a Git checker result. Returns True if it did.

    R7a  verified                          → complete, verified, evidence = commit/PR URL
    R7b  author_mismatch (any task), or
         weak_match/not_found on a task
         that requires evidence            → complete but unverified, ask for a link;
                                             a mismatch also tells the lead
    Anything else (skipped, error, or a miss on a task that doesn't need evidence)
    falls through to R7 and the normal path, so a GitHub outage never blocks a reply.
    """
    if check.is_verified:
        decision.rule_log.append(f"R7a: git check verified {task['key']} → {check.evidence_url}")
        decision.approved.append(ApprovedUpdate(
            task_id=task["id"],
            task_key=task["key"],
            new_status="complete",
            old_status=task["status"],
            progress_note=update.progress_note,
            completion_evidence=check.evidence_url or update.completion_evidence,
            verified=True,
            flags_to_remove=["needs_verification"],
            reason=f"Verified on GitHub: {check.reason}",
            rule_fired="R7a",
            confidence=update.status_confidence,
        ))
        return True

    disputed = check.status == "author_mismatch"
    if not (disputed or (check.checked and task.get("requires_evidence"))):
        decision.rule_log.append(
            f"git check {check.status} for {task['key']} ({check.reason}) → not required, continuing"
        )
        return False

    decision.rule_log.append(f"R7b: git check {check.status} for {task['key']} → needs_verification")
    decision.notifications.add(
        participant_id=sender["id"],
        template_key="GIT_UNVERIFIED",
        context={"task": task, "reason": check.reason},
        question_kind="verify_completion",
        question_task_id=task["id"],
    )
    decision.clarifications.append({"kind": "verify_completion", "task_id": task["id"]})
    if disputed:
        lead = await repo.get_lead(db, task["project_id"])
        if lead and lead["id"] != sender["id"]:
            decision.notifications.add(
                participant_id=lead["id"],
                template_key="GIT_CLAIM_MISMATCH",
                context={"task": task, "reporter": sender["name"], "reason": check.reason},
                dedupe_key=f"git_mismatch:{task['id']}:{check.evidence_url or check.status}",
            )
    decision.approved.append(ApprovedUpdate(
        task_id=task["id"],
        task_key=task["key"],
        new_status="complete",
        old_status=task["status"],
        progress_note=update.progress_note,
        completion_evidence=update.completion_evidence,
        verified=False,
        flags_to_add=["needs_verification"],
        reason=f"Completed, not confirmed on GitHub: {check.reason}",
        rule_fired="R7b",
        confidence=update.status_confidence,
    ))
    return True


def _add_clarify_task(
    decision: PolicyDecision,
    sender: dict,
    tasks: list[dict],
    source_message_id: int,
) -> None:
    if not tasks:
        return
    decision.notifications.add(
        participant_id=sender["id"],
        template_key="CLARIFY_TASK",
        context={"tasks": tasks},
        question_kind="clarify_task",
        question_task_id=None,
    )
    decision.clarifications.append({"kind": "clarify_task"})


async def _check_dependency_conflict(task: dict, db: aiosqlite.Connection) -> dict | None:
    """Return the first incomplete hard upstream, or None."""
    upstreams = await repo.list_dependencies_downstream(db, task["id"], state="active")
    for dep in upstreams:
        if dep["type"] != "hard":
            continue
        upstream = await repo.get_task(db, dep["upstream_task_id"])
        if upstream and upstream["status"] != "complete":
            return upstream
    return None


def interpretation_reason(update: TaskUpdate) -> str:
    if update.evidence:
        return update.evidence
    if update.status:
        return f"Reported {update.status}"
    return "Progress note"
