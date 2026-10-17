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
  <div className="bg-white border border-dashed border-slate-300 rounded-2xl px-6 py-10 text-center">
    {Icon && <Icon className="w-8 h-8 text-slate-300 mx-auto mb-3" />}
    <p className="text-sm font-semibold text-slate-700">{title}</p>
    {children && <p className="text-sm text-slate-500 mt-1 max-w-md mx-auto">{children}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const Panel = ({ icon: Icon, title, actions, children, className = '' }) => (
  <section className={`bg-white rounded-2xl border border-slate-200 shadow-sm p-5 ${className}`}>
    {(title || actions) && (
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {Icon && <Icon className="w-4 h-4" />} {title}
        </h2>
        {actions}
      </div>
    )}
    {children}
  </section>
);

const TONES = {
  slate: 'bg-slate-100 text-slate-600',
  blue: 'bg-blue-50 text-blue-700',
  green: 'bg-emerald-50 text-emerald-700',
  amber: 'bg-amber-50 text-amber-700',
  orange: 'bg-orange-50 text-orange-700',
  red: 'bg-red-50 text-red-700',
  violet: 'bg-violet-50 text-violet-700',
};

export const Chip = ({ tone = 'slate', icon: Icon, children, title, className = '' }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONES[tone]} ${className}`}
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
