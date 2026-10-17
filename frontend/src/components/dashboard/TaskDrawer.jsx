import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  X, Send, Undo2, ArrowRight, MessageSquare, GitBranch, AlertTriangle, SlidersHorizontal, History, BadgeCheck, Check,
} from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import {
  STATUSES, inputClass, primaryButton, secondaryButton, darkButton, statusMeta, timeAgo, shortDate, isUrl, humanize, percent,
} from './helpers';
import { Chip, ErrorNote, Spinner } from './ui';

const Section = ({ icon: Icon, title, children }) => (
  <section className="border-t border-slate-100 pt-4">
    <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
      <Icon className="w-4 h-4" /> {title}
    </h3>
    {children}
  </section>
);

const StatusChip = ({ status }) => {
  const meta = statusMeta(status);
  return (
    <span
      className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ background: meta.fill, color: meta.text }}
    >
      {meta.label}
    </span>
  );
};

const EventRow = ({ event, onRevert, busy }) => {
  const reverted = Boolean(event.reverted_by_event_id);
  const canRevert = !reverted && event.event_type !== 'reverted';
  const statusLike = STATUSES.some((s) => s.status === event.new_value);
  return (
    <li className={`relative pl-5 pb-4 border-l border-slate-200 ml-1.5 ${reverted ? 'opacity-60' : ''}`}>
      <span className="absolute -left-[5px] top-1 w-2.5 h-2.5 rounded-full bg-blue-500 ring-4 ring-white" />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <span className="font-semibold text-slate-900">{humanize(event.event_type)}</span>
        {(event.old_value || event.new_value) && (
          <span className="flex items-center gap-1 text-slate-700">
            {statusLike ? <StatusChip status={event.old_value} /> : <span className="text-slate-500 break-all">{event.old_value || '—'}</span>}
            <ArrowRight className="w-3 h-3 text-slate-400" />
            {statusLike ? <StatusChip status={event.new_value} /> : <span className="break-all">{event.new_value || '—'}</span>}
          </span>
        )}
        {reverted && <Chip tone="slate">reverted</Chip>}
      </div>
      <div className="text-xs text-slate-500 mt-0.5">
        {event.actor || 'system'} · {timeAgo(event.created_at)}
        {percent(event.confidence) ? ` · confidence ${percent(event.confidence)}` : ''}
      </div>
      {event.reason && <div className="text-sm text-slate-700 mt-1">{event.reason}</div>}
      {event.source_message_text && (
        <blockquote className="mt-1 border-l-2 border-blue-200 pl-2 text-xs italic text-slate-500">
          “{event.source_message_text}”
        </blockquote>
      )}
      {canRevert && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onRevert(event)}
          className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-red-600 disabled:opacity-50"
        >
          <Undo2 className="w-3 h-3" /> Revert
        </button>
      )}
    </li>
  );
};

const BlockerRow = ({ blocker, onResolved }) => {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await cadence.resolveBlocker(blocker.id, reason.trim() || 'Resolved from the dashboard');
      toast.success(`Blocker resolved.${res?.owner_notified ? ' The owner was told on Telegram.' : ''}`);
      setOpen(false);
      await onResolved();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="bg-orange-50 border border-orange-100 rounded-xl p-3 text-sm">
      <div className="flex items-start gap-2">
        <span className="flex-1 text-orange-900">
          {blocker.description}
          <span className="text-xs text-orange-700/70">
            {blocker.kind ? ` · ${blocker.kind}` : ''}{blocker.escalation_level > 0 ? ` · escalation ${blocker.escalation_level}` : ''}
          </span>
        </span>
        {!open && (
          <button type="button" onClick={() => setOpen(true)} className="text-xs font-semibold text-orange-800 hover:underline shrink-0">
            Resolve
          </button>
        )}
      </div>
      {open && (
        <form onSubmit={submit} className="mt-2 flex gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="How was it resolved?"
            className={inputClass}
            autoFocus
          />
          <button type="submit" disabled={busy} className={`${darkButton} shrink-0`}>
            {busy ? '…' : <Check className="w-4 h-4" />}
          </button>
        </form>
      )}
    </li>
  );
};

