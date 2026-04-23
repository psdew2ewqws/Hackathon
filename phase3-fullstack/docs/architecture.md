# Phase 3 — System Architecture

Integrated, single-site traffic-intelligence stack covering every mandatory
module from the hackathon handbook §8. One FastAPI process hosts the tracker,
the signal simulator, the event engine, and the REST/WebSocket API; a React
SPA (Vite) is the operator dashboard; SQLite is the durable store.

## Topology

```
                    +-----------------------+
                    |  wadi_saqra_*.mp4     |  (archived field capture)
                    +-----------+-----------+
                                |  ffmpeg  -re  -stream_loop -1
                                v
               +--------------------------------+
               |  MediaMTX  (phase3/bin)        |  rtsp://127.0.0.1:8554/wadi_saqra
               +----------------+---------------+
                                |
                                v
 +------------------------------+----------------------------+
 |                FastAPI process (uvicorn :8000)            |
 |                                                           |
 |  +-----------+   +-----------+   +-----------+            |
 |  | Tracker   |-->| Counters  |-->| Event     |---+        |
 |  | (YOLO +   |   | (zones +  |   | Engine    |   |        |
 |  | ByteTrack)|   | stop-line)|   | §6.6 x6   |   |        |
 |  +-----+-----+   +-----------+   +-----------+   |        |
 |        |                                         |        |
 |        v                                         v        |
 |  +-----------+   +-----------+            +-----------+   |
 |  | Signal    |-->| Fusion +  |----------->| Storage   |   |
 |  | Simulator |   | Webster   |            | Sink      |   |
 |  +-----------+   +-----------+            |(batched)  |   |
 |                       ^                   +-----+-----+   |
 |                       |                         |         |
 |                 +-----+------+                  v         |
 |                 |   gmaps    |             +----------+   |
 |                 |   NDJSON   |             | SQLite   |   |
 |                 +------------+             | (WAL)    |   |
 |                                            +----------+   |
 |                                                           |
 |  Auth (HS256 + bcrypt)   REST+WS   RBAC (viewer/op/admin) |
 +-----------------------------------------------------------+
                                |
                                v
                    +-----------------------+
                    |  React SPA (Vite)     |
                    |  pages: Live, Signal, |
                    |  Forecast, Incidents, |
                    |  System, Audit, ...   |
                    +-----------------------+
```

## Modules

**Data Acquisition (handbook §8.1).** `MediaMTX` single binary accepts an
RTSP publisher on `:8554/wadi_saqra`; `phase3-fullstack/scripts/run_rtsp.sh`
loops the archived 1080p capture through `ffmpeg -re -stream_loop -1` so the
stack always has a deterministic "live" source. The tracker opens the stream
via OpenCV `CAP_FFMPEG`; on grab failure it releases and reconnects after
500 ms (tracker.py lines 127–135).

**Tracker (`poc_wadi_saqra/tracker.py`).** Threaded. Runs Ultralytics
`YOLO.track()` with ByteTrack at 10 FPS ingest on 960-pixel frames, filtered
to COCO vehicle classes `{2, 3, 5, 7}`. Exposes a `TrackerState` snapshot
(counts, FPS, last annotated JPEG) consumed by `/mjpeg` and `/api/counts`,
and two callback hooks: `on_frame` (per-frame, used by the event engine) and
`on_bin` (every 15 s, used by fusion + storage).

**Counters (`counters.py`).** Stateless per-tick: `ApproachCounter` tracks
zone containment (point-in-polygon) and directional stop-line crossings
(`segments_cross` + sign of velocity vector against the zone's
`direction_of_travel`). Zones live in `configs/wadi_saqra_zones.json`.

**Event Engine (`events.py`).** Six detectors: `congestion_class_change`
(hysteresis 5 s), `queue_spillback` (≥20 in-zone for ≥10 s),
`abnormal_stopping` (stationary during green), `stalled_vehicle`
(stationary >20 s), `wrong_way` (velocity dot-product vs expected <
−0.30), and composite `incident` promotion when primitives co-occur within
30 s on the same approach. Writes NDJSON to `data/events.ndjson` and pushes
to the storage sink.

