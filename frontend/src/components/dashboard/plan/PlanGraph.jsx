import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Maximize2, MousePointerClick, Plus, Quote, X, ZoomIn, ZoomOut } from 'lucide-react';
import { percent } from '../helpers';
import { Chip } from '../ui';
import { NODE, initials, layoutLayers, ownerStyle } from './planModel';

const COLORS = {
  hard: '#64748b',
  soft: '#94a3b8',
  review: '#f59e0b',
  critical: '#e11d48',
  rejected: '#fca5a5',
  accept: '#059669',
  reject: '#ef4444',
};

const truncate = (text, n) => (text && text.length > n ? `${text.slice(0, n - 1)}…` : text || '');

function edgeLook(edge, critical) {
  if (!edge.accepted && edge.needsReview) return { color: COLORS.review, width: 1.75, dash: '4 4', marker: 'plan-arrow-review', opacity: 0.85 };
  if (!edge.accepted) return { color: COLORS.rejected, width: 1.75, dash: '4 4', marker: 'plan-arrow-rejected', opacity: 0.9 };
  if (critical) return { color: COLORS.critical, width: 3.5, dash: undefined, marker: 'plan-arrow-critical', opacity: 1 };
  if (edge.needsReview) return { color: COLORS.review, width: 2.25, dash: edge.hard ? undefined : '6 4', marker: 'plan-arrow-review', opacity: 1 };
  return { color: edge.hard ? COLORS.hard : COLORS.soft, width: 2, dash: edge.hard ? undefined : '6 4', marker: edge.hard ? 'plan-arrow' : 'plan-arrow-soft', opacity: 1 };
}

const Legend = () => (
  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-600">
    {[
      ['Accepted', COLORS.hard, undefined, 2],
      ['Soft (FYI only)', COLORS.soft, '6 4', 2],
      ['Needs your review (not included yet)', COLORS.review, '4 4', 2],
      ['Rejected', COLORS.rejected, '4 4', 1.75],
      ['Critical path', COLORS.critical, undefined, 3.5],
    ].map(([label, color, dash, width]) => (
      <span key={label} className="flex items-center gap-1.5">
        <svg width="28" height="8" aria-hidden="true"><line x1="1" y1="4" x2="27" y2="4" stroke={color} strokeWidth={width} strokeDasharray={dash} /></svg>
        {label}
      </span>
    ))}
    <span className="flex items-center gap-1.5">
      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-600 text-white"><Check className="h-2.5 w-2.5" /></span>
      included
      <span className="flex h-4 w-4 items-center justify-center rounded-full border-2 border-amber-500 bg-white text-amber-600"><Plus className="h-2.5 w-2.5" /></span>
      not included, click to add
    </span>
  </div>
);

