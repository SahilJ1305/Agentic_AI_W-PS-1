import React from 'react';
import { AlertTriangle, CheckCircle2, Loader, ShieldAlert } from 'lucide-react';

const TONES = {
  neutral: { box: 'border-slate-200 bg-white', icon: 'bg-slate-100 text-slate-500', value: 'text-slate-900' },
  blue: { box: 'border-slate-200 bg-white', icon: 'bg-blue-50 text-blue-600', value: 'text-slate-900' },
  green: { box: 'border-slate-200 bg-white', icon: 'bg-emerald-50 text-emerald-600', value: 'text-slate-900' },
  orange: { box: 'border-orange-200 bg-orange-50/60', icon: 'bg-orange-100 text-orange-600', value: 'text-orange-700' },
  red: { box: 'border-red-200 bg-red-50/60', icon: 'bg-red-100 text-red-600', value: 'text-red-700' },
};

const Tile = ({ icon: Icon, label, value, note, tone = 'neutral' }) => {
  const t = TONES[tone];
  return (
    <div className={`flex items-center gap-3 rounded-2xl border px-4 py-3 shadow-sm ${t.box}`}>
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${t.icon}`} aria-hidden="true">
        <Icon className="h-[18px] w-[18px]" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        <p className={`text-xl font-bold leading-tight ${t.value}`}>{value}</p>
        {note && <p className="truncate text-xs text-slate-500">{note}</p>}
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