**Signal Simulator (`signal_sim.py`).** Two modes:

1. **Free-run 2-phase** (legacy default): wall-clock cycle
   NS → yellow → all-red → EW → yellow → all-red, 35/35/3/2 = 80 s cycle.
2. **Video-anchored 3-phase** (active when `signal.video_anchor` is present
   in the site config): cycle is NS → E → W, each 35 s green + 3 s yellow
   + 2 s all-red = 120 s. The current phase is computed on every tick from
   `video_ts = (now − ffmpeg_start) % video_duration` offset by the
   user-observed anchor (`{video_ts_seconds, phase_name, signal_state}`).
   The `ffmpeg_start` timestamp is written atomically by `run_rtsp.sh`
   to `data/ffmpeg_start.txt` before `ffmpeg -re -stream_loop -1` is exec'd.
   This keeps the dashboard's NS/E/W lights in exact lockstep with the
   recorded video — useful for demos and for validation against
   ground-truth phase transitions.

Both modes emit handbook-schema events on every phase transition to NDJSON
+ WebSocket + storage sink. Offline 24 h log generator:
`scripts/build_signal_timing_log.py`.

**Fusion + Webster (`fusion.py`).** `fuse()` combines tracker bin counts,
in-zone queue length and a gmaps congestion row into a per-approach pressure
score (`demand_per_min + 0.5·queue·(1 + gmaps_penalty)`). Two Webster variants
are shipped: `webster_two_phase()` for NS+EW combined, and
`webster_three_phase()` for the real Wadi Saqra geometry (NS + E alone + W
alone). Both consume `_phase_flow_ratio_hcm()`, which computes the phase
flow ratio y = max-across-approaches of `arrival_rate_veh_min /
(saturation_flow_per_min × lane_count)` — HCM default 30 veh/min/lane × 2
lanes = 60 veh/min per approach. Arrival rate falls back to a queue proxy
(`in_zone × 60 / cycle_seconds`) when the approach is red and
`demand_per_min` reads zero. A `near_saturation` flag is raised whenever
Y ≥ 0.85 or when the Webster-optimal plan would increase uniform delay —
in that regime the recommender echoes the field plan (no negative
improvements ever surface in the dashboard).
`forecast_per_approach()` anchors on the gmaps target-hour row and augments
with a capped live multiplier (0–0.5) so gmaps remains the prior even when
the camera is quiet.

**Forecast Bridge (`src/forecast_ml/`).** Offline trainer
`forecast-ml-train` produces a LightGBM bundle at
`models/forecast_lgb.json` (4 horizons × 1 model = 4 boosters in one JSON).
`models/forecast_metrics.json` records the last run: MAE 6.10–6.36 veh/15 min
across horizons vs persistence baseline 12.2–41.8. Twelve features:
5 lags, 4 calendar sin/cos, is_weekend, green_active_frac, detector_code.

**Storage (`storage/`).** `db.py` wraps SQLite in WAL mode with FK
enforcement and per-thread connections. `schema.sql` defines 11 tables (see
`data-model.md`). `sinks.py` implements a daemon `StorageSink` that
batches queue records into 1 s / 200-row transactions — producers call
`push(kind, row)` without blocking the hot path.

**Auth (`auth/`).** `jwt_service.py` mints HS256 tokens with 30-minute TTL
(`TRAFFIC_INTEL_JWT_SECRET`, `TRAFFIC_INTEL_JWT_TTL_MIN`). `users.py`
stores bcrypt-hashed passwords in SQLite; `ensure_default_users()` seeds
`viewer` / `operator` / `admin` from env vars on first boot. `deps.py`
provides `get_auth_context` and `require_role("admin")` FastAPI
dependencies used by privileged endpoints (audit log, event demo emitter).
The `JwtService` instance is cached in a module-level `_service` singleton
built lazily by `_svc()` — both the login endpoint (via `make_service()`)
and every request passing through `get_auth_context` share the same
`JwtService`, so tokens minted on login verify cleanly inside the
dependency. **`TRAFFIC_INTEL_JWT_SECRET` must be pinned in the environment
before `uvicorn` starts**; otherwise `make_service()` falls back to a
per-process random secret and every process restart invalidates all
outstanding tokens.