/** Right-hand card: what the current selection means, with the controls to change it. */
export const SelectionCard = ({ model, selection, onSelect, onDecide, owners }) => {
  if (!selection) {
    const path = model.criticalPath;
    return (
      <div className="space-y-3 text-sm text-slate-600">
        <p className="flex items-start gap-2"><MousePointerClick className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
          Click a task to see what it waits for and what it unlocks. Click a line to read why the planner linked two tasks.</p>
        <p>The round badge on each line accepts or rejects it with one click. Lines in amber are the ones the planner was less sure about.</p>
        {path.keys.length > 0 && (
          <p className="rounded-xl bg-rose-50 p-3 text-rose-900">
            <strong>Critical path:</strong> {path.keys.join(' → ')}
            {path.hours > 0 ? ` (${path.hours} h)` : ''}. If any of these slip, the finish slips.
          </p>
        )}
      </div>
    );
  }

  if (selection.type === 'edge') {
    const edge = model.edges.find((e) => e.id === selection.id);
    if (!edge) return null;
    const from = model.byKey.get(edge.upstream);
    const to = model.byKey.get(edge.downstream);
    const confidence = edge.confidence ?? 1;
    return (
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => onSelect({ type: 'node', id: edge.upstream })} className="font-semibold text-blue-700 hover:underline">{edge.upstream}</button>
          <span className="text-slate-400">→</span>
          <button type="button" onClick={() => onSelect({ type: 'node', id: edge.downstream })} className="font-semibold text-blue-700 hover:underline">{edge.downstream}</button>
          <Chip tone={edge.hard ? 'blue' : 'slate'}>{edge.hard ? 'hard' : 'soft'}</Chip>
          {edge.rule && <Chip tone="violet" title="Rule that proposed this link">{edge.rule}</Chip>}
        </div>
        <p className="text-slate-700"><strong>{to?.title}</strong> {edge.hard ? 'cannot start until' : 'benefits from'} <strong>{from?.title}</strong> {edge.hard ? 'is done' : 'is done'}.</p>
        <div>
          <div className="mb-1 flex justify-between text-xs text-slate-500"><span>Planner confidence</span><span className="font-semibold text-slate-700">{percent(confidence)}</span></div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full rounded-full ${edge.needsReview ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${Math.round(confidence * 100)}%` }} />
          </div>
        </div>
        {edge.reason && <p className="text-slate-600">{edge.reason}</p>}
        {edge.evidence_quote && (
          <p className="flex gap-1.5 border-l-2 border-slate-200 pl-2 text-xs italic text-slate-500"><Quote className="mt-0.5 h-3 w-3 shrink-0" /> {edge.evidence_quote}</p>
        )}
        <DecisionButtons accepted={edge.accepted} onDecide={(v) => onDecide(edge.id, v)} label={`${edge.upstream} → ${edge.downstream}`} />
      </div>
    );
  }

  const task = model.byKey.get(selection.id);
  if (!task) return null;
  const owner = model.ownerOf(task.key);
  const style = ownerStyle(owner);
  const mine = model.edges.filter((e) => e.upstream === task.key || e.downstream === task.key);
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="flex items-center gap-2">
          <span className="rounded-md px-1.5 py-0.5 text-xs font-bold" style={{ background: style.bg, color: style.fg }}>{task.key}</span>
          <span className="font-semibold text-slate-900">{task.title}</span>
        </div>
        {task.description && <p className="mt-1 text-slate-600">{task.description}</p>}
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Chip tone="slate">{owner || 'Unassigned'}</Chip>
          {task.estimate_hours != null && <Chip tone="slate">{task.estimate_hours} h</Chip>}
          {task.requires_evidence && <Chip tone="amber">needs evidence</Chip>}
          {model.criticalPath.keys.includes(task.key) && <Chip tone="red">critical path</Chip>}
        </div>
      </div>
      {mine.length === 0 ? (
        <p className="text-slate-500">No dependencies: this task can start right away and nothing waits for it.</p>
      ) : (
        <ul className="space-y-1.5">
          {mine.map((e) => {
            const incoming = e.downstream === task.key;
            const other = incoming ? e.upstream : e.downstream;
            return (
              <li key={e.id} className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${e.accepted ? 'border-slate-200' : 'border-red-100 bg-red-50/40 opacity-80'}`}>
                <span className="min-w-0 flex-1">
                  <span className="text-xs text-slate-500">{incoming ? 'Waits for' : 'Unlocks'}</span>{' '}
                  <button type="button" onClick={() => onSelect({ type: 'node', id: other })} className="font-semibold text-blue-700 hover:underline">{other}</button>
                  {!e.hard && <span className="ml-1 text-xs text-slate-400">(soft)</span>}
                  {e.needsReview && <span className="ml-1 text-xs text-amber-600">· {percent(e.confidence ?? 1)}</span>}
                </span>
                <DecisionButtons compact accepted={e.accepted} onDecide={(v) => onDecide(e.id, v)} label={e.id} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export const DecisionButtons = ({ accepted, onDecide, label, compact = false }) => (
  <div className="flex shrink-0 gap-1" role="group" aria-label={`Decision for ${label}`}>
    <button
      type="button"
      aria-pressed={accepted}
      onClick={() => onDecide(true)}
      title="Accept"
      className={`rounded-lg border ${compact ? 'p-1' : 'px-3 py-1.5 text-sm font-semibold'} inline-flex items-center gap-1 transition-colors ${accepted ? 'border-emerald-600 bg-emerald-600 text-white' : 'border-slate-300 text-slate-500 hover:bg-slate-50'}`}
    >
      <Check className="h-4 w-4" />{!compact && 'Accept'}
    </button>
    <button
      type="button"
      aria-pressed={!accepted}
      onClick={() => onDecide(false)}
      title="Reject"
      className={`rounded-lg border ${compact ? 'p-1' : 'px-3 py-1.5 text-sm font-semibold'} inline-flex items-center gap-1 transition-colors ${!accepted ? 'border-red-600 bg-red-600 text-white' : 'border-slate-300 text-slate-500 hover:bg-slate-50'}`}
    >
      <X className="h-4 w-4" />{!compact && 'Reject'}
    </button>
  </div>
);

const ZOOM_MIN = 0.45;
const AUTO_FIT_MIN = 0.65;
const ZOOM_MAX = 1.4;

const PlanGraph = React.forwardRef(({ model, selection, onSelect, onDecide }, ref) => {
  const scroller = useRef(null);
  const [zoom, setZoom] = useState(1);
  const fittedFor = useRef(null);

  const keys = useMemo(() => model.tasks.map((t) => t.key), [model.tasks]);
  const pairs = model.edges.map((e) => e.id).join('|');
  // the layout depends on which links exist, not on whether they are accepted, so nothing jumps when you decide
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const layout = useMemo(() => layoutLayers(keys, model.edges), [keys, pairs]);

  // minZoom keeps the automatic fit readable (long chains scroll sideways); the Fit button squeezes everything in.
  const fit = (minZoom = ZOOM_MIN) => {
    const room = scroller.current?.clientWidth;
    if (!room) return false;
    setZoom(Math.max(minZoom, Math.min(1, (room - 4) / layout.width)));
    return true;
  };
  // Fit on first sight and whenever a new plan changes the graph's width. The tab is mounted while hidden,
  // so wait until the container has a real width instead of giving up at zero.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return undefined;
    const tryFit = () => {
      if (fittedFor.current !== layout.width && el.clientWidth > 0) {
        fittedFor.current = layout.width;
        fit(AUTO_FIT_MIN);
      }
    };
    tryFit();
    const observer = new ResizeObserver(tryFit);
    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout.width]);

  const focus = useMemo(() => {
    if (!selection) return null;
    if (selection.type === 'node') return model.relatedTo(selection.id);
    const edge = model.edges.find((e) => e.id === selection.id);
    return edge ? new Set([edge.upstream, edge.downstream]) : null;
  }, [selection, model]);

  const w = layout.width * zoom;
  const h = layout.height * zoom;

  return (
    <div ref={ref}>
      <div className="mb-2 flex items-center justify-end gap-1">
        <button type="button" onClick={() => setZoom((z) => Math.max(ZOOM_MIN, +(z - 0.15).toFixed(2)))} aria-label="Zoom out" className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"><ZoomOut className="h-4 w-4" /></button>
        <span className="w-12 text-center text-xs tabular-nums text-slate-500">{Math.round(zoom * 100)}%</span>
        <button type="button" onClick={() => setZoom((z) => Math.min(ZOOM_MAX, +(z + 0.15).toFixed(2)))} aria-label="Zoom in" className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"><ZoomIn className="h-4 w-4" /></button>
        <button type="button" onClick={() => fit()} aria-label="Fit to width" title="Fit to width" className="rounded-lg border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-50"><Maximize2 className="h-4 w-4" /></button>
      </div>

      <div ref={scroller} className="max-h-[70vh] overflow-auto rounded-xl border border-slate-100 bg-[radial-gradient(circle,#e2e8f0_1px,transparent_1px)] [background-size:18px_18px] bg-slate-50/60" onClick={() => onSelect(null)}>
        <svg width={w} height={h} viewBox={`0 0 ${layout.width} ${layout.height}`} role="group" aria-label="Task dependency graph for this plan" className="block">
          <defs>
            {[['plan-arrow', COLORS.hard], ['plan-arrow-soft', COLORS.soft], ['plan-arrow-review', COLORS.review], ['plan-arrow-critical', COLORS.critical], ['plan-arrow-rejected', COLORS.rejected]].map(([id, color]) => (
              <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" fill={color} />
              </marker>
            ))}
            <filter id="plan-node-shadow" x="-10%" y="-10%" width="120%" height="130%">
              <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodColor="#0f172a" floodOpacity="0.12" />
            </filter>
          </defs>

          {model.edges.map((edge) => {
            const from = layout.positions.get(edge.upstream);
            const to = layout.positions.get(edge.downstream);
            if (!from || !to) return null;
            const x1 = from.x + NODE.w; const y1 = from.y + NODE.h / 2;
            const x2 = to.x; const y2 = to.y + NODE.h / 2;
            const mid = Math.max(36, Math.abs(x2 - x1) / 2);
            const d = `M${x1},${y1} C${x1 + mid},${y1} ${x2 - mid},${y2} ${x2},${y2}`;
            const look = edgeLook(edge, model.criticalPairs.has(edge.id) && edge.accepted);
            const selected = selection?.type === 'edge' && selection.id === edge.id;
            const dimmed = focus && !(focus.has(edge.upstream) && focus.has(edge.downstream) && (selection.type === 'edge' ? selected : true));
            const bx = (x1 + x2) / 2; const by = (y1 + y2) / 2;
            return (
              <g key={edge.id} opacity={dimmed ? 0.18 : look.opacity}>
                {selected && <path d={d} fill="none" stroke="#3b82f6" strokeWidth={look.width + 7} opacity="0.25" />}
                <path d={d} fill="none" stroke={look.color} strokeWidth={look.width} strokeDasharray={look.dash} markerEnd={`url(#${look.marker})`} />
                <path d={d} fill="none" stroke="transparent" strokeWidth="16" className="cursor-pointer" onClick={(e) => { e.stopPropagation(); onSelect({ type: 'edge', id: edge.id }); }}>
                  <title>{`${edge.upstream} → ${edge.downstream} (${edge.hard ? 'hard' : 'soft'}, ${percent(edge.confidence ?? 1)})${edge.reason ? `: ${edge.reason}` : ''}`}</title>
                </path>
                <g
                  transform={`translate(${bx},${by})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${edge.accepted ? 'Reject' : 'Accept'} ${edge.upstream} to ${edge.downstream}`}
                  aria-pressed={edge.accepted}
                  className="cursor-pointer outline-none"
                  onClick={(e) => { e.stopPropagation(); onDecide(edge.id, !edge.accepted); }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onDecide(edge.id, !edge.accepted); } }}
                >
                  {edge.accepted ? (
                    <>
                      <circle r="10" fill={COLORS.accept} stroke={edge.needsReview ? COLORS.review : '#fff'} strokeWidth={edge.needsReview ? 3 : 2} />
                      <path d="M-4 0.5 L-1 3.5 L4.5 -3" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </>
                  ) : edge.needsReview ? (
                    <>
                      <circle r="10" fill="#fff" stroke={COLORS.review} strokeWidth="2.5" />
                      <path d="M-4 0 L4 0 M0 -4 L0 4" fill="none" stroke={COLORS.review} strokeWidth="2.25" strokeLinecap="round" />
                    </>
                  ) : (
                    <>
                      <circle r="10" fill={COLORS.reject} stroke="#fff" strokeWidth="2" />
                      <path d="M-3.5 -3.5 L3.5 3.5 M3.5 -3.5 L-3.5 3.5" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
                    </>
                  )}
                  <title>{`${edge.accepted ? 'Accepted' : edge.needsReview ? 'Not included yet' : 'Rejected'}: click to ${edge.accepted ? 'reject' : 'accept'}${edge.needsReview ? ` (planner was ${percent(edge.confidence ?? 1)} sure)` : ''}`}</title>
                </g>
              </g>
            );
          })}

          {model.tasks.map((task) => {
            const pos = layout.positions.get(task.key);
            if (!pos) return null;
            const owner = model.ownerOf(task.key);
            const style = ownerStyle(owner);
            const selected = selection?.type === 'node' && selection.id === task.key;
            const onPath = model.criticalPath.keys.includes(task.key);
            const dimmed = focus && !focus.has(task.key);
            return (
              <g
                key={task.key}
                transform={`translate(${pos.x},${pos.y})`}
                opacity={dimmed ? 0.3 : 1}
                className="cursor-pointer outline-none"
                role="button"
                tabIndex={0}
                aria-label={`${task.key} ${task.title}, ${owner || 'unassigned'}`}
                onClick={(e) => { e.stopPropagation(); onSelect(selected ? null : { type: 'node', id: task.key }); }}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect({ type: 'node', id: task.key }); } }}
              >
                {selected && <rect x="-4" y="-4" width={NODE.w + 8} height={NODE.h + 8} rx="15" fill="none" stroke="#3b82f6" strokeWidth="2.5" />}
                <rect width={NODE.w} height={NODE.h} rx="12" fill="#fff" stroke={onPath ? COLORS.critical : '#cbd5e1'} strokeWidth={onPath ? 2.5 : 1.25} filter="url(#plan-node-shadow)" />
                <rect width="7" height={NODE.h} rx="3.5" fill={style.bar} />
                <text x="18" y="21" fontSize="12" fontWeight="700" fill="#0f172a">{task.key}</text>
                {task.estimate_hours != null && <text x={NODE.w - 12} y="21" fontSize="10.5" textAnchor="end" fill="#64748b">{task.estimate_hours} h</text>}
                <text x="18" y="39" fontSize="11" fill="#334155">{truncate(task.title, 25)}</text>
                <text x="18" y="55" fontSize="10" fill={style.fg}>{truncate(owner || 'Unassigned', 20)}</text>
                <circle cx={NODE.w - 20} cy={NODE.h - 17} r="10" fill={style.bg} stroke={owner ? 'none' : '#94a3b8'} strokeDasharray={owner ? undefined : '2 2'} />
                <text x={NODE.w - 20} y={NODE.h - 13.5} fontSize="9.5" fontWeight="700" textAnchor="middle" fill={style.fg}>{owner ? initials(owner) : '?'}</text>
                <title>{`${task.key}: ${task.title}${owner ? ` (${owner})` : ''}`}</title>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-3"><Legend /></div>
    </div>
  );
});
PlanGraph.displayName = 'PlanGraph';

export default PlanGraph;
