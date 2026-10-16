import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { LogOut, Send, Upload, Users, Activity, SlidersHorizontal, Radio } from 'lucide-react';
import { useAuthStore } from '../authStore';
import { cadence } from '../api/cadence';

const COLUMNS = [
  { status: 'pending', label: 'Pending', accent: 'border-l-slate-400' },
  { status: 'in_progress', label: 'In progress', accent: 'border-l-blue-600' },
  { status: 'blocked', label: 'Blocked', accent: 'border-l-orange-600' },
  { status: 'complete', label: 'Complete', accent: 'border-l-emerald-600' },
];

const LIVE_EVENTS = [
  'task.updated', 'blocker.raised', 'blocker.resolved',
  'interpretation', 'message.in', 'plan.committed',
];

const Panel = ({ icon: Icon, title, children }) => (
  <section className="bg-white rounded-2xl border border-slate-200 p-5">
    <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500 mb-3">
      <Icon className="w-4 h-4" /> {title}
    </h2>
    {children}
  </section>
);

const TaskCard = ({ task, accent, onAsk }) => (
  <article className={`bg-white border border-slate-200 border-l-4 ${accent} rounded-xl p-3 mb-2`}>
    <div className="text-sm font-semibold text-slate-900">
      {task.key} · {task.owner_name || 'Unassigned'}
    </div>
    <div className="text-sm text-slate-700 mt-0.5">{task.title}</div>
    <div className="text-xs text-slate-500 mt-1.5">
      {task.readiness === 'waiting' ? 'Waiting on an upstream task' : 'Ready'}
    </div>
    {task.blocker && (
      <div className="text-xs text-orange-700 mt-1">Blocker: {task.blocker}</div>
    )}
    {task.status !== 'complete' && task.owner_id && (
      <button
        type="button"
        onClick={() => onAsk(task)}
        className="mt-2 text-xs font-semibold text-blue-600 hover:underline"
      >
        Ask {task.owner_name || 'owner'} on Telegram
      </button>
    )}
  </article>
);

