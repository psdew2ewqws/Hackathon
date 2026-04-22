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

**Signal Simulator (`signal_sim.py`).** Wall-clock 2-phase cycle (NS →
yellow → all-red → EW → yellow → all-red). `CurrentPlan` defaults to
35/35/3/2 = 80 s cycle, sourced from `configs/wadi_saqra.json
→ signal.current_plan`. Emits a handbook-schema event on every phase
transition to NDJSON + WebSocket + storage sink. Offline 24 h log generator:
`scripts/build_signal_timing_log.py`.

**Fusion + Webster (`fusion.py`).** `fuse()` combines tracker bin counts,
in-zone queue length and a gmaps congestion row into a per-approach pressure
score (`demand_per_min + 0.5·queue·(1 + gmaps_penalty)`). `webster_two_phase()`
applies Webster's formula to emit a recommended cycle and NS/EW green split,
compared against the field-observed current plan (uniform delay model).
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
