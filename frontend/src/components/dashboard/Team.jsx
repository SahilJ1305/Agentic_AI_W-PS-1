import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Users, Copy, QrCode, Github, UserPlus, Check, PauseCircle, Send, AtSign, Unlink } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { copyText, inputClass, secondaryButton, darkButton, timeAgo } from './helpers';
import { Chip, EmptyState, Panel } from './ui';
import TeamRoster from './TeamRoster';

function telegramState(person) {
  if (!person.telegram_chat_id) return { label: 'Not joined', tone: 'slate' };
  const pausedUntil = person.paused_until ? Date.parse(person.paused_until) : null;
  if (pausedUntil && pausedUntil > Date.now()) return { label: 'Paused', tone: 'amber' };
  return { label: 'On Telegram', tone: 'green' };
}

const HandleField = ({ pid, person, field, label, icon: Icon, onChanged }) => {
  const [value, setValue] = useState(person[field] || '');
  const [busy, setBusy] = useState(false);
  const dirty = value.trim().replace(/^@/, '') !== (person[field] || '');

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await cadence.updateParticipant(pid, person.id, { [field]: value.trim().replace(/^@/, '') || null });
      toast.success(
        field === 'github_username' && person.telegram_chat_id && value.trim()
          ? `Saved. ${person.name} was told on Telegram and can tap Recheck to verify finished tasks.`
          : `${label} saved for ${person.name}.`,
      );
      await onChanged();
    } catch (err) {
      toast.error(err.message);
      setValue(person[field] || '');   // the server refused it: show what is actually saved
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="flex items-center gap-2">
      <Icon className="w-4 h-4 text-slate-400 shrink-0" />
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={label}
        aria-label={`${label} for ${person.name}`}
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

const UnlinkButton = ({ pid, person, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const unlink = async () => {
    const who = person.joined_as || 'the Telegram account that joined';
    if (!window.confirm(`Disconnect ${who} from ${person.name} and make a new invite link? The old link stops working.`)) return;
    setBusy(true);
    try {
      await cadence.resetInvite(pid, person.id);
      toast.success(`${person.name} was unlinked. Send them the new invite link.`);
      await onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button type="button" onClick={unlink} disabled={busy} className={`${secondaryButton} !py-1 !px-2.5 text-xs`}>
      <Unlink className="w-3.5 h-3.5" /> {busy ? 'Unlinking…' : 'Unlink & new link'}
    </button>
  );
};

const MemberCard = ({ pid, person, gitCheck, onChanged }) => {
  const state = telegramState(person);
  const missingGithub = Boolean(gitCheck?.enabled) && !person.github_username;
  const skills = (person.skills || '').split(',').map((s) => s.trim()).filter(Boolean);
  const joined = Boolean(person.telegram_chat_id);
  return (
    <article className="bg-white border border-slate-200 rounded-2xl p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-50 text-[11px] font-bold text-blue-700">
          {String(person.name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('')}
        </span>
        <h3 className="font-semibold text-slate-900">{person.name}</h3>
        <Chip tone={person.role === 'lead' ? 'blue' : 'slate'}>{person.role}</Chip>
        <Chip tone={state.tone} icon={state.label === 'Paused' ? PauseCircle : state.label === 'On Telegram' ? Send : undefined}>{state.label}</Chip>
        {missingGithub && <Chip tone="amber" icon={Github}>No GitHub username</Chip>}
        {person.username_mismatch && <Chip tone="amber" icon={AtSign}>Account mismatch</Chip>}
        {person.paused_until && state.label === 'Paused' && (
          <span className="text-xs text-slate-400">until {new Date(person.paused_until).toLocaleString()}</span>
        )}
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {person.open_task_count ?? 0} open task{person.open_task_count === 1 ? '' : 's'}
        {person.task_count != null ? ` of ${person.task_count}` : ''}
        {person.last_seen_at ? ` · seen ${timeAgo(person.last_seen_at)}` : ''}
      </p>
      {joined && person.joined_as && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span>Joined as <strong>{person.joined_as}</strong></span>
          <UnlinkButton pid={pid} person={person} onChanged={onChanged} />
        </div>
      )}
      {person.username_mismatch && (
        <div role="alert" className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          The saved Telegram username <strong>@{person.telegram_username}</strong> does not match the account that joined
          (<strong>@{person.joined_username}</strong>). If the wrong person joined, press <em>Unlink &amp; new link</em> and send
          them a fresh link; otherwise correct the username to the joined account.
        </div>
      )}
      {skills.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {skills.map((skill) => <Chip key={skill}>{skill}</Chip>)}
        </div>
      )}
      <div className="mt-3 space-y-2">
        <div>
          <HandleField key={`tg-${person.telegram_username || ''}`} pid={pid} person={person} field="telegram_username"
            label="Telegram username" icon={AtSign} onChanged={onChanged} />
          <p className="text-[11px] text-slate-400 mt-1">
            {joined && person.joined_username
              ? `Joined as @${person.joined_username}. A saved username has to match that account; unlink first to change the person.`
              : joined
                ? 'The account that joined has no Telegram username, so there is nothing to compare. Unlink to change the person.'
                : person.telegram_username
                  ? `Only @${person.telegram_username} can use this invite, and they can also just open the bot and tap Start.`
                  : 'Without it, whoever opens the invite link first joins as this person.'}
          </p>
        </div>
        <div>
          <HandleField key={`gh-${person.github_username || ''}`} pid={pid} person={person} field="github_username"
            label="GitHub username" icon={Github} onChanged={onChanged} />
          {missingGithub ? (
            <p className="text-[11px] text-amber-700 mt-1">
              Without this, {person.name}&apos;s “done” claims are accepted but stay <strong>unverified</strong>. Cadence never guesses a username.
            </p>
          ) : (
            <p className="text-[11px] text-slate-400 mt-1">Used to check “done” claims against this person&apos;s commits.</p>
          )}
        </div>
      </div>
      {joined && !person.joined_as && (
        <div className="mt-2"><UnlinkButton pid={pid} person={person} onChanged={onChanged} /></div>
      )}
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
        <input value={form.telegram_username} onChange={set('telegram_username')} placeholder="Telegram username (recommended)" className={inputClass} aria-label="Telegram username" />
        <input value={form.github_username} onChange={set('github_username')} placeholder="GitHub username (optional)" className={inputClass} aria-label="GitHub username" />
        <button type="submit" disabled={busy || !form.name.trim()} className={`${darkButton} sm:col-span-2`}>
          {busy ? 'Adding…' : 'Add teammate'}
        </button>
      </form>
    </Panel>
  );
};

const Team = ({ pid, people, gitCheck, onChanged, projects = [], onSelectProject, refreshKey }) => {
  const waiting = people.filter((p) => !p.telegram_chat_id).length;
  const noGithub = gitCheck?.enabled ? people.filter((p) => !p.github_username) : [];
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[22rem_minmax(0,1fr)] xl:items-start">
    <div className="min-w-0 space-y-4">
      <Panel icon={Users} title={`Team (${people.length})`}>
        <p className="text-sm text-slate-500">
          Each teammate opens their personal invite link (or scans the QR code) and taps <strong>Start</strong> in Telegram.
          That links their chat to their tasks, and Cadence can start checking in. Save each person&apos;s Telegram username
          so only they can use their link; then they can simply open the bot and tap Start, no link needed.
          {waiting > 0 ? ` ${waiting} still ${waiting === 1 ? 'has' : 'have'} not joined.` : people.length > 0 ? ' Everyone has joined.' : ''}
        </p>
      </Panel>

      {noGithub.length > 0 && (
        <div role="status" className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>{noGithub.length} {noGithub.length === 1 ? 'teammate has' : 'teammates have'} no GitHub username yet</strong>
          {' '}({noGithub.map((p) => p.name).join(', ')}). Cadence checks “done” claims against {gitCheck.repo || 'the repository'}
          and never guesses usernames, so until you add them below their finished tasks are marked unverified. When you save one,
          that person is told on Telegram and can tap <em>Recheck</em>.
        </div>
      )}

      {people.length === 0 ? (
        <EmptyState icon={Users} title="No teammates yet">
          Add the people on this project below. Each one gets an invite link for the Telegram bot.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {people.map((person) => <MemberCard key={person.id} pid={pid} person={person} gitCheck={gitCheck} onChanged={onChanged} />)}
        </div>
      )}

      <AddTeammate pid={pid} onChanged={onChanged} />
    </div>

    {projects.length > 0 && (
      <div className="xl:order-first xl:sticky xl:top-40">
        <TeamRoster
          projects={projects}
          currentProjectId={pid}
          livePeople={people}
          onSelectProject={onSelectProject}
          onChangedCurrent={onChanged}
          refreshKey={refreshKey}
        />
      </div>
    )}
    </div>
  );
};

export default Team;
