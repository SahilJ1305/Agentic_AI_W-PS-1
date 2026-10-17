import React, { useState } from 'react';
import StatTiles from './StatTiles';
import { useProjectData } from '../../hooks/useProjectData';
import Header from './Header';
import Board from './Board';
import DependencyGraph from './DependencyGraph';
import ActivityFeed from './ActivityFeed';
import PlanReview from './PlanReview';
import MeetingUpdate from './MeetingUpdate';
import Reports from './Reports';
import Team from './Team';
import TaskDrawer from './TaskDrawer';
import { ErrorNote, LoadingBlock } from './ui';

/** Everything that belongs to one project. Mounted with key={projectId} so state resets on switch. */
const Workspace = ({ projectId, project, headerProps }) => {
  const data = useProjectData(projectId);
  const [tab, setTab] = useState('board');
  const [openTaskId, setOpenTaskId] = useState(null);

  const { summary, tasks, people, blockers } = data;
  const counts = summary?.task_counts || {};
  const openByKey = (key) => {
    const task = tasks.find((t) => t.key === key);
    if (task) setOpenTaskId(task.id);
  };

  const badge = (id) => {
    if (id === 'board') return tasks.length || null;
    if (id === 'team') return people.length || null;
    if (id === 'plan' && data.planSignal?.type === 'ready' && tab !== 'plan') return '•';
    return null;
  };

  return (
    <>
      <Header
        {...headerProps}
        projectId={projectId}
        live={data.live}
        summary={summary}
        onRefresh={data.refresh}
        onOpenReports={() => setTab('reports')}
        tab={tab}
        onSelectTab={setTab}
        badge={badge}
      />

      <div className="w-full px-4 sm:px-6 lg:px-8 xl:px-10 py-5 space-y-4">

        {data.error && (
          <div className="flex items-center gap-3">
            <div className="flex-1"><ErrorNote>{data.error}</ErrorNote></div>
            <button type="button" onClick={data.refresh} className="text-sm font-semibold text-blue-600 hover:underline">Retry</button>
          </div>
        )}

        {tab === 'board' && <StatTiles summary={summary} counts={counts} />}

        {data.loading ? (
          <LoadingBlock label="Loading project…" />
        ) : (
          <>
            {tab === 'board' && (
              <div className="cadence-enter"><Board
                tasks={tasks}
                blockers={blockers}
                flashing={data.flashing}
                onOpen={setOpenTaskId}
                onChanged={data.refresh}
                onGoToPlan={() => setTab('plan')}
              /></div>
            )}
            {tab === 'graph' && (
              <div className="cadence-enter">
                <DependencyGraph pid={projectId} graph={data.graph} onOpenTask={setOpenTaskId} onChanged={data.refresh} />
              </div>
            )}
            {tab === 'activity' && (
              <div className="cadence-enter"><ActivityFeed
                events={data.events}
                messages={data.messages}
                liveEntries={data.liveEntries}
                interps={data.interps}
                loading={data.loading}
              /></div>
            )}
            {/* Always mounted so an in-flight plan and an unsaved draft survive tab switches. */}
            <div hidden={tab !== 'plan'} className="space-y-4">
              <MeetingUpdate pid={projectId} onApplied={data.refresh} />
              <PlanReview
                pid={projectId}
                people={people}
                planSignal={data.planSignal}
                onCommitted={async () => { await data.refresh(); setTab('board'); }}
                onGoToTeam={() => setTab('team')}
              />
            </div>
            {tab === 'reports' && (
              <div className="cadence-enter"><Reports
                pid={projectId}
                projectName={project?.name}
                risks={summary?.risks || []}
                reportTick={data.reportTick}
                onOpenTaskByKey={openByKey}
              /></div>
            )}
            {tab === 'team' && (
              <div className="cadence-enter"><Team
                pid={projectId}
                people={people}
                gitCheck={summary?.git_check}
                onChanged={data.refresh}
                projects={headerProps.projects}
                onSelectProject={headerProps.onSelectProject}
                refreshKey={data.dataTick}
              /></div>
            )}
          </>
        )}
      </div>

      {openTaskId !== null && (
        <TaskDrawer
          key={openTaskId}
          taskId={openTaskId}
          tasks={tasks}
          people={people}
          dataTick={data.dataTick}
          onClose={() => setOpenTaskId(null)}
          onOpenTask={setOpenTaskId}
          onChanged={data.refresh}
        />
      )}
    </>
  );
};

export default Workspace;
