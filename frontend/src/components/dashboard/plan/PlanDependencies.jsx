import React, { useMemo, useState } from 'react';
import { GitBranch, Quote } from 'lucide-react';
import { percent } from '../helpers';
import { Chip } from '../ui';
import { DecisionButtons } from './PlanGraph';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'review', label: 'Needs review' },
  { id: 'rejected', label: 'Rejected' },
];

const PlanDependencies = ({ model, selection, onDecide, onFocusEdge, onAcceptAll }) => {
  const [filter, setFilter] = useState('all');
  const counts = {
    all: model.edges.length,
    review: model.edges.filter((e) => e.needsReview).length,
    rejected: model.edges.filter((e) => !e.accepted).length,
  };
  const shown = useMemo(() => model.edges.filter((e) => (
    filter === 'all' || (filter === 'review' ? e.needsReview : !e.accepted)
  )), [model.edges, filter]);

  if (model.edges.length === 0) {
    return <p className="text-sm text-slate-400">The planner found no dependencies between tasks, so every task can start right away.</p>;
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="inline-flex gap-1 rounded-xl bg-slate-100 p-1" role="tablist" aria-label="Filter dependencies">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${filter === f.id ? 'bg-white text-blue-600 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
            >
              {f.label} <span className="ml-1 text-slate-400">{counts[f.id]}</span>
            </button>
          ))}
        </div>
        {counts.rejected > 0 && (
          <button type="button" onClick={onAcceptAll} className="ml-auto text-xs font-semibold text-blue-600 hover:underline">Accept all</button>
        )}
      </div>

      {shown.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-400">Nothing in this list.</p>
      ) : (
        <ul className="space-y-2">
          {shown.map((edge) => {
            const from = model.byKey.get(edge.upstream);
            const to = model.byKey.get(edge.downstream);
            const confidence = edge.confidence ?? 1;
            const selected = selection?.type === 'edge' && selection.id === edge.id;
            return (
              <li
                key={edge.id}
                className={`flex gap-3 rounded-xl border bg-white p-3 transition-colors ${selected ? 'border-blue-400 ring-2 ring-blue-100' : 'border-slate-200'} ${edge.accepted ? '' : 'opacity-70'}`}
              >
                <span className={`w-1 shrink-0 rounded-full ${edge.accepted ? (edge.needsReview ? 'bg-amber-400' : 'bg-emerald-500') : 'bg-red-300'}`} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <button type="button" onClick={() => onFocusEdge(edge.id)} className="flex w-full flex-wrap items-center gap-x-2 gap-y-1 text-left text-sm" title="Show in the graph">
                    <GitBranch className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
                    <span className="font-semibold text-slate-900">{edge.upstream}</span>
                    <span className="text-slate-400">→</span>
                    <span className="font-semibold text-slate-900">{edge.downstream}</span>
                    <span className="min-w-0 truncate text-xs text-slate-500">{from?.title} → {to?.title}</span>
                  </button>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <Chip tone={edge.hard ? 'blue' : 'slate'}>{edge.hard ? 'hard' : 'soft'}</Chip>
                    {edge.rule && <Chip tone="violet" title="Rule that proposed this link">{edge.rule}</Chip>}
                    <span className="flex items-center gap-1.5 text-xs text-slate-500">
                      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                        <span className={`block h-full rounded-full ${edge.needsReview ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${Math.round(confidence * 100)}%` }} />
                      </span>
                      {percent(confidence)}
                    </span>
                  </div>
                  {edge.reason && <p className="mt-1.5 text-sm text-slate-600">{edge.reason}</p>}
                  {edge.evidence_quote && (
                    <p className="mt-1 flex gap-1 text-xs italic text-slate-500"><Quote className="mt-0.5 h-3 w-3 shrink-0" /> {edge.evidence_quote}</p>
                  )}
                </div>
                <DecisionButtons compact accepted={edge.accepted} onDecide={(v) => onDecide(edge.id, v)} label={edge.id} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default PlanDependencies;
