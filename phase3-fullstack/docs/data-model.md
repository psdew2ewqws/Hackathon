# Phase 3 — Data Model

Source of truth: `phase3-fullstack/src/traffic_intel_phase3/storage/schema.sql`.
Applied on first boot by `get_db()` → `init_schema()`; idempotent (every
statement uses `IF NOT EXISTS`). SQLite is opened in WAL mode with
`PRAGMA foreign_keys = ON`. Eleven tables (plus SQLite's internal
`sqlite_sequence`); site_id is a TEXT FK on every site-scoped table so the
schema is already multi-site.

## Table reference

### `sites`
Per-intersection registry. Bootstrapped with `('wadi_saqra', …)` via
`INSERT OR IGNORE`. All site-scoped tables reference `sites.site_id`.

Columns: `site_id TEXT PK, name TEXT, lat REAL, lng REAL, active INT,
created_at TEXT`.

### `users`
Dashboard user accounts. `pw_hash` stores a bcrypt hash. `role` is a
CHECK-constrained enum. `ensure_default_users()` seeds `viewer`,
`operator`, `admin` idempotently from env vars.

Columns: `id INTEGER PK AI, username TEXT UNIQUE, pw_hash TEXT,
role TEXT CHECK IN (viewer|operator|admin), created_at TEXT`.

### `detector_counts`
One row per 15 s bin × approach. Written by the tracker bridge in
`server._tracker_on_bin()`. Indexed for the dashboard "last N minutes"
query and the training pipeline `SELECT … WHERE approach = ?`.

Columns: `id, site_id FK, ts, detector_id, approach, lane, count,
occupancy_pct, quality_flag`. Indexes: `(site_id, ts)`, `(approach, ts)`.

### `signal_events`
Phase transitions from `SignalSimulator`. One row per state change
(GREEN/YELLOW/RED_ON). Keyed for the dashboard "recent transitions" panel
and the offline Webster delay comparison.

Columns: `id, site_id FK, ts, cycle_number, phase_number, phase_name,
signal_state CHECK IN (GREEN ON|YELLOW ON|RED ON), duration_s`.
Index: `(site_id, ts)`.

### `incidents`
All §6.6 detector hits and composite incidents. `event_id` is TEXT UNIQUE so
the writer uses `INSERT OR IGNORE` (safe to retry). `status` tracks
operator lifecycle: active → resolved/dismissed/escalated.
`payload` is JSON serialized inline. Critical for the Incidents page.

Columns: `id, site_id FK, ts, event_id UNIQUE, event_type, approach,
severity CHECK IN (info|warning|critical), confidence, payload JSON,
snapshot_uri, clip_uri, status, resolved_at, resolved_by FK users.id`.
Indexes: `(site_id, ts)`, `(event_type)`, `(status)`.

