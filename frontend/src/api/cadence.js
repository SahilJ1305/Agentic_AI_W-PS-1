import { CADENCE_API_URL } from './apiConfig';
import { useAuthStore } from '../authStore';

export class CadenceError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, { method = 'GET', json, form } = {}) {
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
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
    throw new CadenceError(detail, response.status);
  }
  return data;
}

export const cadence = {
  listProjects: () => request('/projects'),
  createProject: (name) => request('/projects', { method: 'POST', json: { name } }),
  getProject: (pid) => request(`/projects/${pid}`),
  listTasks: (pid) => request(`/projects/${pid}/tasks`),
  listParticipants: (pid) => request(`/projects/${pid}/participants`),
  listEvents: (pid) => request(`/projects/${pid}/events`),
  uploadSpec: (pid, file) => {
    const form = new FormData();
    form.append('kind', 'spec');
    form.append('file', file);
    return request(`/projects/${pid}/documents`, { method: 'POST', form });
  },
  checkIn: (pid) => request('/admin/checkin', { method: 'POST', json: { project_id: pid } }),
  followUp: (taskId) => request(`/tasks/${taskId}/follow-up`, { method: 'POST' }),
  overrideTask: (taskId, changes) => request(`/tasks/${taskId}`, { method: 'PATCH', json: changes }),
  // EventSource cannot send an Authorization header, so the token goes in the URL.
  streamUrl: (pid) => {
    const token = useAuthStore.getState().token;
    return `${CADENCE_API_URL}/api/projects/${pid}/stream?token=${encodeURIComponent(token || '')}`;
  },
};
