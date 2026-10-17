import React, { useState } from 'react';
import {
  LogOut, Send, FileDown, Newspaper, Plus, Activity, Settings2, ChevronDown,
  KanbanSquare, Network, ClipboardList, FileText, Users,
} from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { downloadText, slug, TABS } from './helpers';
import { Spinner } from './ui';

const TAB_ICONS = {
  board: KanbanSquare,
  graph: Network,
  activity: Activity,
  plan: ClipboardList,
  reports: FileText,
  team: Users,
};

const Header = ({
  displayName, onLogout, projects, projectId, onSelectProject, onNewProject, onManageProjects,
  live, summary, onOpenReports, onRefresh, tab, onSelectTab, badge,
}) => {
  const [busy, setBusy] = useState(null);
  const project = projects.find((p) => p.id === projectId);

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
    <header className="bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-700 text-white shadow-lg shadow-blue-900/10 border-b border-blue-500/30 sticky top-0 z-30 transition-all">
      <div className="w-full px-4 sm:px-6 lg:px-8 xl:px-10 py-3 space-y-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
          <div className="mr-auto flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-blue-600 shadow-md shadow-blue-900/20 font-bold ring-2 ring-white/20" aria-hidden="true">
              <Activity className="h-5 w-5" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-extrabold text-white tracking-tight leading-none">Cadence</h1>
                <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-500/40 text-blue-100 border border-blue-400/30">AI</span>
              </div>
              <p className="text-xs text-blue-100/90 font-medium mt-0.5">Signed in as <span className="font-semibold text-white">{displayName}</span></p>
            </div>
          </div>

          {projects.length > 0 && (
            <div className="relative">
              <select
                value={projectId ?? ''}
                onChange={(e) => onSelectProject(Number(e.target.value))}
                aria-label="Project"
                className="appearance-none border border-white/25 rounded-xl pl-3.5 pr-8 py-2 text-sm font-semibold bg-white/10 hover:bg-white/15 text-white backdrop-blur-sm max-w-[15rem] sm:max-w-xs focus:outline-none focus:ring-2 focus:ring-white/40 cursor-pointer transition-all shadow-inner"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id} className="text-slate-900 bg-white font-medium">{p.name}</option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-blue-200 pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" />
            </div>
          )}

          <button
            type="button"
            onClick={onNewProject}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-bold text-blue-700 bg-white hover:bg-blue-50 shadow-sm rounded-xl transition-all hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
          >
            <Plus className="w-4 h-4 text-blue-700 stroke-[2.5]" />
            <span className="hidden sm:inline">New project</span>
          </button>

          {projects.length > 0 && (
            <button
              type="button"
              onClick={onManageProjects}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-semibold text-white bg-white/10 hover:bg-white/20 border border-white/20 backdrop-blur-sm rounded-xl transition-all hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
              title="Manage or delete projects"
              aria-label="Manage projects"
            >
              <Settings2 className="w-4 h-4 text-blue-100" />
              <span className="hidden md:inline">Manage</span>
            </button>
          )}

          <button
            type="button"
            onClick={onLogout}
            className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold text-blue-100 hover:text-white hover:bg-white/10 rounded-xl transition-all ml-auto sm:ml-0"
          >
            <LogOut className="w-4 h-4 text-blue-200" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>

        {projectId && (
          <div className="pt-2 pb-0.5 border-t border-white/15 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
            {tab && onSelectTab && (
              <nav className="overflow-x-auto py-0.5 -mx-1 px-1" aria-label="Dashboard sections">
                <div className="inline-flex items-center gap-2 bg-blue-900/40 border border-white/20 rounded-2xl p-1.5 backdrop-blur-md min-w-max shadow-inner" role="tablist">
                  {TABS.map((t) => {
                    const active = tab === t.id;
                    const b = badge ? badge(t.id) : null;
                    const Icon = TAB_ICONS[t.id];
                    return (
                      <button
                        key={t.id}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => onSelectTab(t.id)}
                        className={`inline-flex items-center justify-center gap-2 px-5 py-2 text-sm font-semibold rounded-xl transition-all duration-150 ${
                          active
                            ? 'bg-white text-blue-700 shadow-md shadow-blue-950/20 font-bold'
                            : 'text-blue-100 hover:text-white hover:bg-white/15'
                        }`}
                      >
                        {Icon && <Icon className={`w-4 h-4 ${active ? 'text-blue-600' : 'text-blue-200'}`} aria-hidden="true" />}
                        <span>{t.label}</span>
                        {b !== null && (
                          <span className={`ml-1.5 text-xs font-bold rounded-full px-2 py-0.5 ${
                            active
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-white/15 text-white border border-white/20'
                          }`}>
                            {b}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </nav>
            )}

            <div className="flex flex-wrap items-center gap-2.5 ml-auto">
              <button
                type="button"
                onClick={checkIn}
                disabled={Boolean(busy)}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 text-xs sm:text-sm font-bold text-blue-700 bg-white hover:bg-blue-50 shadow-sm rounded-xl transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {busy === 'checkin' ? <Spinner className="w-4 h-4 !text-blue-600" /> : <Send className="w-4 h-4 text-blue-600" />} Check in with everyone
              </button>
              <button
                type="button"
                onClick={postDigest}
                disabled={Boolean(busy)}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 text-xs sm:text-sm font-semibold text-white bg-white/15 hover:bg-white/25 border border-white/20 backdrop-blur-sm shadow-xs rounded-xl transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {busy === 'digest' ? <Spinner className="w-4 h-4 !text-white" /> : <Newspaper className="w-4 h-4 text-blue-100" />} Post digest
              </button>
              <button
                type="button"
                onClick={exportDoc}
                disabled={Boolean(busy)}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 text-xs sm:text-sm font-semibold text-white bg-white/15 hover:bg-white/25 border border-white/20 backdrop-blur-sm shadow-xs rounded-xl transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {busy === 'export' ? <Spinner className="w-4 h-4 !text-white" /> : <FileDown className="w-4 h-4 text-blue-100" />} Export
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};

export default Header;