const DashboardPage = () => {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [people, setPeople] = useState([]);
  const [events, setEvents] = useState([]);
  const [live, setLive] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const displayName = user?.full_name || user?.email?.split('@')[0] || 'there';

  const loadProjects = useCallback(async (preferId) => {
    try {
      const list = await cadence.listProjects();
      setProjects(list);
      setProjectId((current) => {
        const wanted = preferId ?? current;
        if (wanted && list.some((p) => p.id === wanted)) return wanted;
        const active = list.find((p) => p.status === 'active') || list[0];
        return active ? active.id : null;
      });
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const [s, t, p, e] = await Promise.all([
        cadence.getProject(projectId),
        cadence.listTasks(projectId),
        cadence.listParticipants(projectId),
        cadence.listEvents(projectId),
      ]);
      setSummary(s);
      setTasks(t);
      setPeople(p);
      setEvents(e);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [projectId]);

  useEffect(() => { loadProjects(); }, [loadProjects]);
  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!projectId) return undefined;
    const source = new EventSource(cadence.streamUrl(projectId));
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    const onChange = () => refresh();
    LIVE_EVENTS.forEach((name) => source.addEventListener(name, onChange));
    return () => source.close();
  }, [projectId, refresh]);

  const flash = (text) => {
    setNotice(text);
    setTimeout(() => setNotice(null), 4000);
  };

  const run = async (action, success) => {
    try {
      const result = await action();
      flash(typeof success === 'function' ? success(result) : success);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const counts = summary?.task_counts || {};
  const project = projects.find((p) => p.id === projectId);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-50">
        <div className="w-10 h-10 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-extrabold text-slate-900">Cadence</h1>
            <p className="text-sm text-slate-500">Signed in as {displayName}</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {projects.length > 0 && (
              <select
                value={projectId ?? ''}
                onChange={(e) => setProjectId(Number(e.target.value))}
                className="border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{p.owner_user_id ? '' : ' (shared demo)'}
                  </option>
                ))}
              </select>
            )}
            {projectId && (
              <span className={`flex items-center gap-1.5 text-xs font-medium ${live ? 'text-emerald-600' : 'text-slate-400'}`}>
                <Radio className="w-3.5 h-3.5" /> {live ? 'Live' : 'Reconnecting'}
              </span>
            )}
            {projectId && (
              <button
                type="button"
                onClick={() => run(
                  () => cadence.checkIn(projectId),
                  (r) => `Check-in queued for ${r.tasks_targeted} task(s).`,
                )}
                className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl"
              >
                <Send className="w-4 h-4" /> Check in with everyone
              </button>
            )}
            <button
              type="button"
              onClick={() => logout(true)}
              className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-xl"
            >
              <LogOut className="w-4 h-4" /> Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6 space-y-4">
        {error && (
          <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-4 py-2.5">{error}</p>
        )}
        {notice && (
          <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-xl px-4 py-2.5">{notice}</p>
        )}

        {!projectId ? (
          <div className="max-w-xl mx-auto bg-white border border-slate-200 rounded-2xl p-8">
            <h2 className="text-lg font-bold text-slate-900">Start your first project</h2>
            <p className="text-sm text-slate-500 mt-1 mb-5">
              Upload a project spec. Cadence stores the original, creates the tasks, and gives each teammate a Telegram invite link.
            </p>
            <NewProjectForm onCreated={(pid, message) => { flash(message); loadProjects(pid); }} onError={setError} />
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-500">
              {project?.name}: {summary?.total_tasks ?? 0} tasks · {counts.complete || 0} complete · {counts.blocked || 0} blocked · {summary?.open_blockers ?? 0} open blockers
            </p>
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
              <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                {COLUMNS.map((column) => {
                  const columnTasks = tasks.filter((t) => t.status === column.status);
                  return (
                    <div key={column.status}>
                      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
                        {column.label} ({columnTasks.length})
                      </h2>
                      {columnTasks.map((task) => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          accent={column.accent}
                          onAsk={(t) => run(() => cadence.followUp(t.id), `Follow-up queued for ${t.owner_name}.`)}
                        />
                      ))}
                    </div>
                  );
                })}
              </section>

              <aside className="space-y-4">
                <Panel icon={Users} title="Team">
                  <ul className="space-y-3">
                    {people.map((person) => (
                      <li key={person.id} className="text-sm">
                        <span className="font-semibold text-slate-900">{person.name}</span>
                        <span className="text-slate-500"> · {person.role} · {person.telegram_chat_id ? 'on Telegram' : 'not joined'}</span>
                        {!person.telegram_chat_id && person.deep_link && (
                          <a href={person.deep_link} target="_blank" rel="noreferrer" className="block text-xs text-blue-600 break-all hover:underline">
                            {person.deep_link}
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                </Panel>

                <Panel icon={Activity} title="Activity">
                  <ul className="space-y-2.5 max-h-80 overflow-y-auto">
                    {events.length === 0 && <li className="text-sm text-slate-400">No changes yet.</li>}
                    {events.slice(0, 30).map((event) => (
                      <li key={event.id} className="text-sm">
                        <span className="font-semibold text-slate-900">{event.task_key}</span>{' '}
                        {event.event_type.replace('_', ' ')}{' '}
                        {event.old_value ? `${event.old_value} → ` : ''}{event.new_value}
                        {event.reason && <div className="text-xs text-slate-500">{event.reason}</div>}
                      </li>
                    ))}
                  </ul>
                </Panel>

                <Panel icon={SlidersHorizontal} title="Lead override">
                  <OverrideForm
                    tasks={tasks}
                    people={people}
                    onSave={(task, changes) => run(
                      () => cadence.overrideTask(task.id, { ...changes, expected_version: task.version }),
                      'Saved. The owner is told if they are on Telegram.',
                    )}
                  />
                </Panel>

                <Panel icon={Upload} title="New project from a spec">
                  <NewProjectForm onCreated={(pid, message) => { flash(message); loadProjects(pid); }} onError={setError} />
                </Panel>
              </aside>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const inputClass = 'w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white';

const OverrideForm = ({ tasks, people, onSave }) => {
  const [taskId, setTaskId] = useState('');
  const [status, setStatus] = useState('');
  const [ownerId, setOwnerId] = useState('');
  const [reason, setReason] = useState('');

  const selected = useMemo(
    () => tasks.find((t) => String(t.id) === taskId) || tasks[0],
    [tasks, taskId],
  );

  useEffect(() => {
    if (selected) setStatus(selected.status);
  }, [selected]);

  if (!selected) return <p className="text-sm text-slate-400">No tasks yet.</p>;

  const submit = (e) => {
    e.preventDefault();
    onSave(selected, {
      status,
      owner_id: ownerId ? Number(ownerId) : null,
      reason,
    });
    setReason('');
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <select value={String(selected.id)} onChange={(e) => setTaskId(e.target.value)} className={inputClass}>
        {tasks.map((t) => <option key={t.id} value={t.id}>{t.key} · {t.title}</option>)}
      </select>
      <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputClass}>
        {COLUMNS.map((c) => <option key={c.status} value={c.status}>{c.label}</option>)}
      </select>
      <select value={ownerId} onChange={(e) => setOwnerId(e.target.value)} className={inputClass}>
        <option value="">Keep owner</option>
        {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (shown in the activity feed)"
        required
        className={inputClass}
      />
      <button type="submit" className="w-full py-2 text-sm font-semibold text-white bg-slate-900 hover:bg-slate-800 rounded-xl">
        Save override
      </button>
    </form>
  );
};

const NewProjectForm = ({ onCreated, onError }) => {
  const [name, setName] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) {
      onError('Choose a Markdown spec first.');
      return;
    }
    setBusy(true);
    try {
      const project = await cadence.createProject(name.trim() || file.name.replace(/\.[^.]+$/, ''));
      const result = await cadence.uploadSpec(project.id, file);
      const imported = result.imported?.tasks;
      onCreated(
        project.id,
        imported
          ? `Created ${project.name} with ${imported} tasks.`
          : `Created ${project.name}. The planner is building tasks from the spec.`,
      );
      setName('');
      setFile(null);
      e.target.reset();
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name" className={inputClass} />
      <input
        type="file"
        accept=".md,.markdown,.txt"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="w-full text-sm text-slate-600"
      />
      <button
        type="submit"
        disabled={busy}
        className="w-full py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl disabled:opacity-60"
      >
        {busy ? 'Creating…' : 'Create project'}
      </button>
    </form>
  );
};

export default DashboardPage;
