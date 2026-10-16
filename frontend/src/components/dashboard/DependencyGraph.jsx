import React, { useMemo, useState } from 'react';
import { Network, Plus, Trash2, Ban, Check } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { STATUSES, inputClass, statusMeta, darkButton, secondaryButton, percent, humanize } from './helpers';
import { Chip, EmptyState, Panel } from './ui';

const NODE_W = 150;
const NODE_H = 46;
const COL_GAP = 90;
const ROW_GAP = 22;
const PAD = 24;

const RUNTIME_COLOR = '#7c3aed';
const CRITICAL_COLOR = '#e11d48';

/** Longest-path layering (left to right), then a few barycenter sweeps to reduce crossings. */
function layoutGraph(nodes, edges) {
  const ids = nodes.map((n) => n.id);
  const incoming = new Map(ids.map((id) => [id, []]));
  const outgoing = new Map(ids.map((id) => [id, []]));
  edges.forEach((e) => {
    if (incoming.has(e.downstream) && outgoing.has(e.upstream) && e.upstream !== e.downstream) {
      incoming.get(e.downstream).push(e.upstream);
      outgoing.get(e.upstream).push(e.downstream);
    }
  });

  // Kahn topological order; anything left over is part of a cycle and gets layered best-effort.
  const indegree = new Map(ids.map((id) => [id, incoming.get(id).length]));
  const queue = ids.filter((id) => indegree.get(id) === 0);
  const layer = new Map(ids.map((id) => [id, 0]));
  const seen = new Set();
  while (queue.length) {
    const id = queue.shift();
    seen.add(id);
    outgoing.get(id).forEach((next) => {
      layer.set(next, Math.max(layer.get(next), layer.get(id) + 1));
      indegree.set(next, indegree.get(next) - 1);
      if (indegree.get(next) === 0) queue.push(next);
    });
  }
  ids.filter((id) => !seen.has(id)).forEach((id) => {
    const parents = incoming.get(id).filter((p) => seen.has(p));
    layer.set(id, parents.length ? Math.max(...parents.map((p) => layer.get(p))) + 1 : 0);
  });

  const layerCount = Math.max(0, ...layer.values()) + 1;
  const columns = Array.from({ length: layerCount }, () => []);
  nodes.forEach((n) => columns[layer.get(n.id)].push(n.id));

  const order = new Map();
  const reindex = () => columns.forEach((col) => col.forEach((id, i) => order.set(id, i)));
  reindex();
  const bary = (id, neighbours) => {
    const list = neighbours.get(id);
    return list.length ? list.reduce((sum, n) => sum + order.get(n), 0) / list.length : order.get(id);
  };
  for (let pass = 0; pass < 4; pass++) {
    for (let c = 1; c < layerCount; c++) {
      columns[c].sort((a, b) => bary(a, incoming) - bary(b, incoming));
      reindex();
    }
    for (let c = layerCount - 2; c >= 0; c--) {
      columns[c].sort((a, b) => bary(a, outgoing) - bary(b, outgoing));
      reindex();
    }
  }

  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const innerHeight = tallest * NODE_H + (tallest - 1) * ROW_GAP;
  const positions = new Map();
  columns.forEach((col, c) => {
    const colHeight = col.length * NODE_H + Math.max(0, col.length - 1) * ROW_GAP;
    const offset = (innerHeight - colHeight) / 2;
    col.forEach((id, i) => {
      positions.set(id, { x: PAD + c * (NODE_W + COL_GAP), y: PAD + offset + i * (NODE_H + ROW_GAP) });
    });
  });
  return {
    positions,
    width: PAD * 2 + layerCount * NODE_W + (layerCount - 1) * COL_GAP,
    height: PAD * 2 + innerHeight,
  };
}

