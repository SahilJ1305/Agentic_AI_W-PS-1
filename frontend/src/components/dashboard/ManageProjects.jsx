import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, FolderKanban, Lock, Trash2, X } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { dangerButton, secondaryButton, shortDate } from './helpers';
import { Chip, Spinner } from './ui';

const CONFIRM_WORD = 'DELETE';

/**
 * Pick one or more of your projects and delete them for good.
 * Deleting is two steps: choose, then type DELETE. The shared sample project is shown but locked.
 */
const ManageProjects = ({ projects, currentProjectId, onClose, onDeleted }) => {
  const [details, setDetails] = useState({});     // pid -> { tasks, people, joined }
  const [selected, setSelected] = useState(() => new Set());
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(projects.map(async (p) => {
        try {
          const [summary, people] = await Promise.all([cadence.getProject(p.id), cadence.listParticipants(p.id)]);
          return [p.id, {
            tasks: summary.total_tasks ?? 0,
            people: people.length,
            joined: people.filter((x) => x.telegram_chat_id).length,
          }];
        } catch {
          return [p.id, null];
        }
      }));
      if (!cancelled) setDetails(Object.fromEntries(entries));
    })();
    return () => { cancelled = true; };
  }, [projects]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const deletable = useMemo(() => projects.filter((p) => p.owner_user_id), [projects]);
  const chosen = projects.filter((p) => selected.has(p.id));
  const allSelected = deletable.length > 0 && deletable.every((p) => selected.has(p.id));
  const joinedLosing = chosen.reduce((sum, p) => sum + (details[p.id]?.joined ?? 0), 0);

  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const remove = async () => {
    setBusy(true);
    const failed = [];
    let done = 0;
    for (const project of chosen) {
      try {
        await cadence.deleteProject(project.id);
        done += 1;
      } catch (err) {
        failed.push(`${project.name}: ${err.message}`);
      }
    }
    setBusy(false);
    if (done) toast.success(done === 1 ? 'Project deleted.' : `${done} projects deleted.`);
    failed.forEach((message) => toast.error(`Could not delete ${message}`));
    await onDeleted();
    if (failed.length === 0) onClose();
    else { setSelected(new Set()); setConfirming(false); setTyped(''); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Manage projects">
      <button type="button" aria-label="Close" onClick={() => !busy && onClose()} className="absolute inset-0 cursor-default bg-slate-900/30" />
      <div className="relative flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-100 p-5">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Manage projects</h2>
            <p className="mt-0.5 text-sm text-slate-500">{confirming ? 'Last step: this cannot be undone.' : 'Select the projects you want to delete.'}</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="rounded-lg p-1 text-slate-500 hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        {!confirming ? (
          <>
            <div className="overflow-y-auto p-5">
              {deletable.length > 1 && (
                <label className="mb-3 flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(deletable.map((p) => p.id)))}
                    className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-300"
                  />
                  Select all of my projects
                </label>
              )}
              <ul className="space-y-2">
                {projects.map((p) => {
                  const locked = !p.owner_user_id;
                  const info = details[p.id];
                  const checked = selected.has(p.id);
                  return (
                    <li key={p.id}>
                      <label
                        className={`flex items-start gap-3 rounded-xl border p-3 ${
                          locked ? 'cursor-not-allowed border-slate-100 bg-slate-50' : checked ? 'cursor-pointer border-red-300 bg-red-50/50' : 'cursor-pointer border-slate-200 hover:bg-slate-50'
                        }`}
                      >
                        <input
                          type="checkbox"
                          disabled={locked}
                          checked={checked}
                          onChange={() => toggle(p.id)}
                          aria-label={`Select ${p.name}`}
                          className="mt-1 h-4 w-4 rounded border-slate-300 text-red-600 focus:ring-red-300 disabled:opacity-40"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <FolderKanban className="h-4 w-4 shrink-0 text-slate-400" />
                            <span className="truncate text-sm font-semibold text-slate-900">{p.name}</span>
                            {p.id === currentProjectId && <Chip tone="blue">open now</Chip>}
                            {locked && <Chip tone="slate" icon={Lock}>sample, can&apos;t be deleted</Chip>}
                          </span>
                          <span className="mt-0.5 block text-xs text-slate-500">
                            {info === undefined ? 'Loading…' : info === null ? 'Details unavailable' : `${info.tasks} tasks · ${info.joined} of ${info.people} people linked to Telegram`}
                            {p.created_at ? ` · created ${shortDate(p.created_at)}` : ''}
                          </span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              {deletable.length === 0 && <p className="mt-2 text-sm text-slate-500">You have no projects of your own to delete.</p>}
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4">
              <span className="text-sm text-slate-500">{chosen.length ? `${chosen.length} selected` : 'Nothing selected'}</span>
              <div className="flex gap-2">
                <button type="button" onClick={onClose} className={secondaryButton}>Cancel</button>
                <button type="button" disabled={chosen.length === 0} onClick={() => setConfirming(true)} className={dangerButton}>
                  <Trash2 className="h-4 w-4" /> Delete selected{chosen.length ? ` (${chosen.length})` : ''}
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="space-y-3 overflow-y-auto p-5">
              <div className="flex gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>
                  This permanently deletes {chosen.length === 1 ? 'this project' : `these ${chosen.length} projects`} with all tasks, the plan,
                  the activity history, messages and invite links. It cannot be undone.
                  {joinedLosing > 0 && ` ${joinedLosing} ${joinedLosing === 1 ? 'person' : 'people'} linked to Telegram will be disconnected and are not notified.`}
                </p>
              </div>
              <ul className="list-disc pl-5 text-sm text-slate-700">
                {chosen.map((p) => <li key={p.id}><strong>{p.name}</strong></li>)}
              </ul>
              <label className="block text-sm text-slate-600">
                Type <strong className="font-mono text-slate-900">{CONFIRM_WORD}</strong> to confirm
                <input
                  autoFocus
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={CONFIRM_WORD}
                  className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-red-400 focus:outline-none focus:ring-2 focus:ring-red-200"
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-100 p-4">
              <button type="button" disabled={busy} onClick={() => { setConfirming(false); setTyped(''); }} className={secondaryButton}>Back</button>
              <button type="button" disabled={busy || typed.trim() !== CONFIRM_WORD} onClick={remove} className={dangerButton}>
                {busy ? <Spinner className="h-4 w-4 !text-white" /> : <Trash2 className="h-4 w-4" />} {busy ? 'Deleting…' : 'Delete forever'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ManageProjects;
