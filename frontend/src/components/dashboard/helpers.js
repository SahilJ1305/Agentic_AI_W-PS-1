// Shared constants and pure helpers for the dashboard (no React components here).

export const STATUSES = [
  { status: 'pending', label: 'Pending', accent: 'border-l-slate-400', fill: '#e2e8f0', stroke: '#64748b', text: '#334155' },
  { status: 'in_progress', label: 'In progress', accent: 'border-l-blue-600', fill: '#dbeafe', stroke: '#2563eb', text: '#1e3a8a' },
  { status: 'blocked', label: 'Blocked', accent: 'border-l-orange-600', fill: '#ffedd5', stroke: '#ea580c', text: '#7c2d12' },
  { status: 'complete', label: 'Complete', accent: 'border-l-emerald-600', fill: '#d1fae5', stroke: '#059669', text: '#064e3b' },
];

export const statusMeta = (status) => STATUSES.find((s) => s.status === status) || STATUSES[0];

export const inputClass =
  'w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-500';

export const primaryButton =
  'inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-sm rounded-xl transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-1 disabled:opacity-60 disabled:cursor-not-allowed';

export const secondaryButton =
  'inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold text-slate-700 bg-white border border-slate-300 hover:bg-slate-50 rounded-xl transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-1 disabled:opacity-60 disabled:cursor-not-allowed';

export const darkButton =
  'inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-slate-900 hover:bg-slate-800 rounded-xl transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 focus-visible:ring-offset-1 disabled:opacity-60 disabled:cursor-not-allowed';

export const TABS = [
  { id: 'board', label: 'Board' },
  { id: 'graph', label: 'Graph' },
  { id: 'activity', label: 'Activity' },
  { id: 'plan', label: 'Plan' },
  { id: 'reports', label: 'Reports' },
  { id: 'team', label: 'Team' },
];

// SQLite CURRENT_TIMESTAMP values have no timezone ("YYYY-MM-DD HH:MM:SS"); treat them as UTC.
export function parseTime(value) {
  if (!value) return null;
  if (typeof value === 'number') return value;
  let text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)) text = text.replace(' ', 'T');
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)) text += 'Z';
  const ms = Date.parse(text);
  return Number.isNaN(ms) ? null : ms;
}

export function timeAgo(value) {
  const ms = parseTime(value);
  if (ms === null) return '';
  const diff = Math.max(0, Date.now() - ms) / 1000;
  if (diff < 45) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export function clockTime(value) {
  const ms = parseTime(value);
  if (ms === null) return '';
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function shortDate(value) {
  if (!value) return '';
  const ms = parseTime(value);
  if (ms === null) return String(value);
  return new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export const isUrl = (text) => typeof text === 'string' && /^https?:\/\/\S+$/i.test(text.trim());

export const humanize = (text) => String(text ?? '').replace(/_/g, ' ');

export const percent = (value) =>
  typeof value === 'number' ? `${Math.round(value <= 1 ? value * 100 : value)}%` : null;

export function downloadText(filename, text, type = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export const slug = (text) => String(text || 'project').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