function edgeStyle(edge, onCritical) {
  const runtime = edge.source === 'runtime';
  const proposed = edge.state === 'proposed';
  const rejected = edge.state === 'rejected';
  let stroke = '#94a3b8';
  if (runtime) stroke = RUNTIME_COLOR;
  if (onCritical) stroke = CRITICAL_COLOR;
  if (rejected) stroke = '#cbd5e1';
  let dash;
  if (rejected) dash = '2 3';
  else if (proposed) dash = '1.5 5';
  else if (edge.type === 'soft') dash = '6 4';
  return {
    stroke,
    dash,
    width: onCritical ? 3.5 : runtime ? 2.5 : 1.75,
    cap: proposed ? 'round' : 'butt',
    marker: onCritical ? 'arrow-critical' : runtime ? 'arrow-runtime' : 'arrow',
  };
}

const truncate = (text, n) => (text && text.length > n ? `${text.slice(0, n - 1)}…` : text);

const Legend = () => (
  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-600">
    {STATUSES.map((s) => (
      <span key={s.status} className="flex items-center gap-1.5">
        <span className="w-3 h-3 rounded" style={{ background: s.fill, border: `1.5px solid ${s.stroke}` }} /> {s.label}
      </span>
    ))}
    {[
      ['Hard dependency', undefined, '#94a3b8', 2],
      ['Soft dependency', '6 4', '#94a3b8', 2],
      ['Proposed', '1.5 5', '#94a3b8', 2.5],
      ['Runtime (learned from chat)', undefined, RUNTIME_COLOR, 2.5],
      ['Critical path', undefined, CRITICAL_COLOR, 3.5],
    ].map(([label, dash, color, width]) => (
      <span key={label} className="flex items-center gap-1.5">
        <svg width="28" height="8" aria-hidden="true">
          <line x1="1" y1="4" x2="27" y2="4" stroke={color} strokeWidth={width} strokeDasharray={dash} strokeLinecap={dash === '1.5 5' ? 'round' : 'butt'} />
        </svg>
        {label}
      </span>
    ))}
  </div>
);

const AddEdgeForm = ({ pid, nodes, onChanged }) => {
  const [upstream, setUpstream] = useState('');
  const [downstream, setDownstream] = useState('');
  const [type, setType] = useState('hard');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!upstream || !downstream || upstream === downstream) {
      toast.error('Pick two different tasks: the one that must finish first, then the one that waits.');
      return;
    }
    setBusy(true);
    try {
      await cadence.createDependency({
        project_id: pid, upstream_key: upstream, downstream_key: downstream, type, reason: reason.trim() || undefined,
      });
      toast.success(`${downstream} now waits for ${upstream}.`);
      setReason('');
      await onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  const options = nodes.map((n) => <option key={n.id} value={n.key}>{n.key} · {truncate(n.title, 40)}</option>);
  return (
    <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      <select value={upstream} onChange={(e) => setUpstream(e.target.value)} className={inputClass} aria-label="Upstream task">
        <option value="">Must finish first…</option>{options}
      </select>
      <select value={downstream} onChange={(e) => setDownstream(e.target.value)} className={inputClass} aria-label="Downstream task">
        <option value="">…before this one can finish</option>{options}
      </select>
      <select value={type} onChange={(e) => setType(e.target.value)} className={inputClass} aria-label="Dependency type">
        <option value="hard">Hard (blocks readiness)</option>
        <option value="soft">Soft (FYI only)</option>
      </select>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" className={inputClass} />
      <button type="submit" disabled={busy} className={`${darkButton} sm:col-span-2`}>
        <Plus className="w-4 h-4" /> {busy ? 'Adding…' : 'Add dependency'}
      </button>
    </form>
  );
};

