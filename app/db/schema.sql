-- ============================================================
--  Cadence — SQLite schema  (spec §11)
--  Applied once at startup via app/db/repo.py:init_db()
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  summary         TEXT,
  deadline        TEXT,
  timezone        TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  group_chat_id   INTEGER,                         -- Telegram group for digests (optional)
  status          TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','active','archived')),
  settings_json   TEXT NOT NULL DEFAULT '{}',      -- thresholds, cadence, demo_mode
  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS participants (
  id                INTEGER PRIMARY KEY,
  project_id        INTEGER NOT NULL REFERENCES projects(id),
  name              TEXT NOT NULL,
  role              TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('lead','member')),
  skills            TEXT,                          -- comma-separated
  telegram_chat_id  INTEGER UNIQUE,                -- set on /start
  telegram_username TEXT,
  invite_code       TEXT NOT NULL UNIQUE,
  onboarded_at      TEXT,
  last_seen_at      TEXT,
  paused_until      TEXT                           -- /pause
);

CREATE TABLE IF NOT EXISTS source_documents (       -- originals, never edited
  id           INTEGER PRIMARY KEY,
  project_id   INTEGER NOT NULL REFERENCES projects(id),
  kind         TEXT NOT NULL CHECK (kind IN ('spec','task_doc','roster')),
  filename     TEXT,
  mime_type    TEXT,
  content      TEXT NOT NULL,                      -- extracted text
  sha256       TEXT NOT NULL,
  uploaded_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id                 INTEGER PRIMARY KEY,
  agent              TEXT NOT NULL CHECK (agent IN ('planner','coordinator','composer')),
  provider           TEXT NOT NULL,                -- ollama | opencode
  model              TEXT NOT NULL,
  request_json       TEXT,
  response_text      TEXT,
  parsed_ok          INTEGER NOT NULL,
  error              TEXT,
  prompt_tokens      INTEGER,
  completion_tokens  INTEGER,
  latency_ms         INTEGER,
  created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_drafts (
  id               INTEGER PRIMARY KEY,
  project_id       INTEGER NOT NULL REFERENCES projects(id),
  plan_json        TEXT NOT NULL,                  -- PlanDraft JSON
  validation_json  TEXT NOT NULL,                  -- warnings, dropped edges
  status           TEXT NOT NULL DEFAULT 'review'
                   CHECK (status IN ('review','committed','discarded')),
  llm_call_id      INTEGER REFERENCES llm_calls(id),
  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  committed_at     TEXT
);

CREATE TABLE IF NOT EXISTS milestones (
  id          INTEGER PRIMARY KEY,
  project_id  INTEGER NOT NULL REFERENCES projects(id),
  key         TEXT NOT NULL,
  name        TEXT NOT NULL,
  due         TEXT,
  UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS tasks (
  id                   INTEGER PRIMARY KEY,
  project_id           INTEGER NOT NULL REFERENCES projects(id),
  key                  TEXT NOT NULL,              -- stable human id, "T3"
  title                TEXT NOT NULL,
  description          TEXT,
  acceptance           TEXT,
  milestone_id         INTEGER REFERENCES milestones(id),
  owner_id             INTEGER REFERENCES participants(id),
  status               TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','in_progress','blocked','complete')),
  readiness            TEXT NOT NULL DEFAULT 'ready' CHECK (readiness IN ('waiting','ready')),
  progress_note        TEXT,
  eta                  TEXT,
  deadline             TEXT,
  estimate_hours       REAL,
  requires_evidence    INTEGER NOT NULL DEFAULT 0,
  verified             INTEGER NOT NULL DEFAULT 0,
  completion_evidence  TEXT,
  flags_json           TEXT NOT NULL DEFAULT '[]',
  on_critical_path     INTEGER NOT NULL DEFAULT 0,
  source               TEXT NOT NULL DEFAULT 'planner'
                       CHECK (source IN ('planner','task_doc','runtime','manual')),
  version              INTEGER NOT NULL DEFAULT 1, -- optimistic locking
  last_followup_at     TEXT,
  last_reply_at        TEXT,
  completed_at         TEXT,
  created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS messages (
  id                   INTEGER PRIMARY KEY,
  project_id           INTEGER NOT NULL REFERENCES projects(id),
  participant_id       INTEGER REFERENCES participants(id),  -- NULL for group posts
  direction            TEXT NOT NULL CHECK (direction IN ('in','out')),
  channel              TEXT NOT NULL DEFAULT 'telegram_dm'
                       CHECK (channel IN ('telegram_dm','telegram_group')),
  telegram_message_id  INTEGER,
  text                 TEXT NOT NULL,
  template_key         TEXT,                       -- outbound only
  related_task_ids     TEXT,                       -- JSON array
  interpretation_json  TEXT,                       -- inbound: Coordinator output
  llm_call_id          INTEGER REFERENCES llm_calls(id),
  created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dependencies (
  id                     INTEGER PRIMARY KEY,
  project_id             INTEGER NOT NULL REFERENCES projects(id),
  upstream_task_id       INTEGER NOT NULL REFERENCES tasks(id),   -- finishes first
  downstream_task_id     INTEGER NOT NULL REFERENCES tasks(id),   -- waits
  type                   TEXT NOT NULL DEFAULT 'hard' CHECK (type IN ('hard','soft')),
  source                 TEXT NOT NULL
                         CHECK (source IN ('explicit','inferred','runtime','manual')),
  state                  TEXT NOT NULL DEFAULT 'active'
                         CHECK (state IN ('proposed','active','rejected')),
  redundant              INTEGER NOT NULL DEFAULT 0,
  reason                 TEXT,
  evidence               TEXT,
  confidence             REAL NOT NULL DEFAULT 1.0,
  created_by_message_id  INTEGER REFERENCES messages(id),
  created_at             TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (upstream_task_id, downstream_task_id),
  CHECK (upstream_task_id <> downstream_task_id)
);

CREATE TABLE IF NOT EXISTS blockers (
  id                     INTEGER PRIMARY KEY,
  task_id                INTEGER NOT NULL REFERENCES tasks(id),
  description            TEXT NOT NULL,
  kind                   TEXT NOT NULL CHECK (kind IN ('task','person','external')),
  linked_task_id         INTEGER REFERENCES tasks(id),
  linked_participant_id  INTEGER REFERENCES participants(id),
  status                 TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open','pending_confirmation','resolved')),
  escalation_level       INTEGER NOT NULL DEFAULT 0,
  raised_message_id      INTEGER REFERENCES messages(id),
  resolved_message_id    INTEGER REFERENCES messages(id),
  raised_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at            TEXT
);

CREATE TABLE IF NOT EXISTS pending_questions (
  id              INTEGER PRIMARY KEY,
  participant_id  INTEGER NOT NULL REFERENCES participants(id),
  task_id         INTEGER REFERENCES tasks(id),
  kind            TEXT NOT NULL CHECK (kind IN (
                    'status_check','clarify_task','clarify_status','ask_blocker',
                    'verify_completion','dependency_conflict','confirm_unblocked',
                    'confirm_peer_claim','unblock_request','confirm_reopen','offer_task')),
  payload_json    TEXT NOT NULL DEFAULT '{}',      -- button options, blocker id, etc.
  message_id      INTEGER REFERENCES messages(id),
  nudge_count     INTEGER NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','answered','expired','escalated')),
  created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  answered_at     TEXT
);

CREATE TABLE IF NOT EXISTS task_events (            -- append-only audit log
  id                    INTEGER PRIMARY KEY,
  task_id               INTEGER NOT NULL REFERENCES tasks(id),
  event_type            TEXT NOT NULL,             -- status_changed, blocker_raised,
                                                   -- blocker_resolved, note_added,
                                                   -- dependency_added, readiness_changed,
                                                   -- verified, reopened, owner_changed,
                                                   -- override, reverted
  old_value             TEXT,
  new_value             TEXT,
  reason                TEXT,                      -- human-readable "why", shown on dashboard
  actor                 TEXT NOT NULL
                        CHECK (actor IN ('coordinator','planner','engine','lead','system')),
  source_message_id     INTEGER REFERENCES messages(id),
  confidence            REAL,
  reverted_by_event_id  INTEGER REFERENCES task_events(id),
  created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outbox (
  id               INTEGER PRIMARY KEY,
  participant_id   INTEGER REFERENCES participants(id),
  chat_id          INTEGER NOT NULL,
  template_key     TEXT NOT NULL,
  text             TEXT NOT NULL,                  -- rendered HTML
  buttons_json     TEXT,                           -- inline keyboard JSON
  dedupe_key       TEXT UNIQUE,                    -- e.g. "unblocked:T5:by:T3"
  status           TEXT NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','sent','failed')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  not_before       TEXT,
  sent_message_id  INTEGER REFERENCES messages(id),
  error            TEXT,
  created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports (
  id                 INTEGER PRIMARY KEY,
  project_id         INTEGER NOT NULL REFERENCES projects(id),
  kind               TEXT NOT NULL CHECK (kind IN ('digest','risk')),
  content_md         TEXT NOT NULL,
  posted_message_id  INTEGER REFERENCES messages(id),
  created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---- Indexes -------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tasks_owner_status  ON tasks(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_deps_upstream       ON dependencies(upstream_task_id, state);
CREATE INDEX IF NOT EXISTS idx_deps_downstream     ON dependencies(downstream_task_id, state);
CREATE INDEX IF NOT EXISTS idx_blockers_linked     ON blockers(linked_task_id, status);
CREATE INDEX IF NOT EXISTS idx_pq_open             ON pending_questions(participant_id, status);
CREATE INDEX IF NOT EXISTS idx_events_task         ON task_events(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_queue        ON outbox(status, not_before);
