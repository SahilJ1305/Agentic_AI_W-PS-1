import React, { useMemo } from 'react';
import {
  Activity, MessageCircle, Brain, Scale, GitCommit, Bot, AlertTriangle, CheckCircle2, Link2, Info,
} from 'lucide-react';
import { buildFeed } from './feed';
import { clockTime, humanize, percent, statusMeta, timeAgo } from './helpers';
import { Chip, EmptyState } from './ui';

const Step = ({ icon: Icon, label, tone = 'text-slate-400', children }) => (
  <div className="flex gap-3">
    <div className="flex flex-col items-center">
      <span className={`mt-0.5 ${tone}`}><Icon className="w-4 h-4" /></span>
    </div>
    <div className="flex-1 min-w-0 pb-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-0.5">{label}</div>
      {children}
    </div>
  </div>
);

const StatusPill = ({ status }) => {
  if (!status) return null;
  const meta = statusMeta(status);
  return (
    <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: meta.fill, color: meta.text }}>
      {meta.label}
    </span>
  );
};

// Policy rule lines look like "R4: complete+blocker -> forced to blocked"; highlight the rule id.
const DecisionLine = ({ line }) => {
  const text = typeof line === 'string' ? line : JSON.stringify(line);
  const match = text.match(/^\s*(R\d+[a-z]?)\s*[:-]\s*(.*)$/i);
  return (
    <li className="flex gap-2 text-sm">
      {match ? (
        <>
          <span className="font-mono text-xs font-bold bg-violet-50 text-violet-700 rounded px-1.5 py-0.5 h-fit">{match[1].toUpperCase()}</span>
          <span className="text-slate-700">{match[2]}</span>
        </>
      ) : (
        <span className="text-slate-700">{text}</span>
      )}
    </li>
  );
};

const UpdateLine = ({ update }) => {
  if (typeof update === 'string') return <li className="text-sm text-slate-700">{update}</li>;
  const key = update.task_key || update.task || update.key;
  const status = update.status || update.new_status;
  const conf = percent(update.confidence);
  const note = update.progress_note || update.note || update.evidence || update.blocker;
  return (
    <li className="text-sm text-slate-700 flex flex-wrap items-center gap-x-2 gap-y-1">
      {key && <span className="font-semibold text-slate-900">{key}</span>}
      {status && <StatusPill status={status} />}
      {conf && <Chip tone="slate" title="Interpreter confidence">{conf}</Chip>}
      {update.blocker && <Chip tone="orange">blocker</Chip>}
      {note && typeof note === 'string' && <span className="text-xs text-slate-500">{note}</span>}
    </li>
  );
};

const Interpretation = ({ data }) => {
  const updates = Array.isArray(data.updates) ? data.updates : [];
  const decisions = Array.isArray(data.decision) ? data.decision : data.decision ? [data.decision] : [];
  const gitChecks = data.git_checks;
  return (
    <>
      <Step icon={Brain} label="Understood" tone="text-blue-500">
        <div className="flex flex-wrap items-center gap-2">
          {data.intent && <Chip tone="blue">{humanize(data.intent)}</Chip>}
          {updates.length === 0 && <span className="text-sm text-slate-400">No task updates extracted.</span>}
        </div>
        {updates.length > 0 && <ul className="mt-1 space-y-1">{updates.map((u, i) => <UpdateLine key={i} update={u} />)}</ul>}
      </Step>
      {decisions.length > 0 && (
        <Step icon={Scale} label="Policy rules fired" tone="text-violet-500">
          <ul className="space-y-1">{decisions.map((d, i) => <DecisionLine key={i} line={d} />)}</ul>
        </Step>
      )}
      {gitChecks && (Array.isArray(gitChecks) ? gitChecks.length > 0 : true) && (
        <Step icon={GitCommit} label="Git check" tone="text-slate-500">
          {(Array.isArray(gitChecks) ? gitChecks : [gitChecks]).map((g, i) => (
            <p key={i} className="text-sm text-slate-700">{typeof g === 'string' ? g : (g.summary || g.result || JSON.stringify(g))}</p>
          ))}
        </Step>
      )}
    </>
  );
};

