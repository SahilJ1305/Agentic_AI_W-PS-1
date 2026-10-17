import { CADENCE_API_URL } from './apiConfig';
import { useAuthStore } from '../authStore';

export class CadenceError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(path, { method = 'GET', json, form, as = 'json' } = {}) {
  const token = useAuthStore.getState().token;
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  let body;
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }

  let response;
  try {
    response = await fetch(`${CADENCE_API_URL}/api${path}`, { method, headers, body });
  } catch {
    throw new CadenceError(`Cannot reach the Cadence API at ${CADENCE_API_URL}. Is it running?`, 0);
  }

  if (response.status === 401) {
    useAuthStore.getState().logout();
    throw new CadenceError('Your session expired. Log in again.', 401);
  }

  if (as === 'text' && response.ok) return response.text();

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    if (typeof data?.detail === 'string') detail = data.detail;
    else if (Array.isArray(data?.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    throw new CadenceError(detail, response.status, data);
  }
  return data;
}

const qs = (params) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
};

export const cadence = {
  // Projects
  listProjects: () => request('/projects'),
  createProject: (name) => request('/projects', { method: 'POST', json: { name } }),
  getProject: (pid) => request(`/projects/${pid}`),
  deleteProject: (pid) => request(`/projects/${pid}`, { method: 'DELETE' }),
  listTasks: (pid) => request(`/projects/${pid}/tasks`),
  listParticipants: (pid) => request(`/projects/${pid}/participants`),
  listEvents: (pid) => request(`/projects/${pid}/events`),
  listMessages: (pid, { participantId, limit = 100 } = {}) =>
    request(`/projects/${pid}/messages${qs({ participant_id: participantId, limit })}`),
  getGraph: (pid) => request(`/projects/${pid}/graph`),
  listBlockers: (pid) => request(`/projects/${pid}/blockers?status=open`),

  // Documents and planning
  uploadDocument: (pid, kind, file) => {
    const form = new FormData();
    form.append('kind', kind);
    form.append('file', file);
    return request(`/projects/${pid}/documents`, { method: 'POST', form });
  },
  uploadSpec: (pid, file) => cadence.uploadDocument(pid, 'spec', file),
  runPlan: (pid) => request(`/projects/${pid}/plan`, { method: 'POST' }),
  getPlan: (pid, draftId) => request(`/projects/${pid}/plan/${draftId}`),
  commitPlan: (pid, draftId, body) =>
    request(`/projects/${pid}/plan/${draftId}/commit`, { method: 'POST', json: body }),

  // Participants
  addParticipant: (pid, person) => request(`/projects/${pid}/participants`, { method: 'POST', json: person }),
  updateParticipant: (pid, id, changes) =>
    request(`/projects/${pid}/participants/${id}`, { method: 'PATCH', json: changes }),
  resetInvite: (pid, id) => request(`/projects/${pid}/participants/${id}/reset-invite`, { method: 'POST' }),

  // Tasks
  getTask: (taskId) => request(`/tasks/${taskId}`),
  overrideTask: (taskId, changes) => request(`/tasks/${taskId}`, { method: 'PATCH', json: changes }),
  followUp: (taskId) => request(`/tasks/${taskId}/follow-up`, { method: 'POST' }),
  revertEvent: (taskId, eventId) =>
    request(`/tasks/${taskId}/events/${eventId}/revert`, { method: 'POST' }),
  resolveBlocker: (blockerId, reason) =>
    request(`/blockers/${blockerId}/resolve`, { method: 'POST', json: { reason } }),

  // Dependencies
  createDependency: (body) => request('/dependencies', { method: 'POST', json: body }),
  updateDependency: (id, changes) => request(`/dependencies/${id}`, { method: 'PATCH', json: changes }),
  deleteDependency: (id) => request(`/dependencies/${id}`, { method: 'DELETE' }),

  // Reports and export
  generateReport: (pid, kind, post = false) =>
    request(`/projects/${pid}/reports/${kind}?post=${post ? 'true' : 'false'}`, { method: 'POST' }),
  latestReport: (pid, kind) => request(`/projects/${pid}/reports/latest?kind=${kind}`),
  exportMarkdown: (pid) => request(`/projects/${pid}/export.md`, { as: 'text' }),

  // Admin
  checkIn: (pid) => request('/admin/checkin', { method: 'POST', json: { project_id: pid } }),

  // /api/health is public (no auth header).
  health: async () => {
    const response = await fetch(`${CADENCE_API_URL}/api/health`).catch(() => null);
    if (!response?.ok) return null;
    return response.json().catch(() => null);
  },

  // EventSource cannot send an Authorization header, so the token goes in the URL.
  streamUrl: (pid) => {
    const token = useAuthStore.getState().token;
    return `${CADENCE_API_URL}/api/projects/${pid}/stream?token=${encodeURIComponent(token || '')}`;
  },
};
