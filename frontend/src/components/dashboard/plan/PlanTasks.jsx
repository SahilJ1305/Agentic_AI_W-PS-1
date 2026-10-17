import React from 'react';
import { ArrowRight, Crosshair, Hourglass, Rocket } from 'lucide-react';
import { inputClass, percent, shortDate } from '../helpers';
import { Chip } from '../ui';
import { initials, ownerStyle } from './planModel';

const stageTitle = (index, count) => {
  if (index === 0) return { title: 'Stage 1', note: 'Can start right away', icon: Rocket };
  return { title: `Stage ${index + 1}`, note: count ? 'Starts once the tasks it waits for are done' : '', icon: Hourglass };
};

const TaskCard = ({ task, model, people, owners, setOwners, selected, onFocus }) => {
  const current = owners[task.key] ?? task.owner_name ?? '';
  const nameKnown = !current || people.some((p) => p.name === current);
  const style = ownerStyle(current);
  const waits = model.waitsFor(task.key);
  const unlocks = model.unlocks(task.key);
  const onPath = model.criticalPath.keys.includes(task.key);

  return (
    <li className={`flex flex-col rounded-2xl border bg-white p-4 shadow-sm transition-shadow hover:shadow-md ${selected ? 'border-blue-400 ring-2 ring-blue-200' : 'border-slate-200'}`}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 rounded-lg px-2 py-1 text-xs font-bold" style={{ background: style.bg, color: style.fg }}>{task.key}</span>
        <div className="min-w-0 flex-1">
          <button type="button" onClick={() => onFocus(task.key)} className="group flex w-full items-start gap-1.5 text-left" title="Show in the graph">
            <span className="text-sm font-semibold text-slate-900 group-hover:text-blue-700">{task.title}</span>
            <Crosshair className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300 group-hover:text-blue-500" aria-hidden="true" />
          </button>
          {task.description && <p className="mt-1 line-clamp-2 text-xs text-slate-500">{task.description}</p>}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {task.estimate_hours != null && <Chip tone="slate">{task.estimate_hours} h</Chip>}
        {task.deadline && <Chip tone="slate">due {shortDate(task.deadline)}</Chip>}
        {task.requires_evidence && <Chip tone="amber">needs evidence</Chip>}
        {onPath && <Chip tone="red">critical path</Chip>}
        {task.owner_name && percent(task.owner_confidence) && task.owner_confidence < 1 && (
          <Chip tone="slate" title="How sure the planner is about the owner">owner {percent(task.owner_confidence)}</Chip>
        )}
      </div>

      {(waits.length > 0 || unlocks.length > 0) && (
        <div className="mt-3 space-y-1 text-xs text-slate-500">
          {waits.length > 0 && (
            <p className="flex flex-wrap items-center gap-1"><Hourglass className="h-3 w-3" /> Waits for
              {waits.map((k) => <button key={k} type="button" onClick={() => onFocus(k)} className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-700 hover:bg-blue-50 hover:text-blue-700">{k}</button>)}
            </p>
          )}
          {unlocks.length > 0 && (
            <p className="flex flex-wrap items-center gap-1"><ArrowRight className="h-3 w-3" /> Unlocks
              {unlocks.map((k) => <button key={k} type="button" onClick={() => onFocus(k)} className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-700 hover:bg-blue-50 hover:text-blue-700">{k}</button>)}
            </p>
          )}
        </div>
      )}

      <div className="mt-auto flex items-center gap-2 pt-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold" style={{ background: style.bg, color: style.fg }} aria-hidden="true">
          {current ? initials(current) : '?'}
        </span>
        <select
          value={current}
          onChange={(e) => setOwners((prev) => ({ ...prev, [task.key]: e.target.value }))}
          className={`${inputClass} !py-1.5`}
          aria-label={`Owner of ${task.key}`}
        >
          <option value="">Unassigned</option>
          {!nameKnown && <option value={current}>{current} (not on the team)</option>}
          {people.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
        </select>
      </div>
    </li>
  );
};

const PlanTasks = ({ model, people, owners, setOwners, selection, onFocus, onGoToTeam }) => (
  <div className="space-y-5">
    {people.length === 0 && (
      <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
        No teammates yet, so owners cannot be changed. <button type="button" className="font-semibold underline" onClick={onGoToTeam}>Add teammates</button>.
      </p>
    )}
    {model.stages.map((tasks, index) => {
      if (tasks.length === 0) return null;
      const { title, note, icon: Icon } = stageTitle(index, index > 0);
      return (
        <section key={index} aria-label={title}>
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><Icon className="h-4 w-4" /></span>
            <h3 className="text-sm font-bold text-slate-900">{title}</h3>
            <span className="text-xs text-slate-500">{note} · {tasks.length} task{tasks.length === 1 ? '' : 's'}</span>
            <span className="h-px flex-1 bg-slate-200" aria-hidden="true" />
          </div>
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {tasks.map((task) => (
              <TaskCard
                key={task.key}
                task={task}
                model={model}
                people={people}
                owners={owners}
                setOwners={setOwners}
                selected={selection?.type === 'node' && selection.id === task.key}
                onFocus={onFocus}
              />
            ))}
          </ul>
        </section>
      );
    })}
  </div>
);

export default PlanTasks;
