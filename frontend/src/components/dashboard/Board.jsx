import React, { useState } from 'react';
import {
  AlertTriangle, BadgeCheck, CalendarClock, Flag, Hourglass, KanbanSquare, ShieldQuestion, Zap, Link2,
} from 'lucide-react';
import { STATUSES, isUrl, shortDate, timeAgo, humanize, secondaryButton } from './helpers';
import { Chip, EmptyState, Panel } from './ui';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';

const FLAG_TONE = {
  at_risk: 'red',
  stale: 'slate',
  dependency_conflict: 'orange',
  upstream_reopened: 'amber',
};

const RiskDot = ({ risk }) => {
  if (!risk) return null;
  const high = risk.level === 'high';
  return (
    <span
      title={`${high ? 'High' : 'Medium'} risk: ${risk.why}`}
      className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${high ? 'bg-red-500' : 'bg-amber-400'}`}
      role="img"
      aria-label={`${risk.level} risk: ${risk.why}`}
    />
  );
};

export const TaskCard = ({ task, accent, flashing, onOpen }) => {
  const flags = (task.flags || []).filter((f) => f !== 'needs_verification');
  const unverified = (task.flags || []).includes('needs_verification');
  const evidence = task.completion_evidence;
  const waitingOn = task.waiting_on || [];
  const showWaiting = task.status !== 'complete' && task.readiness === 'waiting';
  const due = task.eta || task.deadline;

  return (
    <article
      className={`bg-white border border-slate-200 border-l-4 ${accent} rounded-xl mb-2 transition-shadow hover:shadow-md ${flashing ? 'cadence-flash' : ''}`}
    >
      <button type="button" onClick={() => onOpen(task.id)} className="block w-full text-left p-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-300">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <span>{task.key}</span>
          <span className="text-slate-300">·</span>
          <span className={`truncate ${task.owner_name ? '' : 'text-slate-400 font-medium'}`}>{task.owner_name || 'Unassigned'}</span>
          <span className="ml-auto flex items-center gap-1.5 shrink-0">
            {task.on_critical_path && (
              <span title="On the critical path" className="text-rose-600"><Flag className="w-3.5 h-3.5" /></span>
            )}
            <RiskDot risk={task.risk} />
          </span>
        </div>
        <div className="text-sm text-slate-700 mt-0.5">{task.title}</div>

        {showWaiting && (
          <div className="mt-1.5 flex items-center gap-1 text-xs text-slate-500">
            <Hourglass className="w-3 h-3" />
            {waitingOn.length ? `Waiting on ${waitingOn.join(', ')}` : 'Waiting on an upstream task'}
          </div>
        )}
        {!showWaiting && task.status !== 'complete' && (
          <div className="mt-1.5 text-xs text-emerald-700">Ready to start</div>
        )}

        {task.blocker && (
          <div className="mt-1.5 text-xs text-orange-700 flex gap-1">
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> <span>Blocker: {task.blocker}</span>
          </div>
        )}

        {(flags.length > 0 || unverified || task.verified) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {unverified && <Chip tone="amber" icon={ShieldQuestion} title="Marked complete without the required evidence">unverified</Chip>}
            {task.verified && !unverified && (
              <Chip tone="green" icon={BadgeCheck} title="Completion verified">verified</Chip>
            )}
            {flags.map((flag) => (
              <Chip key={flag} tone={FLAG_TONE[flag] || 'slate'}>{humanize(flag)}</Chip>
            ))}
          </div>
        )}

        {due && (
          <div className="mt-2 flex items-center gap-1 text-xs text-slate-500">
            <CalendarClock className="w-3 h-3" />
            {task.eta ? `ETA ${shortDate(task.eta)}` : ''}
            {task.eta && task.deadline ? ' · ' : ''}
            {task.deadline ? `due ${shortDate(task.deadline)}` : ''}
          </div>
        )}

        {task.last_update?.text && (
          <blockquote className="mt-2 border-l-2 border-slate-200 pl-2 text-xs italic text-slate-500 line-clamp-3">
            “{task.last_update.text}”
            {task.last_update.at && <span className="not-italic text-slate-400"> · {timeAgo(task.last_update.at)}</span>}
          </blockquote>
        )}
      </button>

      {evidence && (
        <div className="px-3 pb-3 -mt-1 text-xs flex items-center gap-1 text-emerald-700">
          <BadgeCheck className="w-3 h-3" />
          {isUrl(evidence) ? (
            <a href={evidence.trim()} target="_blank" rel="noreferrer" className="underline truncate hover:text-emerald-900">
              {evidence.trim().replace(/^https?:\/\//, '')}
            </a>
          ) : (
            <span className="truncate" title={evidence}>{evidence}</span>
          )}
        </div>
      )}
    </article>
  );
};

const OpenBlockers = ({ blockers, onOpen, onChanged }) => {
  const [busy, setBusy] = useState(null);
  if (!blockers.length) return null;

  const resolve = async (blocker) => {
    setBusy(blocker.id);
    try {
      await cadence.resolveBlocker(blocker.id, 'Resolved from the dashboard');
      toast.success(`Blocker on ${blocker.task_key} resolved.`);
      await onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel icon={AlertTriangle} title={`Open blockers (${blockers.length})`}>
      <ul className="divide-y divide-slate-100">
        {blockers.map((b) => (
          <li key={b.id} className="py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <button type="button" onClick={() => b.task_id && onOpen(b.task_id)} className="font-semibold text-slate-900 hover:text-blue-600">
              {b.task_key}
            </button>
            <span className="text-slate-700 flex-1 min-w-[12rem]">
              {b.description}
              <span className="text-slate-400 text-xs">
                {b.owner_name ? ` · ${b.owner_name}` : ''}
                {b.kind ? ` · ${b.kind}` : ''}
                {b.linked_task_key ? ` · waits for ${b.linked_task_key}` : ''}
                {b.escalation_level > 0 ? ` · escalation ${b.escalation_level}` : ''}
              </span>
            </span>
            <button type="button" disabled={busy === b.id} onClick={() => resolve(b)} className={`${secondaryButton} !py-1 !px-3 text-xs`}>
              {busy === b.id ? 'Resolving…' : 'Resolve'}
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
};

const Board = ({ tasks, blockers, flashing, onOpen, onChanged, onGoToPlan }) => {
  if (tasks.length === 0) {
    return (
      <EmptyState
        icon={KanbanSquare}
        title="No tasks yet"
        action={<button type="button" onClick={onGoToPlan} className={secondaryButton}><Zap className="w-4 h-4" /> Open plan review</button>}
      >
        If you uploaded a spec, the planner is turning it into a draft. Review and commit it in the Plan tab and the tasks appear here.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4">
      <OpenBlockers blockers={blockers} onOpen={onOpen} onChanged={onChanged} />
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {STATUSES.map((column) => {
          const columnTasks = tasks.filter((t) => t.status === column.status);
          return (
            <div key={column.status} className="min-w-0">
              <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
                {column.label}
                <span className="rounded-full bg-slate-200 text-slate-600 px-1.5 text-[11px]">{columnTasks.length}</span>
              </h2>
              {columnTasks.length === 0 && (
                <p className="text-xs text-slate-400 border border-dashed border-slate-200 rounded-xl p-3 text-center">Nothing here</p>
              )}
              {columnTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  accent={column.accent}
                  flashing={Boolean(flashing[task.key])}
                  onOpen={onOpen}
                />
              ))}
            </div>
          );
        })}
      </section>
      <p className="text-xs text-slate-400 flex items-center gap-1.5">
        <Link2 className="w-3 h-3" /> Click a card to see its timeline, dependencies and override controls.
      </p>
    </div>
  );
};

export default Board;
