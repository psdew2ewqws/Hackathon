-- Phase 3 §8.5 storage. Designed multi-site from day 1 (site_id FK everywhere).
-- Portable SQL: sqlite3 dialect, but every construct has a Postgres equivalent.

CREATE TABLE IF NOT EXISTS sites (
  site_id     TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  lat         REAL,
  lng         REAL,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS users (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  username    TEXT NOT NULL UNIQUE,
  pw_hash     TEXT NOT NULL,
  role        TEXT NOT NULL CHECK (role IN ('viewer','operator','admin')),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS detector_counts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id        TEXT NOT NULL,
  ts             TEXT NOT NULL,
  detector_id    TEXT,
  approach       TEXT NOT NULL,
  lane           INTEGER,
  count          INTEGER NOT NULL,
  occupancy_pct  REAL,
  quality_flag   INTEGER DEFAULT 0,
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_counts_site_ts ON detector_counts(site_id, ts);
CREATE INDEX IF NOT EXISTS idx_counts_approach_ts ON detector_counts(approach, ts);

CREATE TABLE IF NOT EXISTS signal_events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id        TEXT NOT NULL,
  ts             TEXT NOT NULL,
  cycle_number   INTEGER,
  phase_number   INTEGER NOT NULL,
  phase_name     TEXT,
  signal_state   TEXT NOT NULL CHECK (signal_state IN ('GREEN ON','YELLOW ON','RED ON')),
  duration_s     REAL,
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_signal_site_ts ON signal_events(site_id, ts);

CREATE TABLE IF NOT EXISTS incidents (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id        TEXT NOT NULL,
  ts             TEXT NOT NULL,
  event_id       TEXT NOT NULL UNIQUE,
  event_type     TEXT NOT NULL,
  approach       TEXT,
  severity       TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  confidence     REAL,
  payload        TEXT,             -- JSON blob
  snapshot_uri   TEXT,
  clip_uri       TEXT,
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved','dismissed','escalated')),
  resolved_at    TEXT,
  resolved_by    INTEGER,          -- FK to users.id
  FOREIGN KEY (site_id) REFERENCES sites(site_id),
  FOREIGN KEY (resolved_by) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_incidents_site_ts ON incidents(site_id, ts);
CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents(event_type);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);

CREATE TABLE IF NOT EXISTS forecasts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id        TEXT NOT NULL,
  made_at        TEXT NOT NULL,    -- when the prediction was produced
  target_ts      TEXT NOT NULL,    -- timestamp the prediction is FOR
  approach       TEXT NOT NULL,
  horizon_min    INTEGER NOT NULL, -- 0/15/30/60
  demand_pred    REAL NOT NULL,
  model_version  TEXT,
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_site_target ON forecasts(site_id, target_ts);

CREATE TABLE IF NOT EXISTS recommendations (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id          TEXT NOT NULL,
  ts               TEXT NOT NULL,
  mode             TEXT NOT NULL,            -- 'two_phase' | 'four_phase_nema'
  cycle_s          REAL,
  ns_green         REAL,
  ew_green         REAL,
  delay_est_s      REAL,
  component_json   TEXT,                      -- full Webster snapshot
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_recs_site_ts ON recommendations(site_id, ts);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  user_id    INTEGER,
  username   TEXT,
  role       TEXT,
  action     TEXT NOT NULL,
  resource   TEXT NOT NULL,
  payload    TEXT,
  ip         TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);

CREATE TABLE IF NOT EXISTS ingest_errors (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id    TEXT,
  ts         TEXT NOT NULL,
  source     TEXT NOT NULL,
  reason     TEXT NOT NULL,
  record     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_ts ON ingest_errors(ts);

CREATE TABLE IF NOT EXISTS system_metrics (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id          TEXT,
  ts               TEXT NOT NULL,
  module           TEXT NOT NULL,
  fps              REAL,
  uptime_s         REAL,
  frames_dropped   INTEGER,
  latency_ms       REAL,
  mem_mb           REAL,
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_metrics_module_ts ON system_metrics(module, ts);

-- LLM advisor (opt-in feature, gated by ANTHROPIC_API_KEY at runtime).
-- Tables exist regardless of whether the feature is activated, so audit
-- queries don't have to branch.
CREATE TABLE IF NOT EXISTS llm_conversations (
  id                TEXT PRIMARY KEY,
  user_id           INTEGER NOT NULL,
  username          TEXT NOT NULL,
  site_id           TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  title             TEXT,
  model             TEXT NOT NULL,
  total_tokens_in   INTEGER NOT NULL DEFAULT 0,
  total_tokens_out  INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_llm_conv_user ON llm_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS llm_messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  turn_index      INTEGER NOT NULL,
  ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,                -- plain text, or JSON array of Anthropic content blocks
  tokens_in       INTEGER,
  tokens_out      INTEGER,
  FOREIGN KEY (conversation_id) REFERENCES llm_conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_llm_msg_conv ON llm_messages(conversation_id, ts);

-- Phase 2: forecast scoring. Joins each persisted forecast against the
-- detector_count bin whose ts ≈ target_ts, so we can render rolling MAE
-- per approach × horizon on the dashboard. Populated by
-- scripts/backfill_forecast_score.py (idempotent).
CREATE TABLE IF NOT EXISTS forecast_score (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  site_id        TEXT NOT NULL,
  target_ts      TEXT NOT NULL,
  approach       TEXT NOT NULL,
  horizon_min    INTEGER NOT NULL,
  demand_pred    REAL NOT NULL,
  demand_actual  REAL NOT NULL,
  abs_err        REAL NOT NULL,
  made_at        TEXT NOT NULL,
  UNIQUE(site_id, target_ts, approach, horizon_min, made_at)
);
CREATE INDEX IF NOT EXISTS idx_fc_score_site_target ON forecast_score(site_id, target_ts);
CREATE INDEX IF NOT EXISTS idx_fc_score_horizon ON forecast_score(horizon_min);

-- Phase 4: controller comparison runs. Reserved here so the additive
-- migration story stays in one place.
CREATE TABLE IF NOT EXISTS controller_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,
  controller    TEXT NOT NULL,
  cycle_s       REAL,
  ns_green      REAL,
  ew_green      REAL,
  est_delay_s   REAL,
  est_throughput REAL,
  run_id        TEXT
);
CREATE INDEX IF NOT EXISTS idx_ctrl_runs_run ON controller_runs(run_id);

-- Bootstrap the default site used by the PoC. Idempotent via INSERT OR IGNORE.
INSERT OR IGNORE INTO sites (site_id, name, lat, lng)
VALUES ('wadi_saqra', 'Wadi Saqra intersection', 31.966707273799933, 35.88701562636417);