### `forecasts`
Predictions emitted by the forecast bridge. Two timestamps: `made_at`
(when the prediction ran) and `target_ts` (the instant it's for).
Horizons are 0/15/30/60 minutes (matches LightGBM target columns).

Columns: `id, site_id FK, made_at, target_ts, approach, horizon_min,
demand_pred, model_version`. Index: `(site_id, target_ts)`.

### `recommendations`
Signal-plan recommendations produced by `webster_two_phase()`.
`component_json` stores the full Webster snapshot for drill-down.

Columns: `id, site_id FK, ts, mode, cycle_s, ns_green, ew_green,
delay_est_s, component_json JSON`. Index: `(site_id, ts)`.

### `audit_log`
Every privileged action (login/logout, event demo emit, config change).
Default `ts` uses SQLite millisecond format. The Audit page at
`/api/audit/log` filters by recency.

Columns: `id, ts, user_id FK, username, role, action, resource,
payload JSON, ip`. Indexes: `(ts)`, `(user_id)`.

### `ingest_errors`
Any record the ingest layer rejected (missing field, bad ts, etc.).
Feeds the System → Ingest Errors panel.

Columns: `id, site_id, ts, source, reason, record JSON`.
Index: `(ts)`.

### `system_metrics`
Periodic per-module health sample (tracker, signal_sim, sink). Used by the
System page to show FPS, uptime, frames dropped, latency.

Columns: `id, site_id, ts, module, fps, uptime_s, frames_dropped,
latency_ms, mem_mb`. Index: `(module, ts)`.

## Indexes that matter for the dashboard

- `idx_counts_site_ts` — Live and History pages, last N bins per site.
- `idx_incidents_site_ts` + `idx_incidents_status` — Incidents page default
  query `WHERE status='active' ORDER BY ts DESC`.
- `idx_audit_ts` — Audit page, newest-first pagination.
- `idx_signal_site_ts` — Signal Timing page replays.
- `idx_forecasts_site_target` — Forecast page chart (joins `target_ts`
  across all horizons).

## Postgres DDL mirror

Drop-in equivalent for the production migration — same tables, Postgres
types, named foreign-key constraints, JSONB payloads, timestamptz,
enum-equivalent CHECKs. Partitioning of `detector_counts` and `incidents`
by month is a natural next step once the row counts warrant it.

```sql
CREATE TABLE sites (
  site_id     TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  lat         DOUBLE PRECISION,
  lng         DOUBLE PRECISION,
  active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
  id          SERIAL PRIMARY KEY,
  username    TEXT NOT NULL UNIQUE,
  pw_hash     TEXT NOT NULL,
  role        TEXT NOT NULL CHECK (role IN ('viewer','operator','admin')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE detector_counts (
  id             BIGSERIAL PRIMARY KEY,
  site_id        TEXT NOT NULL,
  ts             TIMESTAMPTZ NOT NULL,
  detector_id    TEXT,
  approach       TEXT NOT NULL,
  lane           INTEGER,
  count          INTEGER NOT NULL,
  occupancy_pct  DOUBLE PRECISION,
  quality_flag   SMALLINT NOT NULL DEFAULT 0,
  CONSTRAINT fk_counts_site FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX idx_counts_site_ts     ON detector_counts(site_id, ts);
CREATE INDEX idx_counts_approach_ts ON detector_counts(approach, ts);

CREATE TABLE signal_events (
  id             BIGSERIAL PRIMARY KEY,
  site_id        TEXT NOT NULL,
  ts             TIMESTAMPTZ NOT NULL,
  cycle_number   INTEGER,
  phase_number   INTEGER NOT NULL,
  phase_name     TEXT,
  signal_state   TEXT NOT NULL CHECK (signal_state IN ('GREEN ON','YELLOW ON','RED ON')),
  duration_s     DOUBLE PRECISION,
  CONSTRAINT fk_signal_site FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX idx_signal_site_ts ON signal_events(site_id, ts);

CREATE TABLE incidents (
  id             BIGSERIAL PRIMARY KEY,
  site_id        TEXT NOT NULL,
  ts             TIMESTAMPTZ NOT NULL,
  event_id       TEXT NOT NULL UNIQUE,
  event_type     TEXT NOT NULL,
  approach       TEXT,
  severity       TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  confidence     DOUBLE PRECISION,
  payload        JSONB,
  snapshot_uri   TEXT,
  clip_uri       TEXT,
  status         TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','resolved','dismissed','escalated')),
  resolved_at    TIMESTAMPTZ,
  resolved_by    INTEGER,
  CONSTRAINT fk_incidents_site        FOREIGN KEY (site_id)     REFERENCES sites(site_id),
  CONSTRAINT fk_incidents_resolved_by FOREIGN KEY (resolved_by) REFERENCES users(id)
);
CREATE INDEX idx_incidents_site_ts ON incidents(site_id, ts);
CREATE INDEX idx_incidents_type    ON incidents(event_type);
CREATE INDEX idx_incidents_status  ON incidents(status);

CREATE TABLE forecasts (
  id             BIGSERIAL PRIMARY KEY,
  site_id        TEXT NOT NULL,
  made_at        TIMESTAMPTZ NOT NULL,
  target_ts      TIMESTAMPTZ NOT NULL,
  approach       TEXT NOT NULL,
  horizon_min    INTEGER NOT NULL CHECK (horizon_min IN (0,15,30,60)),
  demand_pred    DOUBLE PRECISION NOT NULL,
  model_version  TEXT,
  CONSTRAINT fk_forecasts_site FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX idx_forecasts_site_target ON forecasts(site_id, target_ts);

CREATE TABLE recommendations (
  id               BIGSERIAL PRIMARY KEY,
  site_id          TEXT NOT NULL,
  ts               TIMESTAMPTZ NOT NULL,
  mode             TEXT NOT NULL CHECK (mode IN ('two_phase','four_phase_nema')),
  cycle_s          DOUBLE PRECISION,
  ns_green         DOUBLE PRECISION,
  ew_green         DOUBLE PRECISION,
  delay_est_s      DOUBLE PRECISION,
  component_json   JSONB,
  CONSTRAINT fk_recs_site FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX idx_recs_site_ts ON recommendations(site_id, ts);

CREATE TABLE audit_log (
  id         BIGSERIAL PRIMARY KEY,
  ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  user_id    INTEGER,
  username   TEXT,
  role       TEXT,
  action     TEXT NOT NULL,
  resource   TEXT NOT NULL,
  payload    JSONB,
  ip         INET,
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX idx_audit_ts   ON audit_log(ts);
CREATE INDEX idx_audit_user ON audit_log(user_id);

CREATE TABLE ingest_errors (
  id         BIGSERIAL PRIMARY KEY,
  site_id    TEXT,
  ts         TIMESTAMPTZ NOT NULL,
  source     TEXT NOT NULL,
  reason     TEXT NOT NULL,
  record     JSONB
);
CREATE INDEX idx_ingest_errors_ts ON ingest_errors(ts);

CREATE TABLE system_metrics (
  id               BIGSERIAL PRIMARY KEY,
  site_id          TEXT,
  ts               TIMESTAMPTZ NOT NULL,
  module           TEXT NOT NULL,
  fps              DOUBLE PRECISION,
  uptime_s         DOUBLE PRECISION,
  frames_dropped   INTEGER,
  latency_ms       DOUBLE PRECISION,
  mem_mb           DOUBLE PRECISION,
  CONSTRAINT fk_metrics_site FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX idx_metrics_module_ts ON system_metrics(module, ts);
```
