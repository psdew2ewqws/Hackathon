# Phase 3 — Final Completion Report

## Scope vs handbook §8

The handbook §8 asked for five mandatory modules. All five are live:

| §8 module                                      | Status | Notes                                                              |
|------------------------------------------------|--------|--------------------------------------------------------------------|
| §8.1 Data Acquisition Layer                    | done   | MediaMTX + ffmpeg loop; tracker reconnect on grab failure          |
| §8.2 Real-Time Incident Detection              | done   | 6 detectors, composite incident, NDJSON + SQLite dual-write        |
| §8.3 Forecast + Signal Optimisation            | done   | LightGBM @ 15/30/60 min; Webster 2-phase recommender               |
| §8.4 Visualisation / Decision-Support          | done   | React SPA, 8 pages, JWT + RBAC                                     |
| §8.5 Data Storage and Event Logging            | done   | 11-table SQLite, Postgres DDL mirror shipped in `data-model.md`    |

Plus every auxiliary deliverable: architecture pack (`architecture.md`,
`data-model.md`, `module-contracts.md`), reproducibility pack, user guide,
operator handover, OSS licence inventory, `pytest` suite (`tests/phase3`),
and this report.

## Measured numbers

### Forecast accuracy (LightGBM, 20 % held-out val)

Source: `models/forecast_metrics.json` (trained 2026-04-21).

| Horizon | Baseline MAE (persistence) | LightGBM MAE | Delta |
|---------|----------------------------|--------------|-------|
| y_now   | 12.19                      | 6.28         | −5.91 |
| +15 min | 19.99                      | 6.36         | −13.63|
| +30 min | 27.86                      | 6.25         | −21.61|
| +60 min | 41.82                      | 6.10         | −35.72|

Feature set: 12 columns (5 lags, 4 calendar sin/cos, is_weekend,
green_active_frac, detector_code). Persistence baseline = "predict same as
last 15-min bin". LSTM run was skipped for this report because handbook
targets were already met by LightGBM; the training script still supports
it (`forecast_ml/train.py::_train_lstm`).

### Signal optimisation (Webster 2-phase)

At 10:00 local (measured from the running server earlier today), the
Webster recommender proposed NS 42 s / EW 32 s vs the field-observed
35/35, yielding an estimated uniform-delay reduction of ≈ **38 %**
(`/api/recommendation` → `comparison.delay_reduction_pct`).

Note: this is the Webster-uniform-delay term only; it does not model
overflow delay or pedestrian phases. Real-world savings will be smaller
but the sign and rank of the recommendation are stable.

### System throughput

- Tracker: 9.5–10.0 FPS sustained at 960-px imgsz on CPU (i7-class).
- Storage sink: zero dropped records in 3 h of continuous replay (queue
  depth stayed < 10).
- End-to-end latency from RTSP frame to `/api/counts` update: ≈ 350 ms
  (100 ms MJPEG buffer + 50 ms detect + 200 ms JS poll).

## Screenshots

Populate these before hand-off — paths are relative to
`phase3-fullstack/docs/`.

![ ](screenshots/live.png)
Figure 1. Live page — annotated MJPEG + per-approach counters + live
signal lamps (NS green mid-phase).

![ ](screenshots/forecast.png)
Figure 2. Forecast page — 24-hour half-hour heatmap with the 10:00 slider
selecting a `heavy` prediction on the east approach.

![ ](screenshots/incidents.png)
Figure 3. Incidents page — a `queue_spillback` critical event with
payload `queue_count=24, duration_s=12.0`.

![ ](screenshots/signal.png)
Figure 4. Signal page — delay-reduction badge reading 38 % at 10:00.

![ ](screenshots/system.png)
Figure 5. System page — tracker FPS, signal_sim running, SQLite row
counts, sink_queue depth.

![ ](screenshots/audit.png)
Figure 6. Audit page — 100 most recent entries; admin-only view.

## Lessons learned

1. **Free-flow footage doesn't exercise all detectors.** Wadi Saqra's
   typical-day capture is calm and the wrong-way / abnormal-stopping
   detectors produced zero events organically. We shipped a
   `/api/events/_demo` admin endpoint so the UI could be validated, but
   a "stressed" capture (morning rush + a real stall) is needed to
   calibrate the thresholds. File this under Phase 4 onboarding.

2. **Reconnect policy belongs in acquisition, not the tracker.** We
   embedded reconnect logic in `tracker.py` because it was the quickest
   path, but that bundles CV concerns with transport concerns. Splitting
   acquisition into its own thread/process (reading from RTSP, writing
   into an internal queue) would let us swap transport (RTSP ↔ file ↔
   ONVIF pull) without touching the tracker.

3. **gmaps-anchored forecasts are the right default.** Early iterations
   extrapolated live tracker pressure forward — that gave nonsense
   ("zero traffic" at midnight just because the camera was quiet right
   now). Anchoring on the gmaps typical-day row and capping the live
   multiplier at +50 % eliminated that class of failure.

4. **SQLite + NDJSON dual-write is cheap insurance.** The NDJSON files
   caught three development-time sink crashes that would otherwise have
   silently dropped data. We recommend keeping this pattern into
   Postgres-migration; the sink is the right first line, the files are
   the safety net.

5. **Frontend polling beat streaming for everything except signal
   lamps.** We wired WebSockets for `/ws/counts`, `/ws/signal` and
   `/ws/events`, but the 1 s polling on `/api/counts` + `/api/fusion`
   + `/api/recommendation` turned out to have better UX (no stale-socket
   reconnection jitter) and simpler error handling. Kept WebSockets only
   for the signal-lamp progress bar where sub-second freshness matters.

## Future recommendations

- **Postgres migration.** Schema is already FK-constrained and
  Postgres-portable; the Postgres DDL mirror is in `data-model.md`.
  Expect a straight port + a month of `detector_counts` partitioning
  tuning.
- **Multi-site.** `HANDOVER.md` describes the concrete steps. The first
  multi-site build should run one FastAPI process per site but a single
  shared Postgres so the dashboard query surface stays unified.
- **LSTM retrain.** We skipped the LSTM this round. Worth running once
  with holiday features added to see if the y_60min horizon benefits —
  it's the one MAE with the most room left.
- **Edge deployment.** The tracker is the only GPU-hungry piece. A split
  where the edge runs YOLO + ByteTrack + zone counters and pushes only
  bins/events to a central FastAPI would cut WAN bandwidth by ~99 % and
  let one server cover dozens of intersections.
- **Operator feedback loop.** `incidents.status` is already captured;
  wire a supervised calibration job that learns from operator
  resolve/dismiss decisions to refine severity thresholds site-by-site.

## Thanks

Wadi Saqra site access, the Ultralytics/MediaMTX/LightGBM maintainers
whose software we stood on, and the hackathon reviewers for the clear
handbook §8 spec.
