import { useCallback, useEffect, useRef, useState } from 'react';
import { cadence } from '../api/cadence';
import { toast } from './useToastStore';

const SSE_EVENTS = [
  'task.updated', 'blocker.raised', 'blocker.resolved', 'dependency.changed',
  'message.in', 'message.out', 'interpretation',
  'participant.joined', 'team.changed',
  'plan.ready', 'plan.committed', 'plan.error', 'report.created',
];

const REFRESH_DEBOUNCE_MS = 350;
const FLASH_MS = 2200;
const MAX_LIVE = 200;

const EMPTY = {
  summary: null,
  tasks: [],
  people: [],
  events: [],
  messages: [],
  graph: { nodes: [], edges: [], critical_path: [] },
  blockers: [],
};

const asList = (value) => (Array.isArray(value) ? value : []);

/**
 * All project-scoped state for the dashboard. SSE events patch/refresh it; a burst of
 * events produces one reload. Mount this under a component keyed by project id so that
 * switching projects starts from a clean slate.
 */
export function useProjectData(projectId) {
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(false);
  const [liveEntries, setLiveEntries] = useState([]);
  const [interps, setInterps] = useState({});
  const [flashing, setFlashing] = useState({});
  const [dataTick, setDataTick] = useState(0);
  const [reportTick, setReportTick] = useState(0);
  const [planSignal, setPlanSignal] = useState(null);

  const requestId = useRef(0);
  const debounce = useRef(null);
  const flashTimers = useRef({});
  const entryId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    const startedAt = Date.now();
    const results = await Promise.allSettled([
      cadence.getProject(projectId),
      cadence.listTasks(projectId),
      cadence.listParticipants(projectId),
      cadence.listEvents(projectId),
      cadence.listMessages(projectId, { limit: 100 }),
      cadence.getGraph(projectId),
      cadence.listBlockers(projectId),
    ]);
    if (id !== requestId.current) return; // a newer load superseded this one

    const [summary, tasks, people, events, messages, graph, blockers] = results;
    const core = [summary, tasks, people].find((r) => r.status === 'rejected');
    setError(core ? core.reason?.message || 'Could not load the project.' : null);

    setData((prev) => ({
      summary: summary.status === 'fulfilled' ? summary.value : prev.summary,
      tasks: tasks.status === 'fulfilled' ? asList(tasks.value) : prev.tasks,
      people: people.status === 'fulfilled' ? asList(people.value) : prev.people,
      events: events.status === 'fulfilled' ? asList(events.value) : prev.events,
      messages: messages.status === 'fulfilled' ? asList(messages.value) : prev.messages,
      graph: graph.status === 'fulfilled' && graph.value ? graph.value : prev.graph,
      blockers: blockers.status === 'fulfilled' ? asList(blockers.value) : prev.blockers,
    }));
    // Live entries older than this load are now covered by the API data.
    setLiveEntries((entries) => entries.filter((e) => e.at > startedAt));
    setLoading(false);
    setDataTick((n) => n + 1);
  }, [projectId]);

  const scheduleRefresh = useCallback(() => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(load, REFRESH_DEBOUNCE_MS);
  }, [load]);

  const refreshNow = useCallback(() => {
    clearTimeout(debounce.current);
    return load();
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const flashTimersRef = flashTimers.current;
    const source = new EventSource(cadence.streamUrl(projectId));
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false); // EventSource reconnects by itself

    const flash = (key) => {
      if (!key) return;
      setFlashing((prev) => ({ ...prev, [key]: true }));
      clearTimeout(flashTimersRef[key]);
      flashTimersRef[key] = setTimeout(() => {
        setFlashing((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }, FLASH_MS);
    };

    const onEvent = (name) => (event) => {
      let payload = {};
      try {
        payload = JSON.parse(event.data || '{}');
      } catch {
        payload = {};
      }
      // The broadcaster is shared; ignore other projects' traffic when the payload says so.
      if (payload.project_id != null && Number(payload.project_id) !== Number(projectId)) return;

      entryId.current += 1;
      const item = { id: entryId.current, name, payload, at: Date.now() };
      setLiveEntries((entries) => [...entries.slice(-(MAX_LIVE - 1)), item]);

      if (name === 'task.updated') flash(payload.task_key);
      if (name === 'interpretation' && payload.message_id != null) {
        setInterps((prev) => ({ ...prev, [payload.message_id]: payload }));
      }
      if (name === 'report.created') {
        setReportTick((n) => n + 1);
        toast.info(`New ${payload.kind || ''} report is ready.`);
      }
      if (name === 'plan.ready') {
        setPlanSignal({ type: 'ready', draftId: payload.draft_id, warnings: payload.warnings_count, at: Date.now() });
        toast.info('A plan draft is ready for review in the Plan tab.');
      }
      if (name === 'plan.committed') {
        setPlanSignal({ type: 'committed', draftId: payload.draft_id, at: Date.now() });
        toast.success('Plan committed. The board is updated.');
      }
      if (name === 'plan.error') {
        setPlanSignal({ type: 'error', error: payload.error, at: Date.now() });
        toast.error(`The planner failed: ${payload.error || 'unknown error'}`);
      }
      scheduleRefresh();
    };

    const handlers = SSE_EVENTS.map((name) => [name, onEvent(name)]);
    handlers.forEach(([name, handler]) => source.addEventListener(name, handler));
    // After a (re)connect, catch up on anything missed while the stream was down.
    source.addEventListener('connected', scheduleRefresh);

    return () => {
      source.close();
      clearTimeout(debounce.current);
      Object.values(flashTimersRef).forEach(clearTimeout);
    };
  }, [projectId, scheduleRefresh]);

  return {
    ...data,
    loading,
    error,
    live,
    liveEntries,
    interps,
    flashing,
    dataTick,
    reportTick,
    planSignal,
    refresh: refreshNow,
  };
}