## Data flow (happy path)

1. `ffmpeg` loops the archived mp4 into MediaMTX.
2. Tracker `CAP_FFMPEG` pulls a frame, YOLO + ByteTrack label vehicles.
3. Counters resolve zone membership + stop-line crossings.
4. Per-frame callback pushes tracks into the event engine (frame-level
   detectors: abnormal_stopping, stalled_vehicle, wrong_way).
5. Every 15 s the tracker emits a `bin_record`; the same record drives
   fusion (which joins with the gmaps row for the configured hour) and
   feeds the bin-level event detectors (congestion_class_change,
   queue_spillback).
6. Fusion output is consumed by `webster_two_phase()` on every
   `/api/recommendation` request and by `forecast_per_approach()` on
   `/api/forecast?hour=...`.
7. All producers push to `StorageSink`, which writes SQLite in batches.
8. The React SPA polls REST every 1–2 s and subscribes to
   `/ws/counts`, `/ws/signal`, `/ws/events` for low-latency updates.

## Fault-handling paths

Every producer in the pipeline has a defined failure mode and recovery path.
The goal is "degrade visibly, never crash silently":

| Producer            | Failure                         | Detection                                          | Recovery                                                                                   |
|---------------------|---------------------------------|----------------------------------------------------|--------------------------------------------------------------------------------------------|
| RTSP source         | Publisher drops / MediaMTX restart | `cap.read()` returns False                      | Tracker releases the capture, sleeps 500 ms, re-opens with `CAP_FFMPEG`. `last_error` propagates to `/api/health`. |
| YOLO inference      | Model unload / CUDA OOM          | Exception in `.track()`                           | Tracker logs, marks `last_error`, sleeps 1 s, retries. `running=False` visible on the dashboard. |
| Event engine        | Per-detector exception            | Try/except around each detector invocation        | Exception logged with event context; other detectors keep firing; composite-incident re-evaluates next tick. |
| Signal simulator    | Stale `ffmpeg_start.txt`          | File read returns `None` (missing/empty/malformed) | Simulator sleeps 250 ms and retries — no transitions emitted until the anchor is readable.  |
| Storage sink        | SQLite contention / IO error      | `INSERT` raises, batch is returned to queue       | Daemon logs, sleeps 250 ms, retries. Queue depth is surfaced at `/api/health → sink_queue`. |
| Auth / JWT          | Expired or tampered token         | `JwtService.decode` raises                        | Endpoint returns 401 with a structured detail; frontend clears `localStorage` and routes to `/login`. |
| WebSocket           | Client disconnects                | `websocket.send_json` raises                      | Broadcaster drops the client from its set; producers never block on a dead socket.         |

Backpressure is monitored, not tolerated silently: when `sink_queue` exceeds
a high-water mark the dashboard health chip flips yellow, and the tracker
still reports its FPS so the operator can see that ingestion, not inference,
is the bottleneck.

## System monitoring paths

| Surface                       | Source                                                                          | Sampling rate        |
|-------------------------------|---------------------------------------------------------------------------------|----------------------|
| `/api/health`                 | `tracker.state`, `signal_sim.state.running`, SQLite row counts, sink queue depth | on every GET          |
| `/api/ingest/metrics`         | `acquisition/metrics.py`                                                         | live counters         |
| `/api/ingest/errors`          | recent error records (admin-gated)                                               | last 200 errors       |
| `/api/forecast/ml/metrics`    | `models/forecast_metrics.json` (written by last train)                           | on read               |
| `/ws/counts`                  | tracker bin-close events                                                         | every 15 s            |
| `/ws/signal`                  | signal-simulator phase transitions                                               | per phase change      |
| `/ws/events`                  | event engine                                                                     | per event             |
| `/api/audit/log` (admin)      | `storage.audit_log` rows                                                         | last 200 entries      |
| Dashboard "System Health" strip | `/api/ingest/metrics` + `/api/health`                                          | 1 Hz poll             |

Any judge can `curl` the health + metrics endpoints from a read-only JWT and
observe the pipeline's liveness without privileged access.

