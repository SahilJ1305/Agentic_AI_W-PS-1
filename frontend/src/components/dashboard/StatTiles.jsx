import React from 'react';
import { AlertTriangle, CheckCircle2, Loader, ShieldAlert } from 'lucide-react';

const TONES = {
  neutral: { box: 'border-slate-200/90 bg-white hover:border-slate-300', icon: 'bg-slate-50 text-slate-600 ring-1 ring-slate-150', value: 'text-slate-900' },
  blue: { box: 'border-slate-200/90 bg-white hover:border-blue-200', icon: 'bg-blue-50 text-blue-600 ring-1 ring-blue-100', value: 'text-slate-900' },
  green: { box: 'border-slate-200/90 bg-white hover:border-emerald-200', icon: 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100', value: 'text-slate-900' },
  orange: { box: 'border-orange-200/80 bg-white hover:border-orange-300', icon: 'bg-orange-50 text-orange-600 ring-1 ring-orange-200', value: 'text-orange-700' },
  red: { box: 'border-red-200/80 bg-white hover:border-red-300', icon: 'bg-red-50 text-red-600 ring-1 ring-red-200', value: 'text-red-700' },
};

const Tile = ({ icon: Icon, label, value, note, tone = 'neutral' }) => {
  const t = TONES[tone] || TONES.neutral;
  return (
    <div className={`flex items-center gap-3.5 rounded-2xl border px-4 py-3.5 shadow-xs transition-all duration-200 hover:shadow-sm ${t.box}`}>
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${t.icon}`} aria-hidden="true">
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
        <p className={`text-2xl font-extrabold tracking-tight leading-tight ${t.value}`}>{value}</p>
        {note && <p className="truncate text-xs text-slate-500 font-medium">{note}</p>}
      </div>
    </div>
  );
};

/** The four numbers a lead looks at first, from the project summary. */
const StatTiles = ({ summary, counts }) => {
  const total = summary?.total_tasks ?? 0;
  const blocked = counts.blocked || 0;
  const openBlockers = summary?.open_blockers ?? 0;
  const risks = summary?.risks?.length ?? 0;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile icon={CheckCircle2} tone="green" label="Complete" value={`${counts.complete || 0}/${total}`} note="tasks done" />
      <Tile icon={Loader} tone="blue" label="In progress" value={counts.in_progress || 0} note="being worked on" />
      <Tile
        icon={AlertTriangle}
        tone={blocked ? 'orange' : 'neutral'}
        label="Blocked"
        value={blocked}
        note={`${openBlockers} open blocker${openBlockers === 1 ? '' : 's'}`}
      />
      <Tile
        icon={ShieldAlert}
        tone={risks ? 'red' : 'neutral'}
        label="At risk"
        value={risks}
        note={risks ? 'see the Reports tab' : 'nothing flagged'}
      />
    </div>
  );
};

export default StatTiles;
