import React from 'react';
import { AlertTriangle, Clock, GitBranch, ListChecks, Route, Users } from 'lucide-react';
import { Panel } from '../ui';
import { initials, ownerStyle } from './planModel';

const Tile = ({ icon: Icon, label, value, note, tone = 'neutral' }) => {
  const tones = {
    neutral: 'border-slate-200 bg-white',
    amber: 'border-amber-200 bg-amber-50/60',
  };
  const iconTones = { neutral: 'bg-blue-50 text-blue-600', amber: 'bg-amber-100 text-amber-700' };
  return (
    <div className={`flex items-center gap-3 rounded-2xl border px-4 py-3 shadow-sm ${tones[tone]}`}>
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${iconTones[tone]}`} aria-hidden="true"><Icon className="h-[18px] w-[18px]" /></span>
      <div className="min-w-0">
        <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <p className="text-xl font-bold leading-tight text-slate-900">{value}</p>
        {note && <p className="truncate text-xs text-slate-500">{note}</p>}
      </div>
    </div>
  );
};

const hoursLabel = (h) => (Number.isInteger(h) ? `${h} h` : `${h.toFixed(1)} h`);

const PlanOverview = ({ model, summary }) => {
  const { totals, workload, criticalPath } = model;
  const busiest = Math.max(1, ...workload.map((w) => (totals.hours > 0 ? w.hours : w.tasks)));
  return (
    <div className="space-y-4">
      {summary && <p className="px-1 text-sm leading-relaxed text-slate-600">{summary}</p>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={ListChecks} label="Tasks" value={totals.tasks} note={`${model.stages.length} stage${model.stages.length === 1 ? '' : 's'} of work`} />
        <Tile
          icon={GitBranch}
          label="Dependencies"
          value={`${totals.accepted}/${model.edges.length}`}
          note={totals.needsReview ? `${totals.needsReview} need${totals.needsReview === 1 ? 's' : ''} your review` : 'accepted'}
          tone={totals.needsReview ? 'amber' : 'neutral'}
        />
        <Tile
          icon={Clock}
          label="Estimated effort"
          value={totals.hours > 0 ? hoursLabel(totals.hours) : 'n/a'}
          note={criticalPath.hours > 0 ? `${hoursLabel(criticalPath.hours)} on the critical path` : 'no estimates in the spec'}
        />
        <Tile
          icon={Users}
          label="People"
          value={totals.people}
          note={totals.unassigned ? `${totals.unassigned} task${totals.unassigned === 1 ? '' : 's'} unassigned` : 'every task has an owner'}
          tone={totals.unassigned ? 'amber' : 'neutral'}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel icon={Users} title="Workload by person">
          <ul className="space-y-2.5">
            {workload.map((row) => {
              const style = ownerStyle(row.name);
              const value = totals.hours > 0 ? row.hours : row.tasks;
              return (
                <li key={row.name || 'unassigned'} className="flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold" style={{ background: style.bg, color: style.fg }} aria-hidden="true">
                    {row.name ? initials(row.name) : '?'}
                  </span>
                  <span className="w-24 shrink-0 truncate text-sm text-slate-700">{row.name || 'Unassigned'}</span>
                  <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <span className="block h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(4, (value / busiest) * 100)}%`, background: row.name ? style.bar : '#fbbf24' }} />
                  </span>
                  <span className="w-20 shrink-0 text-right text-xs tabular-nums text-slate-500">
                    {totals.hours > 0 ? `${hoursLabel(row.hours)} · ` : ''}{row.tasks} task{row.tasks === 1 ? '' : 's'}
                  </span>
                </li>
              );
            })}
          </ul>
          {totals.unassigned > 0 && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-amber-700"><AlertTriangle className="h-3.5 w-3.5" /> Unassigned tasks can be given an owner in the stage cards below.</p>
          )}
        </Panel>

        <Panel icon={Route} title="Critical path">
          {criticalPath.keys.length === 0 ? (
            <p className="text-sm text-slate-500">
              {totals.needsReview > 0 && totals.accepted < model.edges.length
                ? 'Most dependencies are still waiting for your review. Accept the ones that look right and the longest chain of work appears here.'
                : 'No chain of accepted hard dependencies, so every task can start right away.'}
            </p>
          ) : (
            <>
              <ol className="flex flex-wrap items-center gap-1.5">
                {criticalPath.keys.map((key, i) => (
                  <React.Fragment key={key}>
                    <li className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-bold text-rose-800" title={model.byKey.get(key)?.title}>{key}</li>
                    {i < criticalPath.keys.length - 1 && <span className="text-rose-300" aria-hidden="true">→</span>}
                  </React.Fragment>
                ))}
              </ol>
              <p className="mt-3 text-sm text-slate-600">
                {criticalPath.steps} tasks in a row{criticalPath.hours > 0 ? `, about ${hoursLabel(criticalPath.hours)} of work` : ''}. This is the chain that sets the earliest possible finish:
                if any of them slip, the whole plan slips.
              </p>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
};

export default PlanOverview;
