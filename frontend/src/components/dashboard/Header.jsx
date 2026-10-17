import React, { useEffect, useState } from 'react';
import { LogOut, Send, Radio, Bot, FileDown, Newspaper, Plus, Activity } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { downloadText, primaryButton, secondaryButton, slug } from './helpers';
import { Spinner } from './ui';

const HEALTH_POLL_MS = 30_000;

const BotChip = () => {
  const [health, setHealth] = useState(undefined); // undefined = loading, null = unreachable

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const result = await cadence.health();
      if (!cancelled) setHealth(result);
    };
    poll();
    const timer = setInterval(poll, HEALTH_POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  let tone = 'bg-slate-100 text-slate-500';
  let label = 'Bot: checking…';
  let title = 'Checking the Telegram bot status';
  if (health === null) {
    tone = 'bg-red-50 text-red-700';
    label = 'API unreachable';
    title = 'The Cadence API did not answer /health';
  } else if (health) {
    // Older servers return the string "polling"; newer ones {status, username}.
    const telegram = typeof health.telegram === 'string' ? { status: health.telegram } : health.telegram || {};
    const handle = telegram.username ? `@${telegram.username.replace(/^@/, '')}` : 'Telegram bot';
    if (telegram.status === 'polling') {
      tone = 'bg-emerald-50 text-emerald-700';
      label = `${handle} online`;
      title = 'The bot is polling Telegram';
    } else if (telegram.status === 'conflict') {
      tone = 'bg-amber-50 text-amber-700';
      label = 'Bot conflict';
      title = 'another copy of the bot is running with the same token';
    } else {
      label = 'Bot disabled';
      title = 'The Telegram bot is not running (no token configured)';
    }
  }

  return (
    <span title={title} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
      <Bot className="w-3.5 h-3.5" /> {label}
    </span>
  );
};

const Header = ({
  displayName, onLogout, projects, projectId, onSelectProject, onNewProject,
  live, summary, onOpenReports, onRefresh,
}) => {
  const [busy, setBusy] = useState(null);
  const project = projects.find((p) => p.id === projectId);
  const complete = summary?.progress?.complete ?? summary?.task_counts?.complete ?? 0;
  const total = summary?.progress?.total ?? summary?.total_tasks ?? 0;
  const pct = total ? Math.round((complete / total) * 100) : 0;

  const run = async (name, action) => {
    setBusy(name);
    try {
      await action();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  };

  const checkIn = () => run('checkin', async () => {
    const result = await cadence.checkIn(projectId);
    toast.success(`Check-in queued for ${result.tasks_targeted ?? 0} task(s).`);
    await onRefresh();
  });

  const postDigest = () => run('digest', async () => {
    const result = await cadence.generateReport(projectId, 'digest', true);
    toast.success(result.posted ? 'Digest posted to Telegram.' : 'Digest generated, but it could not be posted to Telegram.');
    onOpenReports();
  });

  const exportDoc = () => run('export', async () => {
    const text = await cadence.exportMarkdown(projectId);
    downloadText(`${slug(project?.name)}-status.md`, text);
    toast.success('Exported the living task doc.');
    onOpenReports();
  });

  return (
    <header className="bg-white/95 backdrop-blur border-b border-slate-200 shadow-sm sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="mr-auto flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm" aria-hidden="true">
              <Activity className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-xl font-extrabold text-slate-900 leading-tight">Cadence</h1>
              <p className="text-xs text-slate-500">Signed in as {displayName}</p>
            </div>
          </div>

          {projects.length > 0 && (
            <select
              value={projectId ?? ''}
              onChange={(e) => onSelectProject(Number(e.target.value))}
              aria-label="Project"
              className="border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white max-w-[14rem] sm:max-w-xs"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}{p.owner_user_id ? '' : ' (shared demo)'}</option>
              ))}
            </select>
          )}
          <button type="button" onClick={onNewProject} className={`${secondaryButton} !px-3`}>
            <Plus className="w-4 h-4" /> <span className="hidden sm:inline">New project</span>
          </button>

          {projectId && (
            <span
              className={`flex items-center gap-1.5 text-xs font-medium ${live ? 'text-emerald-600' : 'text-amber-600'}`}
              role="status"
            >
              <Radio className={`w-3.5 h-3.5 ${live ? '' : 'animate-pulse'}`} /> {live ? 'Live' : 'Reconnecting…'}
            </span>
          )}
          <BotChip />
          <button type="button" onClick={onLogout} className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-xl">
            <LogOut className="w-4 h-4" /> <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>

        {projectId && (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div className="flex-1 min-w-[12rem]">
              <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>{project?.name}</span>
                <span className="font-semibold text-slate-700">{complete} of {total} tasks complete</span>
              </div>
              <div
                className="h-2 rounded-full bg-slate-100 overflow-hidden"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={complete}
                aria-label="Project progress"
              >
                <div className="h-full bg-gradient-to-r from-emerald-400 to-emerald-500 transition-all duration-500" style={{ width: `${pct}%` }} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={checkIn} disabled={Boolean(busy)} className={primaryButton}>
                {busy === 'checkin' ? <Spinner className="w-4 h-4 !text-white" /> : <Send className="w-4 h-4" />} Check in with everyone
              </button>
              <button type="button" onClick={postDigest} disabled={Boolean(busy)} className={secondaryButton}>
                {busy === 'digest' ? <Spinner className="w-4 h-4" /> : <Newspaper className="w-4 h-4" />} Post digest
              </button>
              <button type="button" onClick={exportDoc} disabled={Boolean(busy)} className={secondaryButton}>
                {busy === 'export' ? <Spinner className="w-4 h-4" /> : <FileDown className="w-4 h-4" />} Export
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};

export default Header;
