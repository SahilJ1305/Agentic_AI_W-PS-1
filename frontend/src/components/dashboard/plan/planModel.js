// Pure logic behind the Plan review screen: no React, so it can be tested with `node --test`.
// A "draft" is the planner's output: { tasks: [{key, title, estimate_hours, owner_name, ...}],
// dependencies: [{upstream, downstream, type, confidence, reason, evidence_quote, rule}] }.
// `decisions` maps "UP>DOWN" to true (accepted) or false (rejected).

export const AUTO_ACCEPT_CONFIDENCE = 0.8;

export const pairKey = (dep) => `${dep.upstream}>${dep.downstream}`;

export const initialDecisions = (draft) =>
  Object.fromEntries((draft?.dependencies || []).map((d) => [pairKey(d), (d.confidence ?? 1) >= AUTO_ACCEPT_CONFIDENCE]));

export const NODE = { w: 184, h: 64, colGap: 100, rowGap: 26, pad: 28 };

// ── owners ─────────────────────────────────────────────────────────────────────

const PALETTE = [
  { bar: '#2563eb', bg: '#dbeafe', fg: '#1e3a8a' },
  { bar: '#059669', bg: '#d1fae5', fg: '#064e3b' },
  { bar: '#7c3aed', bg: '#ede9fe', fg: '#4c1d95' },
  { bar: '#db2777', bg: '#fce7f3', fg: '#831843' },
  { bar: '#ea580c', bg: '#ffedd5', fg: '#7c2d12' },
  { bar: '#0891b2', bg: '#cffafe', fg: '#164e63' },
  { bar: '#ca8a04', bg: '#fef9c3', fg: '#713f12' },
  { bar: '#4f46e5', bg: '#e0e7ff', fg: '#312e81' },
];
const NO_OWNER = { bar: '#94a3b8', bg: '#f1f5f9', fg: '#475569' };

