import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Copy, FolderKanban, Link2, RefreshCw, Search, Unlink, UsersRound,
} from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { copyText, secondaryButton, timeAgo } from './helpers';
import { Chip, Spinner } from './ui';

const POLL_MS = 30_000;

const initials = (name) =>
  String(name || '?').trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || '?';

function joinState(person) {
  if (!person.telegram_chat_id) return { label: 'Not joined', dot: 'bg-slate-300', text: 'text-slate-500' };
  const pausedUntil = person.paused_until ? Date.parse(person.paused_until) : null;
  if (pausedUntil && pausedUntil > Date.now()) return { label: 'Paused', dot: 'bg-amber-400', text: 'text-amber-700' };
  return { label: 'On Telegram', dot: 'bg-emerald-500', text: 'text-emerald-700' };
}

const RosterRow = ({ pid, person, onDone }) => {
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const state = joinState(person);
  const joined = Boolean(person.telegram_chat_id);

  const copy = async () => {
    if (!person.deep_link) return;
    if (await copyText(person.deep_link)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } else {
      toast.error('Could not copy. Open the Team card and copy the link from there.');
    }
  };

  const newLink = async () => {
    const message = joined
      ? `Disconnect ${person.joined_as || 'the Telegram account that joined'} from ${person.name} and make a new invite link? The old link stops working.`
      : `Make a new invite link for ${person.name}? The old link stops working.`;
    if (!window.confirm(message)) return;
    setBusy(true);
    try {
      const fresh = await cadence.resetInvite(pid, person.id);
      const copiedNow = fresh?.deep_link ? await copyText(fresh.deep_link) : false;
      toast.success(
        joined
          ? `${person.name} was unlinked. ${copiedNow ? 'The new invite link is copied.' : 'Send them the new invite link.'}`
          : `New invite link for ${person.name}${copiedNow ? ' copied.' : '.'}`,
      );
      await onDone();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-600"
        >
          {initials(person.name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-semibold text-slate-900">{person.name}</span>
            {person.role === 'lead' && <Chip tone="blue">lead</Chip>}
            {person.username_mismatch && (
              <Chip tone="amber" icon={AlertTriangle} title="The saved Telegram username does not match the account that joined">
                mismatch
              </Chip>
            )}
          </div>
          <p className={`mt-0.5 flex items-center gap-1.5 text-xs ${state.text}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${state.dot}`} aria-hidden="true" />
            {state.label}
            <span className="text-slate-400">
              · {person.open_task_count ?? 0} open task{person.open_task_count === 1 ? '' : 's'}
              {person.last_seen_at && joined ? ` · ${timeAgo(person.last_seen_at)}` : ''}
            </span>
          </p>
          {joined && person.joined_as && (
            <p className="mt-0.5 truncate text-xs text-slate-500" title={person.joined_as}>as {person.joined_as}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {!joined && person.deep_link && (
              <button type="button" onClick={copy} className={`${secondaryButton} !py-1 !px-2.5 text-xs`}>
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'Copied' : 'Copy link'}
              </button>
            )}
            <button type="button" onClick={newLink} disabled={busy} className={`${secondaryButton} !py-1 !px-2.5 text-xs`}>
              {busy ? <Spinner className="h-3.5 w-3.5" /> : joined ? <Unlink className="h-3.5 w-3.5" /> : <Link2 className="h-3.5 w-3.5" />}
              {busy ? 'Working…' : joined ? 'Unlink & new link' : 'New link'}
            </button>
          </div>
        </div>
      </div>
    </li>
  );
};

/**
 * Everyone on every project in one place: who is linked to Telegram where, with unlink / new link
 * next to each person so the lead does not have to open each project to find them.
 * Data for the project that is open comes from the live `people` prop; the others are fetched
 * here and refreshed every 30 s and after every action.
 */
const TeamRoster = ({ projects, currentProjectId, livePeople, onSelectProject, onChangedCurrent, refreshKey }) => {
  const [byProject, setByProject] = useState({});
  const [loading, setLoading] = useState(true);
  const [spinning, setSpinning] = useState(false);
  const [query, setQuery] = useState('');
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [collapsed, setCollapsed] = useState({});

  const load = useCallback(async () => {
    setSpinning(true);
    const results = await Promise.all(
      projects.map(async (p) => {
        try {
          return [p.id, { people: await cadence.listParticipants(p.id) }];
        } catch (err) {
          return [p.id, { error: err.message }];
        }
      }),
    );
    setByProject(Object.fromEntries(results));
    setLoading(false);
    setSpinning(false);
  }, [projects]);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load, refreshKey]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.map((project) => {
      const everyone = project.id === currentProjectId ? livePeople : byProject[project.id]?.people || [];
      const visible = everyone.filter((person) => {
        if (onlyOpen && person.telegram_chat_id) return false;
        if (!needle) return true;
        return [person.name, person.joined_as, person.telegram_username, project.name]
          .some((value) => String(value || '').toLowerCase().includes(needle));
      });
      return {
        project,
        everyone,
        visible,
        joined: everyone.filter((person) => person.telegram_chat_id).length,
        error: project.id === currentProjectId ? null : byProject[project.id]?.error,
      };
    });
  }, [projects, currentProjectId, livePeople, byProject, query, onlyOpen]);

  const totals = groups.reduce(
    (sum, group) => ({ people: sum.people + group.everyone.length, joined: sum.joined + group.joined }),
    { people: 0, joined: 0 },
  );
  const filtering = Boolean(query.trim()) || onlyOpen;

  const afterAction = (pid) => async () => {
    if (pid === currentProjectId) await onChangedCurrent();
    await load();
  };

  return (
    <aside aria-label="Everyone across projects" className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <UsersRound className="h-4 w-4" /> All projects
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              <strong className="text-slate-900">{totals.joined}</strong> of {totals.people} people linked to Telegram
              {projects.length > 1 ? ` across ${projects.length} projects` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            aria-label="Refresh the list"
            title="Refresh"
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <RefreshCw className={`h-4 w-4 ${spinning ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <label className="relative mt-3 block">
          <span className="sr-only">Search people</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, account or project"
            className="w-full rounded-xl border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        </label>
        <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={onlyOpen}
            onChange={(e) => setOnlyOpen(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-300"
          />
          Only people who have not joined
        </label>
      </div>

      <div className="max-h-[calc(100vh-18rem)] overflow-y-auto p-4">
        {loading && <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-500"><Spinner /> Loading…</div>}
        {!loading && filtering && groups.every((g) => g.visible.length === 0) && (
          <p className="py-6 text-center text-sm text-slate-500">No one matches.</p>
        )}
        {!loading && (
          <div className="space-y-5">
            {groups.map(({ project, everyone, visible, joined, error }) => {
              if (filtering && visible.length === 0) return null;
              const isCurrent = project.id === currentProjectId;
              const open = filtering ? true : !(collapsed[project.id] ?? (projects.length > 3 && !isCurrent));
              return (
                <section key={project.id} aria-label={project.name}>
                  <div className="mb-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setCollapsed((prev) => ({ ...prev, [project.id]: open }))}
                      aria-expanded={open}
                      className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg text-left hover:text-blue-700"
                    >
                      {open ? <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />}
                      <FolderKanban className="h-4 w-4 shrink-0 text-slate-400" />
                      <span className="truncate text-sm font-semibold text-slate-900">{project.name}</span>
                    </button>
                    <span className="shrink-0 text-xs text-slate-500">{joined}/{everyone.length} linked</span>
                    {isCurrent ? (
                      <Chip tone="blue">open</Chip>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onSelectProject(project.id)}
                        className="shrink-0 text-xs font-semibold text-blue-600 hover:underline"
                      >
                        Open
                      </button>
                    )}
                  </div>
                  {open && (
                    error ? (
                      <p className="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">Could not load this project: {error}</p>
                    ) : visible.length === 0 ? (
                      <p className="rounded-xl border border-dashed border-slate-200 px-3 py-3 text-center text-xs text-slate-400">No people yet</p>
                    ) : (
                      <ul className="divide-y divide-slate-100 rounded-xl border border-slate-100 p-3">
                        {visible.map((person) => (
                          <RosterRow key={person.id} pid={project.id} person={person} onDone={afterAction(project.id)} />
                        ))}
                      </ul>
                    )
                  )}
                </section>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
};

export default TeamRoster;
