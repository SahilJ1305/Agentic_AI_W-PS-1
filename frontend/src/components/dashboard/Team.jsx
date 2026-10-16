import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Users, Copy, QrCode, Github, UserPlus, Check, PauseCircle, Send } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { copyText, inputClass, secondaryButton, darkButton, timeAgo } from './helpers';
import { Chip, EmptyState, Panel } from './ui';

function telegramState(person) {
  if (!person.telegram_chat_id) return { label: 'Not joined', tone: 'slate' };
  const pausedUntil = person.paused_until ? Date.parse(person.paused_until) : null;
  if (pausedUntil && pausedUntil > Date.now()) return { label: 'Paused', tone: 'amber' };
  return { label: 'On Telegram', tone: 'green' };
}

const GithubField = ({ pid, person, onChanged }) => {
  const [value, setValue] = useState(person.github_username || '');
  const [busy, setBusy] = useState(false);
  const dirty = value.trim().replace(/^@/, '') !== (person.github_username || '');

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await cadence.updateParticipant(pid, person.id, { github_username: value.trim().replace(/^@/, '') || null });
      toast.success(`GitHub username saved for ${person.name}.`);
      await onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="flex items-center gap-2">
      <Github className="w-4 h-4 text-slate-400 shrink-0" />
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="GitHub username"
        aria-label={`GitHub username for ${person.name}`}
        className={`${inputClass} !py-1.5`}
      />
      <button type="submit" disabled={!dirty || busy} className={`${secondaryButton} !py-1.5 shrink-0`}>
        {busy ? '…' : 'Save'}
      </button>
    </form>
  );
};

const InviteBlock = ({ person }) => {
  const [showQr, setShowQr] = useState(false);
  const [copied, setCopied] = useState(false);
  if (!person.deep_link) return null;

  const copy = async () => {
    const ok = await copyText(person.deep_link);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } else {
      toast.error('Could not copy. Select the link and copy it manually.');
    }
  };

  return (
    <div className="mt-3 rounded-xl bg-slate-50 border border-slate-100 p-3">
      <div className="flex items-center gap-2">
        <a href={person.deep_link} target="_blank" rel="noreferrer" className="flex-1 min-w-0 text-xs text-blue-600 hover:underline truncate" title={person.deep_link}>
          {person.deep_link}
        </a>
        <button type="button" onClick={copy} className={`${secondaryButton} !py-1 !px-2.5 text-xs shrink-0`}>
          {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          onClick={() => setShowQr((v) => !v)}
          aria-expanded={showQr}
          className={`${secondaryButton} !py-1 !px-2.5 text-xs shrink-0`}
        >
          <QrCode className="w-3.5 h-3.5" /> QR
        </button>
      </div>
      {showQr && (
        <div className="mt-3 flex flex-col items-center gap-2">
          <div className="bg-white p-3 rounded-xl border border-slate-200">
            <QRCodeSVG value={person.deep_link} size={160} />
          </div>
          <p className="text-xs text-slate-500">Scan with a phone camera to open Telegram.</p>
        </div>
      )}
    </div>
  );
};

const MemberCard = ({ pid, person, onChanged }) => {
  const state = telegramState(person);
  const skills = (person.skills || '').split(',').map((s) => s.trim()).filter(Boolean);
  const joined = Boolean(person.telegram_chat_id);
  return (
    <article className="bg-white border border-slate-200 rounded-2xl p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-slate-900">{person.name}</h3>
        <Chip tone={person.role === 'lead' ? 'blue' : 'slate'}>{person.role}</Chip>
        <Chip tone={state.tone} icon={state.label === 'Paused' ? PauseCircle : state.label === 'On Telegram' ? Send : undefined}>{state.label}</Chip>
        {person.paused_until && state.label === 'Paused' && (
          <span className="text-xs text-slate-400">until {new Date(person.paused_until).toLocaleString()}</span>
        )}
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {person.open_task_count ?? 0} open task{person.open_task_count === 1 ? '' : 's'}
        {person.task_count != null ? ` of ${person.task_count}` : ''}
        {person.telegram_username ? ` · @${person.telegram_username}` : ''}
        {person.last_seen_at ? ` · seen ${timeAgo(person.last_seen_at)}` : ''}
      </p>
      {skills.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {skills.map((skill) => <Chip key={skill}>{skill}</Chip>)}
        </div>
      )}
      <div className="mt-3">
        <GithubField key={person.github_username || ''} pid={pid} person={person} onChanged={onChanged} />
        <p className="text-[11px] text-slate-400 mt-1">Used to check “done” claims against this person&apos;s commits.</p>
      </div>
      {!joined && <InviteBlock person={person} />}
      {joined && person.deep_link && (
        <details className="mt-3 text-xs text-slate-500">
          <summary className="cursor-pointer hover:text-slate-700">Invite link</summary>
          <InviteBlock person={person} />
        </details>
      )}
    </article>
  );
};

const AddTeammate = ({ pid, onChanged }) => {
  const empty = { name: '', role: 'member', skills: '', telegram_username: '', github_username: '' };
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      const person = await cadence.addParticipant(pid, {
        name: form.name.trim(),
        role: form.role,
        skills: form.skills.trim() || null,
        telegram_username: form.telegram_username.trim().replace(/^@/, '') || null,
        github_username: form.github_username.trim().replace(/^@/, '') || null,
      });
      toast.success(`${person?.name || form.name} added. Send them their invite link below.`);
      setForm(empty);
      await onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel icon={UserPlus} title="Add teammate">
      <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <input value={form.name} onChange={set('name')} placeholder="Name" required className={inputClass} aria-label="Name" />
        <select value={form.role} onChange={set('role')} className={inputClass} aria-label="Role">
          <option value="member">Member</option>
          <option value="lead">Lead</option>
        </select>
        <input value={form.skills} onChange={set('skills')} placeholder="Skills (comma separated)" className={`${inputClass} sm:col-span-2`} aria-label="Skills" />
        <input value={form.telegram_username} onChange={set('telegram_username')} placeholder="Telegram username (optional)" className={inputClass} aria-label="Telegram username" />
        <input value={form.github_username} onChange={set('github_username')} placeholder="GitHub username (optional)" className={inputClass} aria-label="GitHub username" />
        <button type="submit" disabled={busy || !form.name.trim()} className={`${darkButton} sm:col-span-2`}>
          {busy ? 'Adding…' : 'Add teammate'}
        </button>
      </form>
    </Panel>
  );
};

const Team = ({ pid, people, onChanged }) => {
  const waiting = people.filter((p) => !p.telegram_chat_id).length;
  return (
    <div className="space-y-4">
      <Panel icon={Users} title={`Team (${people.length})`}>
        <p className="text-sm text-slate-500">
          Each teammate opens their personal invite link (or scans the QR code) and taps <strong>Start</strong> in Telegram.
          That links their chat to their tasks, and Cadence can start checking in.
          {waiting > 0 ? ` ${waiting} still ${waiting === 1 ? 'has' : 'have'} not joined.` : people.length > 0 ? ' Everyone has joined.' : ''}
        </p>
      </Panel>

      {people.length === 0 ? (
        <EmptyState icon={Users} title="No teammates yet">
          Add the people on this project below. Each one gets an invite link for the Telegram bot.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {people.map((person) => <MemberCard key={person.id} pid={pid} person={person} onChanged={onChanged} />)}
        </div>
      )}

      <AddTeammate pid={pid} onChanged={onChanged} />
    </div>
  );
};

export default Team;