const Change = ({ change }) => {
  switch (change.kind) {
    case 'task':
      return (
        <li className="text-sm text-slate-700">
          <span className="font-semibold text-slate-900">{change.taskKey}</span>{' '}
          <span className="text-slate-500">{humanize(change.eventType)}</span>{' '}
          {change.prev && <><StatusPill status={change.prev} /><span className="text-slate-400"> → </span></>}
          {change.next ? <StatusPill status={change.next} /> : null}
          {change.actor === 'lead' && <Chip tone="slate" className="ml-1.5">lead override</Chip>}
          {change.rule && change.rule !== 'lead override' && <Chip tone="violet" className="ml-1.5">{change.rule}</Chip>}
          {change.reason && <div className="text-xs text-slate-500 mt-0.5">{change.reason}</div>}
        </li>
      );
    case 'blocker':
      return (
        <li className="text-sm text-slate-700 flex gap-1.5">
          {change.raised ? <AlertTriangle className="w-4 h-4 text-orange-500 shrink-0" /> : <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />}
          <span>
            <span className="font-semibold text-slate-900">{change.taskKey}</span>{' '}
            {change.raised ? 'blocker raised' : 'blocker resolved'}{change.text ? `: ${change.text}` : ''}
          </span>
        </li>
      );
    case 'dependency':
      return <li className="text-sm text-slate-700 flex gap-1.5"><Link2 className="w-4 h-4 text-violet-500 shrink-0" /> {change.text}</li>;
    default:
      return <li className="text-sm text-slate-500 flex gap-1.5"><Info className="w-4 h-4 shrink-0" /> {change.text}</li>;
  }
};

const Group = ({ group }) => {
  const when = group.start;
  return (
    <article className="bg-white border border-slate-200 rounded-2xl p-4">
      <header className="flex items-center justify-between gap-2 mb-2 text-xs text-slate-400">
        <span className="font-semibold text-slate-600">
          {group.incoming ? `Message from ${group.incoming.who || 'a teammate'}` : group.changes[0]?.actor === 'lead' ? 'Lead action' : 'System'}
        </span>
        <span title={new Date(when).toLocaleString()}>{clockTime(when)} · {timeAgo(when)}</span>
      </header>

      {group.incoming && (
        <Step icon={MessageCircle} label="Heard" tone="text-emerald-500">
          <blockquote className="bg-slate-50 border border-slate-100 rounded-xl px-3 py-2 text-sm text-slate-800 whitespace-pre-wrap break-words">
            “{group.incoming.text}”
          </blockquote>
        </Step>
      )}

      {group.interps.map((entry) => <Interpretation key={entry.key} data={entry.data} />)}

      {group.changes.length > 0 && (
        <Step icon={GitCommit} label="Changed" tone="text-blue-600">
          <ul className="space-y-1.5">
            {group.changes.map((c) => <Change key={c.key} change={c} />)}
          </ul>
        </Step>
      )}

      {group.replies.map((reply) => (
        <Step key={reply.key} icon={Bot} label={`Cadence replied${reply.who ? ` to ${reply.who}` : ''}`} tone="text-blue-500">
          <div className="bg-blue-50 text-blue-900 rounded-xl px-3 py-2 text-sm whitespace-pre-wrap break-words">
            {reply.text}
            {reply.template && <div className="text-[10px] text-blue-400 mt-1 font-mono">{reply.template}</div>}
          </div>
        </Step>
      ))}
    </article>
  );
};

const ActivityFeed = ({ events, messages, liveEntries, interps, loading }) => {
  const groups = useMemo(
    () => buildFeed({ events, messages, live: liveEntries, interps }),
    [events, messages, liveEntries, interps],
  );

  if (!loading && groups.length === 0) {
    return (
      <EmptyState icon={Activity} title="No activity yet">
        When a teammate replies to the bot, you will see the message, how it was interpreted, the policy rules that fired
        and the resulting change here, live.
      </EmptyState>
    );
  }

  return (
    <div className="w-full space-y-3">
      <p className="text-sm text-slate-500">
        Each card is one Telegram message: what was said, how Cadence understood it, which rules decided the outcome, and what changed.
      </p>
      {groups.slice(0, 80).map((group) => <Group key={group.id} group={group} />)}
    </div>
  );
};

export default ActivityFeed;