const EdgeDetails = ({ edge, onChanged, onClose }) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, message) => {
    setBusy(true);
    try {
      await fn();
      toast.success(message);
      await onChanged();
      onClose();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="border border-slate-200 rounded-xl p-3 text-sm bg-slate-50 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-900">{edge.upstream_key} → {edge.downstream_key}</span>
        <Chip tone={edge.type === 'hard' ? 'blue' : 'slate'}>{edge.type}</Chip>
        <Chip tone={edge.state === 'active' ? 'green' : edge.state === 'proposed' ? 'amber' : 'slate'}>{edge.state}</Chip>
        <Chip tone={edge.source === 'runtime' ? 'violet' : 'slate'}>{edge.source}</Chip>
        {percent(edge.confidence) && <span className="text-xs text-slate-500">confidence {percent(edge.confidence)}</span>}
      </div>
      {edge.reason && <p className="text-slate-600">{edge.reason}</p>}
      <div className="flex flex-wrap gap-2">
        {edge.state !== 'active' && (
          <button type="button" disabled={busy} className={secondaryButton} onClick={() => run(() => cadence.updateDependency(edge.id, { state: 'active' }), 'Dependency accepted.')}>
            <Check className="w-4 h-4" /> Accept
          </button>
        )}
        {edge.state !== 'rejected' && (
          <button type="button" disabled={busy} className={secondaryButton} onClick={() => run(() => cadence.updateDependency(edge.id, { state: 'rejected' }), 'Dependency rejected.')}>
            <Ban className="w-4 h-4" /> Reject
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          className={`${secondaryButton} !text-red-700`}
          onClick={() => {
            if (window.confirm(`Remove the dependency ${edge.upstream_key} → ${edge.downstream_key}?`)) {
              run(() => cadence.deleteDependency(edge.id), 'Dependency removed.');
            }
          }}
        >
          <Trash2 className="w-4 h-4" /> Remove
        </button>
        <button type="button" onClick={onClose} className="text-sm text-slate-500 px-2">Close</button>
      </div>
    </div>
  );
};

const DependencyGraph = ({ pid, graph, onOpenTask, onChanged }) => {
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [showRejected, setShowRejected] = useState(false);
  const [hover, setHover] = useState(null);

  const nodes = useMemo(() => graph?.nodes || [], [graph]);
  const allEdges = useMemo(() => graph?.edges || [], [graph]);
  const keyById = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n.key])), [nodes]);
  const critical = useMemo(() => graph?.critical_path || [], [graph]);

  const edges = useMemo(
    () => allEdges
      .map((e) => ({
        ...e,
        upstream_key: e.upstream_key || keyById[e.upstream],
        downstream_key: e.downstream_key || keyById[e.downstream],
      }))
      .filter((e) => showRejected || e.state !== 'rejected'),
    [allEdges, keyById, showRejected],
  );
  const hiddenCount = allEdges.filter((e) => e.state === 'rejected').length;

  const criticalPairs = useMemo(() => {
    const set = new Set();
    for (let i = 0; i + 1 < critical.length; i++) set.add(`${critical[i]}>${critical[i + 1]}`);
    return set;
  }, [critical]);
  const criticalKeys = useMemo(() => new Set(critical), [critical]);

  const layout = useMemo(() => layoutGraph(nodes, edges.filter((e) => e.state !== 'rejected')), [nodes, edges]);
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) || null;

  if (nodes.length === 0) {
    return (
      <EmptyState icon={Network} title="No dependency graph yet">
        Once the plan is committed, tasks and the dependencies between them appear here.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4">
      <Panel
        icon={Network}
        title="Dependency graph"
        actions={hiddenCount > 0 && (
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            <input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} />
            Show rejected ({hiddenCount})
          </label>
        )}
      >
        <div className="overflow-auto border border-slate-100 rounded-xl bg-slate-50/50 max-h-[70vh]">
          <svg
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            role="img"
            aria-label="Task dependency graph"
            className="block"
          >
            <defs>
              {[['arrow', '#94a3b8'], ['arrow-runtime', RUNTIME_COLOR], ['arrow-critical', CRITICAL_COLOR]].map(([id, color]) => (
                <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0 0 L10 5 L0 10 z" fill={color} />
                </marker>
              ))}
            </defs>

            {edges.map((edge) => {
              const from = layout.positions.get(edge.upstream);
              const to = layout.positions.get(edge.downstream);
              if (!from || !to) return null;
              const x1 = from.x + NODE_W;
              const y1 = from.y + NODE_H / 2;
              const x2 = to.x;
              const y2 = to.y + NODE_H / 2;
              const mid = Math.max(30, (x2 - x1) / 2);
              const d = `M${x1},${y1} C${x1 + mid},${y1} ${x2 - mid},${y2} ${x2},${y2}`;
              const onCritical = criticalPairs.has(`${edge.upstream_key}>${edge.downstream_key}`) && edge.state === 'active';
              const style = edgeStyle(edge, onCritical);
              const selected = edge.id === selectedEdgeId;
              return (
                <g key={edge.id}>
                  <path
                    d={d}
                    fill="none"
                    stroke={style.stroke}
                    strokeWidth={selected ? style.width + 1.5 : style.width}
                    strokeDasharray={style.dash}
                    strokeLinecap={style.cap}
                    markerEnd={`url(#${style.marker})`}
                    opacity={edge.state === 'rejected' ? 0.6 : 1}
                  />
                  <path
                    d={d}
                    fill="none"
                    stroke="transparent"
                    strokeWidth="14"
                    className="cursor-pointer"
                    onClick={() => setSelectedEdgeId(edge.id)}
                  >
                    <title>{`${edge.upstream_key} → ${edge.downstream_key} (${edge.type}, ${edge.source}, ${edge.state})${edge.reason ? `: ${edge.reason}` : ''}`}</title>
                  </path>
                </g>
              );
            })}

            {nodes.map((node) => {
              const pos = layout.positions.get(node.id);
              if (!pos) return null;
              const meta = statusMeta(node.status);
              const onCritical = criticalKeys.has(node.key) || node.on_critical_path;
              return (
                <g
                  key={node.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  className="cursor-pointer"
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.key} ${node.title}, ${meta.label}`}
                  onClick={() => onOpenTask(node.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpenTask(node.id); } }}
                  onMouseEnter={() => setHover(node.id)}
                  onMouseLeave={() => setHover(null)}
                >
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx="10"
                    fill={meta.fill}
                    stroke={onCritical ? CRITICAL_COLOR : meta.stroke}
                    strokeWidth={onCritical ? 3.5 : hover === node.id ? 2.5 : 1.5}
                  />
                  <text x="10" y="19" fontSize="12" fontWeight="700" fill={meta.text}>{node.key}</text>
                  {node.readiness === 'waiting' && node.status !== 'complete' && (
                    <text x={NODE_W - 10} y="19" fontSize="10" textAnchor="end" fill={meta.text} opacity="0.7">waiting</text>
                  )}
                  <text x="10" y="35" fontSize="11" fill={meta.text}>{truncate(node.title, 22)}</text>
                  <title>{`${node.key}: ${node.title}${node.owner_name ? ` (${node.owner_name})` : ''} - ${humanize(node.status)}, ${node.readiness}`}</title>
                </g>
              );
            })}
          </svg>
        </div>
        <div className="mt-3"><Legend /></div>
        <p className="text-xs text-slate-400 mt-2">Click a task to open it, or an edge to accept, reject or remove it. Left to right is the order work has to happen in.</p>
      </Panel>

      {selectedEdge && (
        <EdgeDetails
          key={selectedEdge.id}
          edge={selectedEdge}
          onChanged={onChanged}
          onClose={() => setSelectedEdgeId(null)}
        />
      )}

      <Panel icon={Plus} title="Add a dependency">
        <AddEdgeForm pid={pid} nodes={nodes} onChanged={onChanged} />
      </Panel>

      {edges.length > 0 && (
        <Panel title={`All dependencies (${edges.length})`}>
          <ul className="divide-y divide-slate-100 text-sm">
            {edges.map((edge) => (
              <li key={edge.id}>
                <button type="button" onClick={() => setSelectedEdgeId(edge.id)} className="w-full text-left py-2 flex flex-wrap items-center gap-2 hover:bg-slate-50 rounded-lg px-1">
                  <span className="font-semibold text-slate-900">{edge.upstream_key} → {edge.downstream_key}</span>
                  <Chip tone={edge.type === 'hard' ? 'blue' : 'slate'}>{edge.type}</Chip>
                  <Chip tone={edge.state === 'active' ? 'green' : edge.state === 'proposed' ? 'amber' : 'slate'}>{edge.state}</Chip>
                  {edge.source === 'runtime' && <Chip tone="violet">runtime</Chip>}
                  <span className="text-xs text-slate-500 truncate flex-1 min-w-[8rem]">{edge.reason}</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
};

export default DependencyGraph;
