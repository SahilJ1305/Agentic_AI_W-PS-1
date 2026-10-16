import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ClipboardList, Sparkles, AlertTriangle, Check, X, FileQuestion, Quote } from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { inputClass, primaryButton, percent, shortDate } from './helpers';
import { Chip, EmptyState, ErrorNote, Panel, Spinner } from './ui';

const AUTO_ACCEPT_CONFIDENCE = 0.8;
const PLAN_TIMEOUT_MS = 180_000;
const POLL_MS = 4000;

const pairKey = (dep) => `${dep.upstream}>${dep.downstream}`;

const initialDecisions = (draft) =>
  Object.fromEntries((draft?.dependencies || []).map((d) => [pairKey(d), (d.confidence ?? 1) >= AUTO_ACCEPT_CONFIDENCE]));

const PlanReview = ({ pid, people, planSignal, onCommitted, onGoToTeam }) => {
  const [draftId, setDraftId] = useState(null);
  const [plan, setPlan] = useState(null); // { draft, validation, status }
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState(null);
  const [noSpec, setNoSpec] = useState(false);
  const [decisions, setDecisions] = useState({});
  const [owners, setOwners] = useState({});
  const [committing, setCommitting] = useState(false);
  const timeout = useRef(null);
  const poll = useRef(null);
  const handledSignal = useRef(null);

  const stopWaiting = useCallback(() => {
    clearTimeout(timeout.current);
    clearInterval(poll.current);
    setPlanning(false);
  }, []);

  const loadDraft = useCallback(async (id) => {
    try {
      const result = await cadence.getPlan(pid, id);
      setDraftId(id);
      setPlan(result);
      setDecisions(initialDecisions(result.draft));
      setOwners({});
      setError(null);
      stopWaiting();
      return true;
    } catch (err) {
      if (err.status !== 404) setError(err.message);
      return false;
    }
  }, [pid, stopWaiting]);

  // On first visit try the newest draft. Needs GET /plan/latest on the API; ignored if it is missing.
  useEffect(() => {
    let cancelled = false;
    cadence.getPlan(pid, 'latest').then((result) => {
      const id = result?.draft_id ?? result?.id;
      if (cancelled || !result?.draft || id == null) return;
      setPlan(result);
      setDraftId(id);
      setDecisions(initialDecisions(result.draft));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [pid]);

  // React to plan.ready / plan.error over SSE.
  useEffect(() => {
    if (!planSignal || handledSignal.current === planSignal.at) return;
    handledSignal.current = planSignal.at;
    if (planSignal.type === 'ready' && planSignal.draftId != null) {
      loadDraft(planSignal.draftId);
    } else if (planSignal.type === 'error') {
      stopWaiting();
      setError(`The planner failed: ${planSignal.error || 'unknown error'}`);
    } else if (planSignal.type === 'committed') {
      setPlan(null);
      setDraftId(null);
    }
  }, [planSignal, loadDraft, stopWaiting]);

  useEffect(() => () => { clearTimeout(timeout.current); clearInterval(poll.current); }, []);

  const replan = async () => {
    setError(null);
    setNoSpec(false);
    setPlanning(true);
    try {
      const result = await cadence.runPlan(pid);
      toast.info('The planner is reading your spec. This takes a few seconds.');
      // Preferred: wait for plan.ready over SSE. If the API returns a draft id, poll it as a fallback.
      const id = result?.draft_id;
      if (id != null) poll.current = setInterval(() => loadDraft(id), POLL_MS);
      timeout.current = setTimeout(() => {
        stopWaiting();
        setError('The planner is taking longer than expected. Check that the backend and the LLM are running, then try again.');
      }, PLAN_TIMEOUT_MS);
    } catch (err) {
      setPlanning(false);
      if (err.status === 400 && /spec/i.test(err.message)) setNoSpec(true);
      else setError(err.message);
    }
  };

  const commit = async () => {
    const deps = plan.draft.dependencies || [];
    const accepted = deps.filter((d) => decisions[pairKey(d)]).map((d) => [d.upstream, d.downstream]);
    const rejected = deps.filter((d) => !decisions[pairKey(d)]).map((d) => [d.upstream, d.downstream]);
    const ownerOverrides = {};
    Object.entries(owners).forEach(([key, name]) => {
      const original = plan.draft.tasks.find((t) => t.key === key)?.owner_name || '';
      if (name !== original && name) ownerOverrides[key] = name;
    });
    setCommitting(true);
    try {
      const result = await cadence.commitPlan(pid, draftId, {
        accepted_edge_pairs: accepted,
        rejected_edge_pairs: rejected,
        owner_overrides: ownerOverrides,
      });
      toast.success(`Plan committed: ${result.tasks ?? plan.draft.tasks.length} tasks created.`);
      setPlan(null);
      setDraftId(null);
      await onCommitted();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setCommitting(false);
    }
  };

  const draft = plan?.draft;
  const warnings = useMemo(() => {
    const all = [...(plan?.validation?.warnings || []), ...(draft?.warnings || [])];
    return [...new Set(all)];
  }, [plan, draft]);
  const alreadyCommitted = plan?.status && plan.status !== 'review';
  const acceptedCount = Object.values(decisions).filter(Boolean).length;

  const header = (
    <Panel
      icon={ClipboardList}
      title="Plan review"
      actions={(
        <button type="button" onClick={replan} disabled={planning} className={primaryButton}>
          {planning ? <Spinner className="w-4 h-4 !text-white" /> : <Sparkles className="w-4 h-4" />}
          {planning ? 'Planning…' : 'Re-plan from spec'}
        </button>
      )}
    >
      <p className="text-sm text-slate-500">
        The planner reads your spec and proposes tasks, owners and dependencies. Nothing is created until you commit.
        Dependencies the planner is at least {Math.round(AUTO_ACCEPT_CONFIDENCE * 100)}% sure about are pre-selected.
      </p>
    </Panel>
  );

  if (noSpec) {
    return (
      <div className="space-y-4">
        {header}
        <EmptyState icon={FileQuestion} title="No spec uploaded yet">
          Cadence needs a project spec to plan from. Create a new project with a spec file from the project menu at the top of the page.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {header}
      <ErrorNote>{error}</ErrorNote>

      {planning && (
        <div className="flex items-center gap-3 bg-blue-50 border border-blue-100 text-blue-800 rounded-2xl px-5 py-4 text-sm">
          <Spinner /> Planner is working. The draft appears here as soon as it is ready.
        </div>
      )}

      {!draft && !planning && !error && (
        <EmptyState icon={ClipboardList} title="No draft to review">
          Click “Re-plan from spec” to generate a draft of tasks and dependencies for this project.
        </EmptyState>
      )}

      {draft && (
        <>
          {alreadyCommitted && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
              This draft was already {plan.status}. Re-plan to get a fresh one.
            </p>
          )}

          {draft.summary && <p className="text-sm text-slate-600 px-1">{draft.summary}</p>}

          {warnings.length > 0 && (
            <Panel icon={AlertTriangle} title={`Validation warnings (${warnings.length})`} className="!border-amber-200 !bg-amber-50/50">
              <ul className="list-disc pl-5 text-sm text-amber-900 space-y-1">
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </Panel>
          )}

          <Panel title={`Tasks (${draft.tasks.length})`}>
            {people.length === 0 && (
              <p className="text-xs text-amber-700 mb-2">
                No teammates yet, so owners cannot be changed. <button type="button" className="underline" onClick={onGoToTeam}>Add teammates</button>.
              </p>
            )}
            <ul className="divide-y divide-slate-100">
              {draft.tasks.map((task) => {
                const current = owners[task.key] ?? task.owner_name ?? '';
                const nameKnown = !current || people.some((p) => p.name === current);
                return (
                  <li key={task.key} className="py-3 grid grid-cols-1 md:grid-cols-[1fr_220px] gap-2">
                    <div className="min-w-0">
                      <div className="text-sm">
                        <span className="font-semibold text-slate-900">{task.key}</span>{' '}
                        <span className="text-slate-800">{task.title}</span>
                      </div>
                      {task.description && <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{task.description}</p>}
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {task.deadline && <Chip tone="slate">due {shortDate(task.deadline)}</Chip>}
                        {task.estimate_hours != null && <Chip tone="slate">{task.estimate_hours}h</Chip>}
                        {task.requires_evidence && <Chip tone="amber">needs evidence</Chip>}
                        {task.owner_name && percent(task.owner_confidence) && task.owner_confidence < 1 && (
                          <Chip tone="slate" title="How sure the planner is about the owner">owner {percent(task.owner_confidence)}</Chip>
                        )}
                      </div>
                    </div>
                    <select
                      value={current}
                      onChange={(e) => setOwners((prev) => ({ ...prev, [task.key]: e.target.value }))}
                      className={inputClass}
                      aria-label={`Owner of ${task.key}`}
                    >
                      <option value="">Unassigned</option>
                      {!nameKnown && <option value={current}>{current} (not on the team)</option>}
                      {people.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
                    </select>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel title={`Dependencies (${acceptedCount} of ${(draft.dependencies || []).length} accepted)`}>
            {(draft.dependencies || []).length === 0 ? (
              <p className="text-sm text-slate-400">The planner found no dependencies between tasks.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {draft.dependencies.map((dep) => {
                  const key = pairKey(dep);
                  const accepted = Boolean(decisions[key]);
                  return (
                    <li key={key} className={`py-3 flex gap-3 ${accepted ? '' : 'opacity-60'}`}>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <span className="font-semibold text-slate-900">{dep.upstream} → {dep.downstream}</span>
                          <Chip tone={dep.type === 'hard' ? 'blue' : 'slate'}>{dep.type}</Chip>
                          <Chip tone={(dep.confidence ?? 1) >= AUTO_ACCEPT_CONFIDENCE ? 'green' : 'amber'}>{percent(dep.confidence ?? 1)}</Chip>
                          {dep.rule && <Chip tone="violet" title="Rule that proposed this edge">{dep.rule}</Chip>}
                        </div>
                        {dep.reason && <p className="text-sm text-slate-600 mt-1">{dep.reason}</p>}
                        {dep.evidence_quote && (
                          <p className="text-xs italic text-slate-500 mt-1 flex gap-1">
                            <Quote className="w-3 h-3 mt-0.5 shrink-0" /> {dep.evidence_quote}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-1 shrink-0 self-start" role="group" aria-label={`Decision for ${key}`}>
                        <button
                          type="button"
                          aria-pressed={accepted}
                          onClick={() => setDecisions((prev) => ({ ...prev, [key]: true }))}
                          className={`p-2 rounded-lg border ${accepted ? 'bg-emerald-600 border-emerald-600 text-white' : 'border-slate-300 text-slate-500 hover:bg-slate-50'}`}
                          title="Accept"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          aria-pressed={!accepted}
                          onClick={() => setDecisions((prev) => ({ ...prev, [key]: false }))}
                          className={`p-2 rounded-lg border ${!accepted ? 'bg-red-600 border-red-600 text-white' : 'border-slate-300 text-slate-500 hover:bg-slate-50'}`}
                          title="Reject"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <div className="flex justify-end">
            <button type="button" onClick={commit} disabled={committing || alreadyCommitted} className={primaryButton}>
              {committing ? 'Committing…' : `Commit plan (${draft.tasks.length} tasks, ${acceptedCount} dependencies)`}
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default PlanReview;
