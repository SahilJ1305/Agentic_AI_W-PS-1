// Accounts service (backend/, Postgres): sign-up, login, password reset.
export const AUTH_API_URL = import.meta.env.VITE_AUTH_API_URL || 'http://localhost:8001';

// Cadence API (app/): projects, tasks, Telegram coordination, live stream.
export const CADENCE_API_URL = import.meta.env.VITE_CADENCE_API_URL || 'http://localhost:8000';

// The auth pages predate the split and import this name.
export const API_BASE_URL = AUTH_API_URL;