## Multi-site scale plan

The system was built as a PoC against a single intersection but the data
model is already site-scoped. Scaling to N intersections is a structural
refactor, not a rewrite:

1. **Config**: one JSON per site under `configs/sites/<site_id>.json` (same
   schema as today's `wadi_saqra.json`). A top-level
   `configs/sites.index.json` lists the enabled sites.
2. **Storage**: no schema change — every row already carries
   `intersection_id`; a compound index `(intersection_id, ts)` keeps reads
   cheap.
3. **Process layout**: one `TrackerConfig` → one `Tracker` + one
   `SignalSimulator` + one `EventEngine` instance per site, all inside a
   single `uvicorn` process. When a site exceeds ~25 % CPU we shard into
   one uvicorn per site behind a lightweight reverse proxy; nothing else
   changes.
4. **API**: existing endpoints gain an optional `?site_id=…` query param.
   A new `/api/sites` endpoint lists configured sites, their RTSP URL, and
   live health.
5. **Dashboard**: a site selector in the Nav (stub already present) is
   populated from `/api/sites`; every panel filters on the active site.
   Switching sites is a client-side state change, no reload required.
6. **Forecaster**: per-site LightGBM model files
   (`models/forecast_lgb_<site_id>.json`); the bridge picks the model by
   `site_id`. Training script accepts `--site` flag.
7. **gmaps ingestion**: per-site NDJSON, corridor definitions per-site,
   already supported via `gmaps.typical_ndjson` in the site config.

## Data flow (diagram)

```mermaid
flowchart LR
    subgraph Acq[Acquisition]
        MP4[wadi_saqra_*.mp4] -->|ffmpeg -re -stream_loop -1| MM[MediaMTX :8554]
        MM -->|RTSP| TRK[Tracker<br/>YOLO26 + ByteTrack]
        FFSTART[[ffmpeg_start.txt]] -.-> SIG
    end

    subgraph Core[FastAPI :8000]
        TRK --> CNT[Counters]
        TRK --> EV[Event Engine<br/>6 detectors §6.6]
        CNT --> FUS[Fusion]
        GMAPS[[gmaps NDJSON]] --> FUS
        FUS --> WEB[Webster 2-phase / 3-phase]
        SIG[Signal Simulator<br/>video-anchored] --> SSINK
        EV --> SSINK[Storage Sink<br/>batched]
        CNT --> SSINK
        FUS --> SSINK
        SSINK --> DB[(SQLite WAL)]
        FCML[LightGBM Forecast<br/>+0/+15/+30/+60] --> FUS
    end

    subgraph API[REST + WS]
        WEB --> REC[/api/recommendation/]
        FCML --> FAPI[/api/forecast*/]
        CNT --> CAPI[/api/counts/] --> WS[/ws/counts/]
        SIG --> SAPI[/api/signal/*/] --> WSS[/ws/signal/]
        EV --> EAPI[/api/events/] --> WSE[/ws/events/]
        DB --> HAPI[/api/history*/]
        HEALTH[/api/health/] <-- TRK & SIG & SSINK & DB
    end

    subgraph UI[React SPA /app/]
        LIVE[Live page<br/>video+cards+6 panels]
        OTHER[Signal · Forecast · Incidents · History · System · Audit]
    end

    REC & FAPI & CAPI & SAPI & EAPI & HAPI & HEALTH --> LIVE
    WS & WSS & WSE --> LIVE
```

## Cross-references

- Source entry point: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/server.py`
- Schema: `phase3-fullstack/src/traffic_intel_phase3/storage/schema.sql`
- Auth wiring: `phase3-fullstack/src/traffic_intel_phase3/auth/{jwt_service,users,deps}.py`
- Frontend routes: `frontend/src/App.tsx` (Live, Signal, Forecast, Incidents,
  System, Audit, History, Signal Timing)
- Site + signal config: `phase3-fullstack/configs/wadi_saqra.json`
- Zones polygon: `phase3-fullstack/configs/wadi_saqra_zones.json`
- Stack launch scripts: `phase3-fullstack/scripts/run_rtsp.sh`,
  `phase3-fullstack/bin/mediamtx`