export function ownerStyle(name) {
  if (!name) return NO_OWNER;
  let hash = 0;
  for (const ch of String(name)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

export const initials = (name) =>
  String(name || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';

// ── layout: layers left to right, then a few sweeps to reduce crossings ─────────

export function layoutLayers(keys, edges, dims = NODE) {
  const incoming = new Map(keys.map((k) => [k, []]));
  const outgoing = new Map(keys.map((k) => [k, []]));
  edges.forEach((e) => {
    if (incoming.has(e.downstream) && outgoing.has(e.upstream) && e.upstream !== e.downstream) {
      incoming.get(e.downstream).push(e.upstream);
      outgoing.get(e.upstream).push(e.downstream);
    }
  });

  const indegree = new Map(keys.map((k) => [k, incoming.get(k).length]));
  const queue = keys.filter((k) => indegree.get(k) === 0);
  const layer = new Map(keys.map((k) => [k, 0]));
  const seen = new Set();
  while (queue.length) {
    const k = queue.shift();
    seen.add(k);
    outgoing.get(k).forEach((next) => {
      layer.set(next, Math.max(layer.get(next), layer.get(k) + 1));
      indegree.set(next, indegree.get(next) - 1);
      if (indegree.get(next) === 0) queue.push(next);
    });
  }
  // anything left is on a cycle: place it after its already-placed parents
  keys.filter((k) => !seen.has(k)).forEach((k) => {
    const parents = incoming.get(k).filter((p) => seen.has(p));
    layer.set(k, parents.length ? Math.max(...parents.map((p) => layer.get(p))) + 1 : 0);
  });

  const layerCount = Math.max(0, ...layer.values()) + 1;
  const columns = Array.from({ length: layerCount }, () => []);
  keys.forEach((k) => columns[layer.get(k)].push(k));

  const order = new Map();
  const reindex = () => columns.forEach((col) => col.forEach((k, i) => order.set(k, i)));
  reindex();
  const bary = (k, neighbours) => {
    const list = neighbours.get(k);
    return list.length ? list.reduce((sum, n) => sum + order.get(n), 0) / list.length : order.get(k);
  };
  for (let pass = 0; pass < 4; pass++) {
    for (let c = 1; c < layerCount; c++) { columns[c].sort((a, b) => bary(a, incoming) - bary(b, incoming)); reindex(); }
    for (let c = layerCount - 2; c >= 0; c--) { columns[c].sort((a, b) => bary(a, outgoing) - bary(b, outgoing)); reindex(); }
  }

  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const innerHeight = tallest * dims.h + (tallest - 1) * dims.rowGap;
  const positions = new Map();
  columns.forEach((col, c) => {
    const colHeight = col.length * dims.h + Math.max(0, col.length - 1) * dims.rowGap;
    const offset = (innerHeight - colHeight) / 2;
    col.forEach((k, i) => positions.set(k, { x: dims.pad + c * (dims.w + dims.colGap), y: dims.pad + offset + i * (dims.h + dims.rowGap) }));
  });
  return {
    positions,
    layerOf: layer,
    width: dims.pad * 2 + layerCount * dims.w + (layerCount - 1) * dims.colGap,
    height: dims.pad * 2 + innerHeight,
  };
}

// ── the model ──────────────────────────────────────────────────────────────────

/**
 * Everything the screen shows, derived from the draft plus the lead's decisions and owner choices.
 * Only accepted HARD dependencies block work, so only they decide stages and the critical path.
 */
export function buildPlanModel(draft, decisions = {}, owners = {}) {
  const tasks = draft?.tasks || [];
  const byKey = new Map(tasks.map((t) => [t.key, t]));
  const seenPairs = new Set();
  const edges = [];
  (draft?.dependencies || []).forEach((d) => {
    const id = pairKey(d);
    if (!byKey.has(d.upstream) || !byKey.has(d.downstream) || d.upstream === d.downstream || seenPairs.has(id)) return;
    seenPairs.add(id);
    edges.push({
      ...d,
      id,
      accepted: Boolean(decisions[id]),
      hard: (d.type ?? 'hard') === 'hard',
      needsReview: (d.confidence ?? 1) < AUTO_ACCEPT_CONFIDENCE,
    });
  });

  const ownerOf = (key) => owners[key] ?? byKey.get(key)?.owner_name ?? '';

  // stages and critical path over accepted hard edges
  const keys = tasks.map((t) => t.key);
  const blocking = edges.filter((e) => e.accepted && e.hard);
  const parents = new Map(keys.map((k) => [k, []]));
  const children = new Map(keys.map((k) => [k, []]));
  blocking.forEach((e) => { parents.get(e.downstream).push(e.upstream); children.get(e.upstream).push(e.downstream); });

  const indegree = new Map(keys.map((k) => [k, parents.get(k).length]));
  const queue = keys.filter((k) => indegree.get(k) === 0);
  const topo = [];
  const stage = new Map(keys.map((k) => [k, 0]));
  while (queue.length) {
    const k = queue.shift();
    topo.push(k);
    children.get(k).forEach((next) => {
      stage.set(next, Math.max(stage.get(next), stage.get(k) + 1));
      indegree.set(next, indegree.get(next) - 1);
      if (indegree.get(next) === 0) queue.push(next);
    });
  }
  const onCycle = keys.filter((k) => !topo.includes(k));
  onCycle.forEach((k) => {
    const placed = parents.get(k).filter((p) => topo.includes(p));
    stage.set(k, placed.length ? Math.max(...placed.map((p) => stage.get(p))) + 1 : 0);
  });

  const hoursOf = (k) => Number(byKey.get(k)?.estimate_hours) || 0;
  const totalHours = keys.reduce((sum, k) => sum + hoursOf(k), 0);
  const weight = (k) => (totalHours > 0 ? hoursOf(k) : 1);   // no estimates at all: count steps instead
  const dist = new Map();
  const prev = new Map();
  topo.forEach((k) => {
    const best = parents.get(k).reduce((acc, p) => (acc === null || dist.get(p) > dist.get(acc) ? p : acc), null);
    dist.set(k, weight(k) + (best === null ? 0 : dist.get(best)));
    prev.set(k, best);
  });
  let end = null;
  topo.forEach((k) => { if (end === null || dist.get(k) > dist.get(end)) end = k; });
  const path = [];
  for (let k = end; k !== null && k !== undefined; k = prev.get(k)) path.unshift(k);
  const criticalPath = {
    keys: path.length > 1 ? path : [],
    hours: path.reduce((sum, k) => sum + hoursOf(k), 0),
    steps: path.length,
  };
  const criticalPairs = new Set();
  for (let i = 0; i + 1 < criticalPath.keys.length; i++) criticalPairs.add(`${criticalPath.keys[i]}>${criticalPath.keys[i + 1]}`);

  // neighbours over every accepted edge (hard or soft), for highlighting
  const accepted = edges.filter((e) => e.accepted);
  const reach = (start, next) => {
    const out = new Set();
    const stack = [start];
    while (stack.length) {
      const k = stack.pop();
      (next.get(k) || []).forEach((n) => { if (!out.has(n)) { out.add(n); stack.push(n); } });
    }
    return out;
  };
  const up = new Map(keys.map((k) => [k, []]));
  const down = new Map(keys.map((k) => [k, []]));
  accepted.forEach((e) => { up.get(e.downstream).push(e.upstream); down.get(e.upstream).push(e.downstream); });
  const relatedTo = (key) => new Set([key, ...reach(key, up), ...reach(key, down)]);

  const waitsFor = (k) => blocking.filter((e) => e.downstream === k).map((e) => e.upstream);
  const unlocks = (k) => blocking.filter((e) => e.upstream === k).map((e) => e.downstream);

  // stages: groups of tasks that can run in parallel once the previous stage is done
  const stageCount = Math.max(0, ...stage.values()) + 1;
  const stages = Array.from({ length: stageCount }, (_, i) => keys.filter((k) => stage.get(k) === i).map((k) => byKey.get(k)));

  // workload per person (effective owners, including the lead's choices in this screen)
  const load = new Map();
  tasks.forEach((t) => {
    const name = ownerOf(t.key) || '';
    const row = load.get(name) || { name, hours: 0, tasks: 0 };
    row.hours += hoursOf(t.key);
    row.tasks += 1;
    load.set(name, row);
  });
  const workload = [...load.values()].sort((a, b) => (a.name === '' ? 1 : b.name === '' ? -1 : b.hours - a.hours || b.tasks - a.tasks));

  return {
    tasks, byKey, edges, ownerOf, stage, stages, criticalPath, criticalPairs, onCycle,
    relatedTo, waitsFor, unlocks, workload,
    totals: {
      tasks: tasks.length,
      hours: totalHours,
      accepted: edges.filter((e) => e.accepted).length,
      rejected: edges.filter((e) => !e.accepted).length,
      needsReview: edges.filter((e) => e.needsReview).length,
      unassigned: tasks.filter((t) => !ownerOf(t.key)).length,
      people: workload.filter((w) => w.name).length,
    },
  };
}
