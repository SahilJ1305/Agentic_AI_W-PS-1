import React, { useMemo, useRef, useState } from 'react';
import { FileJson, Download, Check, X, AlertTriangle, HelpCircle } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { downloadText, primaryButton, secondaryButton } from './helpers';
import { Chip, ErrorNote, Panel, Spinner } from './ui';

const KIND_TONE = { added: 'green', changed: 'blue', removed: 'red' };

/** Lines only in v2 (added) and only in v1 (removed); enough to see what the meeting changed. */
function lineDiff(before, after) {
  const a = before.split('\n');
  const b = after.split('\n');
  const inA = new Set(a);
  const inB = new Set(b);
  return [
    ...a.filter((line) => line.trim() && !inB.has(line)).map((line) => ({ sign: '-', line })),
    ...b.filter((line) => line.trim() && !inA.has(line)).map((line) => ({ sign: '+', line })),
  ];
}

/** Upload Fireflies meeting notes, review the generated spec v2, then apply it as the new spec. */
const MeetingUpdate = ({ pid, onApplied }) => {
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [view, setView] = useState('changes');
  const diff = useMemo(() => (result ? lineDiff(result.spec_v1, result.spec_md) : []), [result]);

  const generate = async (file) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await cadence.reviseFromMeeting(pid, file));
      setView('changes');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  const apply = async () => {
    setApplying(true);
    try {
      const file = new File([result.spec_md], result.filename, { type: 'text/markdown' });
      const res = await cadence.uploadDocument(pid, 'spec', file);
      toast.success(
        res.imported
          ? `Spec v${result.version} applied: ${res.imported.tasks} tasks are on the board, live statuses kept.`
          : `Spec v${result.version} saved. The planner is drafting tasks from it on this tab.`,
      );
      setResult(null);
      await onApplied?.();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setApplying(false);
    }
  };

  return (
    <Panel icon={FileJson} title="Update the spec from a meeting">
      {!result && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-slate-500 flex-1 min-w-[16rem]">
            Upload the meeting notes (Fireflies JSON). Cadence compares them with the current spec and drafts the next
            version for you to review. Nothing changes until you apply it.
          </p>
          <input ref={input} type="file" accept=".json,application/json" className="hidden"
            onChange={(e) => generate(e.target.files?.[0])} />
          <button type="button" className={primaryButton} disabled={busy} onClick={() => input.current?.click()}>
            {busy ? <><Spinner className="w-4 h-4 text-white" /> Reading the meeting…</> : <><FileJson className="w-4 h-4" /> Upload meeting JSON</>}
          </button>
        </div>
      )}
      {busy && <p className="text-xs text-slate-400 mt-2">This can take up to a minute: the model rewrites the whole spec.</p>}
      <ErrorNote>{error}</ErrorNote>

      {result && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm text-slate-700 flex-1">
              <strong>{result.filename}</strong> drafted from {result.based_on}:{' '}
              {result.changes.length ? `${result.changes.length} change${result.changes.length === 1 ? '' : 's'}` : 'the meeting changed nothing'}.
            </p>
            <div className="inline-flex bg-slate-100 rounded-xl p-0.5 text-xs font-semibold">
              {['changes', 'diff', 'full'].map((id) => (
                <button key={id} type="button" onClick={() => setView(id)}
                  className={`px-3 py-1.5 rounded-lg ${view === id ? 'bg-white shadow-sm text-blue-600' : 'text-slate-500'}`}>
                  {id === 'changes' ? 'Changes' : id === 'diff' ? 'Changed lines' : 'Full v2'}
                </button>
              ))}
            </div>
          </div>

          {result.warnings.map((w) => (
            <p key={w} className="flex items-start gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-100 rounded-xl px-3 py-2">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {w}
            </p>
          ))}

          {view === 'changes' && (
            <ul className="space-y-2">
              {result.changes.map((c, i) => (
                <li key={i} className="border border-slate-100 rounded-xl px-3 py-2">
                  <div className="flex items-center gap-2">
                    <Chip tone={KIND_TONE[c.kind] || 'slate'}>{c.kind}</Chip>
                    {c.section && <span className="text-xs text-slate-400">{c.section}</span>}
                  </div>
                  <p className="text-sm text-slate-800 mt-1">{c.summary}</p>
                  {c.source && <p className="text-xs text-slate-400 mt-0.5">From the meeting: {c.source}</p>}
                </li>
              ))}
              {result.open_questions.length > 0 && (
                <li className="border border-violet-100 bg-violet-50/50 rounded-xl px-3 py-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-violet-700"><HelpCircle className="w-3.5 h-3.5" /> Left open in the meeting</p>
                  <ul className="mt-1 list-disc pl-5 text-sm text-slate-700">
                    {result.open_questions.map((q) => <li key={q}>{q}</li>)}
                  </ul>
                </li>
              )}
            </ul>
          )}

          {view === 'diff' && (
            <pre className="text-xs bg-slate-50 border border-slate-100 rounded-xl p-3 max-h-96 overflow-auto whitespace-pre-wrap">
              {diff.length ? diff.map((d, i) => (
                <div key={i} className={d.sign === '+' ? 'text-emerald-700 bg-emerald-50' : 'text-red-700 bg-red-50 line-through'}>
                  {d.sign} {d.line}
                </div>
              )) : 'No lines changed.'}
            </pre>
          )}

          {view === 'full' && (
            <pre className="text-xs bg-slate-50 border border-slate-100 rounded-xl p-3 max-h-96 overflow-auto whitespace-pre-wrap">{result.spec_md}</pre>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="button" className={primaryButton} disabled={applying || !result.changes.length} onClick={apply}>
              <Check className="w-4 h-4" /> {applying ? 'Applying…' : `Apply as spec v${result.version}`}
            </button>
            <button type="button" className={secondaryButton} onClick={() => downloadText(result.filename, result.spec_md)}>
              <Download className="w-4 h-4" /> Download v{result.version}
            </button>
            <button type="button" className={secondaryButton} disabled={applying} onClick={() => setResult(null)}>
              <X className="w-4 h-4" /> Discard
            </button>
          </div>
          <p className="text-[11px] text-slate-400">
            Applying keeps v1 unchanged, adds new tasks, updates owners, titles and deadlines the meeting changed, and never
            resets a task's live status.
          </p>
        </div>
      )}
    </Panel>
  );
};

export default MeetingUpdate;