const OverrideForm = ({ task, people, conflict, onSaved, onConflict, onClearConflict }) => {
  const [status, setStatus] = useState(task.status);
  const [ownerId, setOwnerId] = useState(task.owner_id ? String(task.owner_id) : '');
  const [deadline, setDeadline] = useState(task.deadline ? String(task.deadline).slice(0, 10) : '');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!reason.trim()) return;
    setBusy(true);
    onClearConflict();
    const changes = { reason: reason.trim(), expected_version: task.version };
    if (status !== task.status) changes.status = status;
    if (ownerId && Number(ownerId) !== task.owner_id) changes.owner_id = Number(ownerId);
    if (deadline && deadline !== String(task.deadline || '').slice(0, 10)) changes.deadline = deadline;
    try {
      await cadence.overrideTask(task.id, changes);
      toast.success('Override saved. The owner is told if they are on Telegram.');
      setReason('');
      await onSaved();
    } catch (err) {
      if (err.status === 409) {
        await onConflict();
      } else {
        toast.error(err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      {conflict && (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
          This task was changed by someone else (or by a Telegram reply) while you were editing. The latest version
          has been reloaded. Check it and save again.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-slate-500">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={`${inputClass} mt-1`}>
            {STATUSES.map((s) => <option key={s.status} value={s.status}>{s.label}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Owner
          <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} className={`${inputClass} mt-1`}>
            <option value="">{task.owner_id ? 'Keep owner' : 'Unassigned'}</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      </div>
      <label className="block text-xs text-slate-500">
        Deadline
        <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} className={`${inputClass} mt-1`} />
      </label>
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (required, shown in the activity feed)"
        required
        className={inputClass}
      />
      <button type="submit" disabled={busy || !reason.trim()} className={`${darkButton} w-full`}>
        {busy ? 'Saving…' : 'Save override'}
      </button>
      <p className="text-[11px] text-slate-400">Saving as version {task.version}. A mismatch means someone else changed it first.</p>
    </form>
  );
};

const TaskDrawer = ({ taskId, tasks, people, dataTick, onClose, onOpenTask, onChanged }) => {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loadedId, setLoadedId] = useState(null);
  const [conflict, setConflict] = useState(false);

  const fetchDetail = useCallback(async () => {
    try {
      const result = await cadence.getTask(taskId);
      setDetail(result);
      setLoadedId(taskId);
      setError(null);
    } catch (err) {
      setError(err.message);
      setLoadedId(taskId);
    }
  }, [taskId]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail, dataTick]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const tasksById = useMemo(() => Object.fromEntries(tasks.map((t) => [t.id, t])), [tasks]);
  const ready = detail && loadedId === taskId && detail.task?.id === taskId;
  const task = ready ? detail.task : tasks.find((t) => t.id === taskId);
  // Prefer the richer list item (owner_name, flags, ...) for display, detail for the version.
  const listItem = tasks.find((t) => t.id === taskId);
  const shown = { ...listItem, ...(ready ? detail.task : {}) };
  const events = useMemo(
    () => (ready ? [...(detail.events || [])].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)) || b.id - a.id) : []),
    [detail, ready],
  );

  const refreshAll = async () => {
    await fetchDetail();
    await onChanged();
  };

  const act = async (fn, success) => {
    setBusy(true);
    try {
      await fn();
      if (success) toast.success(success);
      await refreshAll();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  const depKey = (dep, side) => {
    const direct = side === 'up' ? dep.upstream_key : dep.downstream_key;
    if (direct) return direct;
    return tasksById[side === 'up' ? dep.upstream_task_id : dep.downstream_task_id]?.key || '?';
  };
  const depTaskId = (dep, side) => (side === 'up' ? dep.upstream_task_id : dep.downstream_task_id);

  // upstream_deps: edges this task waits for (show their upstream task); downstream_deps: edges that wait on this task.
  const waitsFor = ready ? detail.upstream_deps || [] : [];
  const unblocks = ready ? detail.downstream_deps || [] : [];
  const messages = ready ? detail.messages || [] : [];
  const blockers = ready ? detail.blockers || [] : [];

  const renderDeps = (deps, side, empty) => (
    deps.length === 0 ? <p className="text-sm text-slate-400">{empty}</p> : (
      <ul className="space-y-1">
        {deps.map((dep) => {
          const id = depTaskId(dep, side);
          const other = tasksById[id];
          return (
            <li key={dep.id}>
              <button type="button" onClick={() => id && onOpenTask(id)} className="w-full text-left flex items-center gap-2 text-sm rounded-lg px-2 py-1.5 hover:bg-slate-50">
                <span className="font-semibold text-slate-900">{depKey(dep, side)}</span>
                <span className="text-slate-600 truncate flex-1">{other?.title}</span>
                {other && <StatusChip status={other.status} />}
                <Chip tone={dep.type === 'hard' ? 'blue' : 'slate'}>{dep.type || 'hard'}</Chip>
              </button>
            </li>
          );
        })}
      </ul>
    )
  );

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={`Task ${shown.key || ''}`}>
      <button type="button" aria-label="Close panel" onClick={onClose} className="absolute inset-0 bg-slate-900/30 cursor-default" />
      <aside className="relative w-full sm:max-w-lg bg-white h-full overflow-y-auto shadow-2xl">
        <header className="sticky top-0 z-10 bg-white border-b border-slate-200 px-5 py-4 flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-extrabold text-slate-900">{shown.key}</span>
              {shown.status && <StatusChip status={shown.status} />}
              {shown.readiness && <Chip tone={shown.readiness === 'waiting' ? 'amber' : 'green'}>{shown.readiness}</Chip>}
              {Boolean(shown.on_critical_path) && <Chip tone="red">critical path</Chip>}
            </div>
            <p className="text-sm text-slate-700 mt-0.5">{shown.title}</p>
            <p className="text-xs text-slate-500 mt-0.5">
              {shown.owner_name || 'Unassigned'}
              {shown.deadline ? ` · due ${shortDate(shown.deadline)}` : ''}
              {shown.eta ? ` · ETA ${shortDate(shown.eta)}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="px-5 py-4 space-y-5">
          {error && <ErrorNote>{error}</ErrorNote>}
          {!ready && !error && (
            <div className="flex items-center gap-3 text-sm text-slate-500 py-6"><Spinner /> Loading task…</div>
          )}

          {task && (
            <>
              {shown.progress_note && <p className="text-sm text-slate-600">{shown.progress_note}</p>}
              {shown.completion_evidence && (
                <p className="text-sm flex items-center gap-1.5 text-emerald-700">
                  <BadgeCheck className="w-4 h-4" /> Evidence:{' '}
                  {isUrl(shown.completion_evidence) ? (
                    <a href={shown.completion_evidence.trim()} target="_blank" rel="noreferrer" className="underline break-all">{shown.completion_evidence}</a>
                  ) : shown.completion_evidence}
                </p>
              )}
              {shown.risk && (
                <p className={`text-sm rounded-xl px-3 py-2 ${shown.risk.level === 'high' ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-800'}`}>
                  <strong className="capitalize">{shown.risk.level} risk:</strong> {shown.risk.why}
                </p>
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy || !shown.owner_id || shown.status === 'complete'}
                  onClick={() => act(() => cadence.followUp(taskId), `Follow-up sent to ${shown.owner_name}.`)}
                  className={primaryButton}
                  title={!shown.owner_id ? 'Assign an owner first' : undefined}
                >
                  <Send className="w-4 h-4" /> Ask {shown.owner_name || 'owner'} on Telegram
                </button>
              </div>

              <Section icon={AlertTriangle} title={`Open blockers (${blockers.length})`}>
                {blockers.length === 0 ? <p className="text-sm text-slate-400">No open blockers.</p> : (
                  <ul className="space-y-2">
                    {blockers.map((b) => <BlockerRow key={b.id} blocker={b} onResolved={refreshAll} />)}
                  </ul>
                )}
              </Section>

              <Section icon={GitBranch} title="Dependencies">
                <p className="text-xs text-slate-500 mb-1">Waits for</p>
                {renderDeps(waitsFor, 'up', 'Nothing upstream.')}
                <p className="text-xs text-slate-500 mt-3 mb-1">Unblocks</p>
                {renderDeps(unblocks, 'down', 'Nothing downstream.')}
              </Section>

              <Section icon={History} title="Timeline">
                {!ready ? null : events.length === 0 ? (
                  <p className="text-sm text-slate-400">No events recorded yet.</p>
                ) : (
                  <ul>
                    {events.map((event) => (
                      <EventRow
                        key={event.id}
                        event={event}
                        busy={busy}
                        onRevert={(ev) => {
                          if (!window.confirm(`Revert "${humanize(ev.event_type)}" (${ev.old_value ?? '—'} ← ${ev.new_value ?? '—'})?`)) return;
                          act(() => cadence.revertEvent(taskId, ev.id), 'Change reverted.');
                        }}
                      />
                    ))}
                  </ul>
                )}
              </Section>

              <Section icon={MessageSquare} title="Conversation">
                {messages.length === 0 ? <p className="text-sm text-slate-400">No messages about this task yet.</p> : (
                  <ul className="space-y-2">
                    {messages.slice(0, 12).map((m) => (
                      <li key={m.id} className={`flex ${m.direction === 'out' ? 'justify-end' : ''}`}>
                        <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.direction === 'out' ? 'bg-blue-50 text-blue-900' : 'bg-slate-100 text-slate-800'}`}>
                          <div className="whitespace-pre-wrap break-words">{m.text}</div>
                          <div className="text-[10px] text-slate-400 mt-0.5">
                            {m.direction === 'out' ? 'Cadence' : 'Teammate'} · {timeAgo(m.created_at)}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              {ready && (
                <Section icon={SlidersHorizontal} title="Lead override">
                  <OverrideForm
                    key={`${detail.task.id}-${detail.task.version}`}
                    task={detail.task}
                    people={people}
                    conflict={conflict}
                    onSaved={refreshAll}
                    onClearConflict={() => setConflict(false)}
                    onConflict={async () => { setConflict(true); await refreshAll(); }}
                  />
                </Section>
              )}
            </>
          )}

          {!task && error && (
            <button type="button" onClick={fetchDetail} className={secondaryButton}>Try again</button>
          )}
        </div>
      </aside>
    </div>
  );
};

export default TaskDrawer;
