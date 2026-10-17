import React from 'react';
import { Loader2, X, CheckCircle2, AlertTriangle, Info } from 'lucide-react';
import { useToastStore } from '../../hooks/useToastStore';

export const Spinner = ({ className = 'w-5 h-5' }) => (
  <Loader2 className={`${className} animate-spin text-blue-600`} aria-label="Loading" />
);

export const LoadingBlock = ({ label = 'Loading…' }) => (
  <div className="flex items-center justify-center gap-3 py-16 text-sm text-slate-500">
    <Spinner /> {label}
  </div>
);

export const EmptyState = ({ icon: Icon, title, children, action }) => (
  <div className="bg-white border border-dashed border-slate-300 rounded-2xl px-6 py-12 text-center shadow-xs">
    {Icon && (
      <div className="w-12 h-12 rounded-2xl bg-blue-50/70 text-blue-600 ring-1 ring-blue-100 flex items-center justify-center mx-auto mb-3.5">
        <Icon className="w-6 h-6" />
      </div>
    )}
    <p className="text-base font-bold text-slate-800">{title}</p>
    {children && <p className="text-sm text-slate-500 mt-1.5 max-w-md mx-auto leading-relaxed">{children}</p>}
    {action && <div className="mt-5">{action}</div>}
  </div>
);

export const Panel = ({ icon: Icon, title, actions, children, className = '' }) => (
  <section className={`bg-white rounded-2xl border border-slate-200/90 shadow-xs p-5 sm:p-6 transition-all ${className}`}>
    {(title || actions) && (
      <div className="flex items-center justify-between gap-3 mb-3.5">
        <h2 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-500">
          {Icon && <Icon className="w-4 h-4 text-blue-600" />} {title}
        </h2>
        {actions}
      </div>
    )}
    {children}
  </section>
);

const TONES = {
  slate: 'bg-slate-100 text-slate-600 border border-slate-200/60',
  blue: 'bg-blue-50 text-blue-700 border border-blue-200/60',
  green: 'bg-emerald-50 text-emerald-700 border border-emerald-200/60',
  amber: 'bg-amber-50 text-amber-700 border border-amber-200/60',
  orange: 'bg-orange-50 text-orange-700 border border-orange-200/60',
  red: 'bg-red-50 text-red-700 border border-red-200/60',
  violet: 'bg-violet-50 text-violet-700 border border-violet-200/60',
};

export const Chip = ({ tone = 'slate', icon: Icon, children, title, className = '' }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${TONES[tone] || TONES.slate} ${className}`}
  >
    {Icon && <Icon className="w-3 h-3" />} {children}
  </span>
);

export const ErrorNote = ({ children }) =>
  children ? (
    <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-xl px-4 py-2.5">{children}</p>
  ) : null;

const TOAST_STYLE = {
  success: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-800', Icon: CheckCircle2 },
  error: { cls: 'border-red-200 bg-red-50 text-red-800', Icon: AlertTriangle },
  info: { cls: 'border-blue-200 bg-blue-50 text-blue-800', Icon: Info },
};

export const ToastHost = () => {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  return (
    <div
      className="fixed z-[60] bottom-4 right-4 left-4 sm:left-auto sm:w-96 space-y-2 pointer-events-none"
      aria-live="polite"
    >
      {toasts.map((t) => {
        const { cls, Icon } = TOAST_STYLE[t.kind] || TOAST_STYLE.info;
        return (
          <div
            key={t.id}
            role={t.kind === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto flex items-start gap-2.5 border rounded-xl px-4 py-3 text-sm shadow-lg ${cls}`}
          >
            <Icon className="w-4 h-4 mt-0.5 shrink-0" />
            <span className="flex-1 break-words">{t.text}</span>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss" className="opacity-60 hover:opacity-100">
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
