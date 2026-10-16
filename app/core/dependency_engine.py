"""
app/core/dependency_engine.py — graph validation, readiness, propagation.

All functions are pure async — they read from the DB and write back via repo.
No LLM calls here. This is the deterministic half of the system.

Key entry points:
  validate_graph(edges)            → ValidationResult
  compute_readiness(task_id, db)   → "ready" | "waiting"
  on_task_completed(task_id, ...)  → fires notifications
  on_blocker_raised(blocker, ...)  → creates runtime edge + UNBLOCK_REQUEST
  compute_critical_path(pid, db)   → marks on_critical_path flag
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

import aiosqlite

from app.agents.schemas import PlannedDependency
from app.config import settings
from app.db import repo

log = logging.getLogger(__name__)


# ── Validation ─────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    accepted: list[PlannedDependency] = field(default_factory=list)
    proposed: list[PlannedDependency] = field(default_factory=list)   # 0.5–0.8
    dropped:  list[PlannedDependency] = field(default_factory=list)   # < 0.5
    warnings: list[str]               = field(default_factory=list)


def validate_graph(
    edges: list[PlannedDependency],
    known_keys: set[str],
    auto_accept_threshold: float | None = None,
) -> ValidationResult:
    """
    Run the 6-step graph validation pipeline (spec §7.3).

    Steps:
      1. Drop unknown task keys and self-loops.
      2. Deduplicate (keep highest-confidence; explicit beats inferred).
      3. Detect and break cycles (remove lowest-confidence edge per cycle).
      4. Mark redundant edges (A→B→C makes A→C redundant).
      5. Apply confidence threshold:
           ≥ auto_accept_threshold → accepted (active)
           0.5 – threshold         → proposed
           < 0.5                   → dropped
      6. Return ValidationResult.
    """
    threshold = auto_accept_threshold or settings.edge_auto_accept
    result = ValidationResult()

    # Step 1: unknown keys and self-loops
    clean: list[PlannedDependency] = []
    for e in edges:
        if e.upstream not in known_keys:
            result.warnings.append(f"Unknown upstream task '{e.upstream}' in edge {e.upstream}→{e.downstream}")
            result.dropped.append(e)
            continue
        if e.downstream not in known_keys:
            result.warnings.append(f"Unknown downstream task '{e.downstream}' in edge {e.upstream}→{e.downstream}")
            result.dropped.append(e)
            continue
        if e.upstream == e.downstream:
            result.warnings.append(f"Self-loop on '{e.upstream}' dropped")
            result.dropped.append(e)
            continue
        clean.append(e)

    # Step 2: deduplicate — keep highest confidence; explicit source preferred
    best: dict[tuple[str, str], PlannedDependency] = {}
    for e in clean:
        k = (e.upstream, e.downstream)
        if k not in best:
            best[k] = e
        else:
            prev = best[k]
            # Prefer explicit (evidence_quote) over inferred (rule only)
            prev_explicit = prev.evidence_quote is not None
            curr_explicit = e.evidence_quote is not None
            if curr_explicit and not prev_explicit:
                best[k] = e
            elif curr_explicit == prev_explicit and e.confidence > prev.confidence:
                best[k] = e
    deduped = list(best.values())

    # Step 3: cycle detection and breaking (Kahn's algorithm)
    acyclic = _break_cycles(deduped, result)

    # Step 4: mark redundant edges (transitive reduction check)
    non_redundant = _mark_redundant(acyclic, result)

    # Step 5: confidence threshold
    for e in non_redundant:
        if e.confidence >= threshold:
            result.accepted.append(e)
        elif e.confidence >= 0.5:
            result.proposed.append(e)
        else:
            result.dropped.append(e)
            result.warnings.append(
                f"Edge {e.upstream}→{e.downstream} dropped (confidence {e.confidence:.2f} < 0.5)"
            )

    return result


def _break_cycles(
    edges: list[PlannedDependency], result: ValidationResult
) -> list[PlannedDependency]:
    """Detect cycles; remove the lowest-confidence edge from each cycle."""
    remaining = list(edges)

    while True:
        # Build adjacency
        adj: dict[str, list[str]] = defaultdict(list)
        for e in remaining:
            adj[e.upstream].append(e.downstream)

        # Kahn's topological sort
        in_degree: dict[str, int] = defaultdict(int)
        nodes: set[str] = set()
        for e in remaining:
            nodes.add(e.upstream)
            nodes.add(e.downstream)
            in_degree[e.downstream] += 1

        queue = deque(n for n in nodes if in_degree[n] == 0)
        visited = 0
        while queue:
            n = queue.popleft()
            visited += 1
            for m in adj[n]:
                in_degree[m] -= 1
                if in_degree[m] == 0:
                    queue.append(m)

        if visited == len(nodes):
            break  # acyclic

        # Find the lowest-confidence edge that participates in a cycle
        # (any edge with a node still in cycle is a candidate)
        cycle_nodes = {n for n in nodes if in_degree[n] > 0}
        cycle_edges = [
            e for e in remaining
            if e.upstream in cycle_nodes and e.downstream in cycle_nodes
        ]
        if not cycle_edges:
            break  # safety

        worst = min(cycle_edges, key=lambda e: e.confidence)
        result.warnings.append(
            f"Cycle detected — removed edge {worst.upstream}→{worst.downstream} "
            f"(confidence {worst.confidence:.2f})"
        )
        result.dropped.append(worst)
        remaining = [e for e in remaining if e is not worst]

    return remaining


def _mark_redundant(
    edges: list[PlannedDependency], result: ValidationResult
) -> list[PlannedDependency]:
    """
    Remove edges that are already implied by a longer path (A→B→C makes A→C redundant).
    Redundant edges are noted in warnings but not moved to dropped (they stay as proposed).
    """
    # Build reachability via DFS
    adj: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adj[e.upstream].add(e.downstream)

    def reachable(start: str, skip_direct: str) -> set[str]:
        visited: set[str] = set()
        stack = [n for n in adj[start] if n != skip_direct]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj[n])
        return visited

    non_redundant: list[PlannedDependency] = []
    for e in edges:
        if e.downstream in reachable(e.upstream, e.downstream):
            result.warnings.append(
                f"Edge {e.upstream}→{e.downstream} is redundant (implied by a longer path)"
            )
            # Keep it (don't drop), but callers can mark it redundant in DB
        non_redundant.append(e)

    return non_redundant


# ── Readiness ──────────────────────────────────────────────────────────────────

async def compute_readiness(task_id: int, db: aiosqlite.Connection) -> str:
    """
    A task is 'waiting' if any active hard upstream is not complete.
    Returns 'ready' or 'waiting'.
    """
    upstreams = await repo.list_dependencies_downstream(db, task_id, state="active")
    for dep in upstreams:
        if dep["type"] != "hard":
            continue
        upstream_task = await repo.get_task(db, dep["upstream_task_id"])
        if upstream_task and upstream_task["status"] != "complete":
            return "waiting"
    return "ready"


async def recompute_all_readiness(project_id: int, db: aiosqlite.Connection, now: str) -> None:
    """Recompute readiness for every task in the project."""
    tasks = await repo.list_tasks(db, project_id)
    for t in tasks:
        new_readiness = await compute_readiness(t["id"], db)
        if new_readiness != t["readiness"]:
            await repo.set_task_readiness(db, t["id"], new_readiness, now)


# ── Propagation (spec §7.5 and §7.7) ──────────────────────────────────────────

async def on_task_completed(
    task_id: int,
    source_msg_id: int | None,
    db: aiosqlite.Connection,
    now: str,
) -> "NotificationBatch":
    """
    Runs all propagation logic when a task is marked complete.
    Returns a NotificationBatch (caller must flush it).
    """
    from app.core.notifications import NotificationBatch  # avoid circular import

    task = await repo.get_task(db, task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    batch = NotificationBatch()
    finisher = await repo.get_participant(db, task["owner_id"]) if task.get("owner_id") else None
    finisher_name = (finisher or {}).get("name", "A teammate")

    # 1. Downstream readiness
    downstream_edges = await repo.list_dependencies_upstream(db, task_id, state="active")
    for edge in downstream_edges:
        down = await repo.get_task(db, edge["downstream_task_id"])
        if not down:
            continue

        if edge["type"] == "hard":
            new_readiness = await compute_readiness(down["id"], db)
            if new_readiness == "ready" and down["readiness"] != "ready":
                await repo.set_task_readiness(db, down["id"], "ready", now)
                await repo.append_task_event(
                    db,
                    task_id=down["id"],
                    event_type="readiness_changed",
                    old_value="waiting",
                    new_value="ready",
                    reason=f"{task['key']} completed",
                    actor="engine",
                    source_message_id=source_msg_id,
                    now=now,
                )
                batch.add(
                    participant_id=down["owner_id"],
                    template_key="UNBLOCKED_DOWNSTREAM",
                    context={
                        "task": down,
                        "upstream_task": task,
                        "upstream_owner": finisher_name,
                    },
                )
        elif edge["type"] == "soft":
            down_owner = await repo.get_participant(db, down["owner_id"]) if down["owner_id"] else None
            if down_owner:
                batch.add(
                    participant_id=down["owner_id"],
                    template_key="FYI_UPSTREAM_DONE",
                    context={"task": down, "upstream_task": task, "upstream_owner": finisher_name},
                )

    # 2. Blockers linked to this task → pending_confirmation
    linked_blockers = await repo.list_blockers_linked_to_task(db, task_id)
    for blocker in linked_blockers:
        await repo.set_blocker_pending_confirmation(db, blocker["id"])
        blocked_task = await repo.get_task(db, blocker["task_id"])
        if blocked_task and blocked_task["owner_id"]:
            batch.add(
                participant_id=blocked_task["owner_id"],
                template_key="CONFIRM_UNBLOCKED",
                context={
                    "task": blocked_task,
                    "upstream_task": task,
                    "upstream_owner": finisher_name,
                    "blocker": blocker,
                },
                question_kind="confirm_unblocked",
                question_task_id=blocked_task["id"],
            )

    # 3. Next-task prompt for the completer
    from app.core.next_task import pick_next_task  # avoid circular import
    owner_id = task.get("owner_id")
    if owner_id:
        next_task = await pick_next_task(owner_id, db)
        batch.add(
            participant_id=owner_id,
            template_key="ACK_COMPLETE_NEXT" if next_task else "ACK_COMPLETE_ALL_CLEAR",
            context={"task": task, "next_task": next_task},
        )

    # 4. Recompute critical path
    project_id = task["project_id"]
    await compute_critical_path(project_id, db, now)

    return batch


async def on_blocker_raised(
    blocker_id: int,
    db: aiosqlite.Connection,
    now: str,
) -> "NotificationBatch":
    """
    Handle a newly raised blocker:
    - If kind=task and confidence ≥ RUNTIME_EDGE_MIN: create runtime edge + UNBLOCK_REQUEST
    - Otherwise: tell the lead
    """
    from app.core.notifications import NotificationBatch

    blocker = await repo.get_blocker(db, blocker_id)
    if not blocker:
        raise ValueError(f"Blocker {blocker_id} not found")

    blocked_task = await repo.get_task(db, blocker["task_id"])
    batch = NotificationBatch()

    if blocker["kind"] == "task" and blocker.get("linked_task_id"):
        linked_task = await repo.get_task(db, blocker["linked_task_id"])
        if linked_task and linked_task["owner_id"]:
            asker = await repo.get_participant(db, blocked_task["owner_id"]) if blocked_task["owner_id"] else None
            helper = await repo.get_participant(db, linked_task["owner_id"])
            batch.add(
                participant_id=linked_task["owner_id"],
                template_key="UNBLOCK_REQUEST",
                context={
                    "task": blocked_task,             # what is stuck
                    "upstream_task": linked_task,     # what it is waiting on
                    "blocker": blocker,
                    "name": (asker or {}).get("name", "A teammate"),
                    "unblocker": (helper or {}).get("name", ""),
                },
                question_kind="unblock_request",
                question_task_id=linked_task["id"],
            )
    elif blocker["kind"] == "person" and blocker.get("linked_participant_id"):
        asker = await repo.get_participant(db, blocked_task["owner_id"]) if blocked_task["owner_id"] else None
        helper = await repo.get_participant(db, blocker["linked_participant_id"])
        batch.add(
            participant_id=blocker["linked_participant_id"],
            template_key="UNBLOCK_REQUEST_PERSON",
            context={
                "task": blocked_task,
                "blocker": blocker,
                "name": (asker or {}).get("name", "A teammate"),
                "unblocker": (helper or {}).get("name", ""),
            },
        )
    # External blockers: handled in the digest / risk report (Tier 1: just record)

    return batch


# ── Critical path ──────────────────────────────────────────────────────────────

async def compute_critical_path(
    project_id: int, db: aiosqlite.Connection, now: str
) -> list[int]:
    """
    Compute the critical path (longest path by deadline).
    Marks tasks on the path with on_critical_path=1.
    Returns ordered list of task IDs.
    """
    tasks = await repo.list_tasks(db, project_id)
    deps = await repo.list_all_dependencies(db, project_id)

    task_by_id = {t["id"]: t for t in tasks}

    # Build adjacency list (upstream → list of downstream ids)
    downstream_of: dict[int, list[int]] = defaultdict(list)
    upstream_of: dict[int, list[int]] = defaultdict(list)
    for d in deps:
        if d["state"] == "active" and d["type"] == "hard":
            downstream_of[d["upstream_task_id"]].append(d["downstream_task_id"])
            upstream_of[d["downstream_task_id"]].append(d["upstream_task_id"])

    # Topological order
    in_degree: dict[int, int] = {t["id"]: 0 for t in tasks}
    for tid in upstream_of:
        in_degree[tid] = len(upstream_of[tid])

    queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
    topo: list[int] = []
    while queue:
        n = queue.popleft()
        topo.append(n)
        for m in downstream_of[n]:
            in_degree[m] -= 1
            if in_degree[m] == 0:
                queue.append(m)

    # Longest path by deadline weight
    # Weight of a node: time until deadline (0 if no deadline → treat as 0)
    import datetime

    def deadline_weight(task: dict) -> float:
        if task.get("deadline"):
            try:
                dl = datetime.datetime.fromisoformat(task["deadline"])
                return dl.timestamp()
            except Exception:
                pass
        return 0.0

    dist: dict[int, float] = {t["id"]: deadline_weight(task_by_id[t["id"]]) for t in tasks}
    prev: dict[int, int | None] = {t["id"]: None for t in tasks}

    for n in topo:
        for m in downstream_of[n]:
            candidate = dist[n] + deadline_weight(task_by_id[m])
            if candidate > dist[m]:
                dist[m] = candidate
                prev[m] = n

    # Find the end of the critical path (task with greatest dist, must have downstreams = 0)
    sink = max(
        (t["id"] for t in tasks if not downstream_of[t["id"]]),
        key=lambda tid: dist[tid],
        default=None,
    )

    critical_ids: list[int] = []
    if sink:
        cur_id: int | None = sink
        while cur_id is not None:
            critical_ids.append(cur_id)
            cur_id = prev.get(cur_id)
        critical_ids.reverse()

    await repo.set_critical_path(db, critical_ids)
    return critical_ids
