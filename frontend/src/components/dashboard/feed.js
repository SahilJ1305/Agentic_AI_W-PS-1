// Builds the "why did this change" feed: one group per Telegram message, with the
// interpretation, the policy rules that fired, the resulting changes and the bot reply.
import { parseTime } from './helpers';

const WINDOW_MS = 120_000;

function liveToEntry(item) {
  const p = item.payload || {};
  const base = { key: `live-${item.id}`, at: item.at, live: true };
  switch (item.name) {
    case 'message.in':
      return { ...base, kind: 'message_in', who: p.participant, text: p.text };
    case 'message.out':
      return { ...base, kind: 'message_out', who: p.participant, text: p.text, template: p.template_key };
    case 'interpretation':
      return { ...base, kind: 'interpretation', data: p };
    case 'task.updated':
      return {
        ...base,
        kind: 'task',
        taskKey: p.task_key,
        eventType: 'status_changed',
        next: p.status,
        reason: p.reason,
        rule: p.rule_fired,
        flags: p.flags,
        actor: p.rule_fired === 'lead override' ? 'lead' : undefined,
      };
    case 'blocker.raised':
      return { ...base, kind: 'blocker', raised: true, taskKey: p.task_key, text: p.description, blockerKind: p.kind };
    case 'blocker.resolved':
      return { ...base, kind: 'blocker', raised: false, taskKey: p.task_key, text: p.reason || 'Blocker resolved' };
    case 'dependency.changed':
      return {
        ...base,
        kind: 'dependency',
        text: `${p.upstream_key} -> ${p.downstream_key} is now ${p.state}${p.source ? ` (${p.source})` : ''}`,
      };
    case 'report.created':
      return { ...base, kind: 'other', text: `${p.kind} report generated` };
    case 'plan.ready':
      return { ...base, kind: 'other', text: `Plan draft ready (${p.warnings_count ?? 0} warnings)` };
    case 'plan.committed':
      return { ...base, kind: 'other', text: 'Plan committed' };
    default:
      return null;
  }
}

export function buildFeed({ events, messages, live, interps }) {
  const entries = [];

  messages.forEach((m) => {
    const at = parseTime(m.created_at) ?? 0;
    if (m.direction === 'in') {
      entries.push({ key: `m${m.id}`, at, kind: 'message_in', who: m.participant_name, text: m.text });
      const interp = interps[m.id] || m.interpretation;
      if (interp) entries.push({ key: `i${m.id}`, at: at + 1, kind: 'interpretation', data: interp });
    } else {
      entries.push({
        key: `m${m.id}`, at, kind: 'message_out', who: m.participant_name, text: m.text, template: m.template_key,
      });
    }
  });

  events.forEach((e) => {
    entries.push({
      key: `e${e.id}`,
      at: parseTime(e.created_at) ?? 0,
      kind: 'task',
      taskKey: e.task_key,
      taskTitle: e.task_title,
      eventType: e.event_type,
      prev: e.old_value,
      next: e.new_value,
      reason: e.reason,
      actor: e.actor,
      confidence: e.confidence,
    });
  });

  live.forEach((item) => {
    const entry = liveToEntry(item);
    if (entry) entries.push(entry);
  });

  entries.sort((a, b) => a.at - b.at);

  const groups = [];
  let current = null;
  const startGroup = (entry, withIncoming) => {
    current = {
      id: entry.key,
      start: entry.at,
      last: entry.at,
      who: entry.who || null,
      incoming: withIncoming ? entry : null,
      interps: [],
      changes: [],
      replies: [],
    };
    groups.push(current);
  };

  entries.forEach((entry) => {
    if (entry.kind === 'message_in') {
      startGroup(entry, true);
      return;
    }
    const manual = entry.kind === 'task' && entry.actor === 'lead';
    const canAttach = current && !manual && entry.at - current.last <= WINDOW_MS;
    if (!canAttach) startGroup(entry, false);
    current.last = Math.max(current.last, entry.at);
    if (entry.kind === 'interpretation') current.interps.push(entry);
    else if (entry.kind === 'message_out') {
      current.replies.push(entry);
      if (!current.who) current.who = entry.who;
    } else current.changes.push(entry);
    if (manual) current = null;
  });

  return groups.reverse();
}
