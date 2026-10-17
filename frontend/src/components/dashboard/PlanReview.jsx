import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ChevronDown, ChevronUp, ClipboardList, FileQuestion, GitBranch, LayoutGrid, Network, Rocket, Sparkles,
} from 'lucide-react';
import { cadence } from '../../api/cadence';
import { toast } from '../../hooks/useToastStore';
import { primaryButton } from './helpers';
import { EmptyState, ErrorNote, Panel, Spinner } from './ui';
import PlanDependencies from './plan/PlanDependencies';
import PlanGraph, { SelectionCard } from './plan/PlanGraph';
import PlanOverview from './plan/PlanOverview';
import PlanTasks from './plan/PlanTasks';
import { AUTO_ACCEPT_CONFIDENCE, buildPlanModel, initialDecisions, pairKey } from './plan/planModel';

const PLAN_TIMEOUT_MS = 180_000;
const POLL_MS = 4000;
const WARNINGS_SHOWN = 3;

const PlanReview = ({ pid, people, planSignal, onCommitted, onGoToTeam }) => {
  const [draftId, setDraftId] = useState(null);
  const [plan, setPlan] = useState(null); // { draft, validation, status }
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState(null);
  const [noSpec, setNoSpec] = useState(false);
  const [decisions, setDecisions] = useState({});
  const [owners, setOwners] = useState({});
  const [committing, setCommitting] = useState(false);
  const [selection, setSelection] = useState(null);       // { type: 'node' | 'edge', id }
  const [allWarnings, setAllWarnings] = useState(false);
  const graphRef = useRef(null);
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
      setSelection(null);
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
  const model = useMemo(() => (draft ? buildPlanModel(draft, decisions, owners) : null), [draft, decisions, owners]);

  const decide = useCallback((id, value) => setDecisions((prev) => ({ ...prev, [id]: value })), []);
  const showInGraph = (next) => {
    setSelection(next);
    graphRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  const acceptAll = () => setDecisions((prev) => Object.fromEntries(Object.keys(prev).map((k) => [k, true])));

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
        Dependencies the planner is at least {Math.round(AUTO_ACCEPT_CONFIDENCE * 100)}% sure about are pre-selected; the rest are
        marked amber for you to decide.
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

      {draft && model && (
        <>
          {alreadyCommitted && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
              This draft was already {plan.status}. Re-plan to get a fresh one.
            </p>
          )}

          <PlanOverview model={model} summary={draft.summary} />

          {warnings.length > 0 && (
            <Panel icon={AlertTriangle} title={`Things to check (${warnings.length})`} className="!border-amber-200 !bg-amber-50/50">
              <ul className="list-disc pl-5 text-sm text-amber-900 space-y-1">
                {(allWarnings ? warnings : warnings.slice(0, WARNINGS_SHOWN)).map((w, i) => <li key={i}>{w}</li>)}
              </ul>
              {warnings.length > WARNINGS_SHOWN && (
                <button type="button" onClick={() => setAllWarnings((v) => !v)} className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-amber-800 hover:underline">
                  {allWarnings ? <><ChevronUp className="h-4 w-4" /> Show fewer</> : <><ChevronDown className="h-4 w-4" /> Show all {warnings.length}</>}
                </button>
              )}
            </Panel>
          )}

          <Panel icon={Network} title="Dependency map">
            <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1fr)_19rem]">
              <PlanGraph ref={graphRef} model={model} selection={selection} onSelect={setSelection} onDecide={decide} />
              <aside aria-label="Selection details" className="rounded-xl border border-slate-100 bg-slate-50/60 p-4 2xl:self-start">
                <SelectionCard model={model} selection={selection} onSelect={setSelection} onDecide={decide} owners={owners} />
              </aside>
            </div>
          </Panel>

          <Panel icon={LayoutGrid} title={`Tasks (${model.tasks.length}), in the order work can start`}>
            <PlanTasks
              model={model}
              people={people}
              owners={owners}
              setOwners={setOwners}
              selection={selection}
              onFocus={(key) => showInGraph({ type: 'node', id: key })}
              onGoToTeam={onGoToTeam}
            />
          </Panel>

          <Panel icon={GitBranch} title={`Dependencies (${acceptedCount} of ${(draft.dependencies || []).length} accepted)`}>
            <PlanDependencies
              model={model}
              selection={selection}
              onDecide={decide}
              onFocusEdge={(id) => showInGraph({ type: 'edge', id })}
              onAcceptAll={acceptAll}
            />
          </Panel>

          <div className="plan-commit-bar sticky bottom-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur">
            <p className="text-sm text-slate-600">
              <Rocket className="mr-1.5 inline h-4 w-4 text-blue-600" />
              <strong className="text-slate-900">{draft.tasks.length}</strong> tasks ·{' '}
              <strong className="text-slate-900">{acceptedCount}</strong> dependencies accepted
              {model.totals.rejected > 0 && <> · <strong className="text-red-700">{model.totals.rejected}</strong> rejected</>}
              {model.totals.unassigned > 0 && <> · <strong className="text-amber-700">{model.totals.unassigned}</strong> unassigned</>}
            </p>
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
