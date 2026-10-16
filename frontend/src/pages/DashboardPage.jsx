import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useAuthStore } from '../authStore';
import { cadence } from '../api/cadence';
import Header from '../components/dashboard/Header';
import Workspace from '../components/dashboard/Workspace';
import Onboarding from '../components/dashboard/Onboarding';
import NewProjectCard from '../components/dashboard/NewProjectCard';
import { ErrorNote, LoadingBlock, ToastHost } from '../components/dashboard/ui';
import { secondaryButton } from '../components/dashboard/helpers';

const DashboardPage = () => {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showNew, setShowNew] = useState(false);

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

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const project = projects.find((p) => p.id === projectId);

  const headerProps = {
    displayName,
    onLogout: () => logout(true),
    projects,
    projectId,
    onSelectProject: setProjectId,
    onNewProject: () => setShowNew(true),
  };

  const created = async (pid) => {
    setShowNew(false);
    await loadProjects(pid);
  };

  let body;
  if (loading) {
    body = <LoadingBlock label="Loading your projects…" />;
  } else if (error && projects.length === 0) {
    body = (
      <div className="max-w-xl mx-auto px-4 py-10 space-y-3">
        <ErrorNote>{error}</ErrorNote>
        <button type="button" onClick={() => { setLoading(true); loadProjects(); }} className={secondaryButton}>Try again</button>
      </div>
    );
  } else if (!projectId) {
    body = (
      <>
        <Header {...headerProps} live={false} summary={null} onOpenReports={() => {}} onRefresh={() => {}} />
        <Onboarding onCreated={created} />
      </>
    );
  } else {
    body = <Workspace key={projectId} projectId={projectId} project={project} headerProps={headerProps} />;
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      {body}

      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="New project">
          <button type="button" aria-label="Close" onClick={() => setShowNew(false)} className="absolute inset-0 bg-slate-900/30 cursor-default" />
          <div className="relative w-full max-w-md bg-white rounded-2xl border border-slate-200 p-6 shadow-2xl">
            <div className="flex items-start justify-between mb-1">
              <h2 className="text-lg font-bold text-slate-900">New project from a spec</h2>
              <button type="button" onClick={() => setShowNew(false)} aria-label="Close" className="p-1 rounded-lg hover:bg-slate-100 text-slate-500">
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-sm text-slate-500 mb-4">Cadence drafts tasks from the spec. Teammates then join through their Telegram invite links.</p>
            <NewProjectCard onCreated={created} />
          </div>
        </div>
      )}

      <ToastHost />
    </div>
  );
};

export default DashboardPage;
