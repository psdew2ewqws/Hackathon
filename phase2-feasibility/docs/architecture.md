# Phase 2 — System Architecture

> Handbook §7.1 deliverable. Describes every module, the data flow between
> them, the storage and logging layers, the dashboard interaction, the
> fault-handling paths, the system-monitoring paths, and how the design
> scales to additional sites.

## Top-level diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       SOURCE LAYER (read-only)                            │
│                                                                           │
│   ┌──────────────────┐  ┌────────────────────┐  ┌─────────────────────┐  │
│   │ TheVideo.mp4     │  │ data/detector_     │  │ data/signal_logs/   │  │
│   │ (replayed CCTV)  │  │ counts/*.parquet   │  │ *.ndjson            │  │
│   │ §6.1             │  │ §6.3 (synth)       │  │ §6.4 (synth)        │  │
│   └────────┬─────────┘  └─────────┬──────────┘  └──────────┬──────────┘  │
└────────────┼──────────────────────┼─────────────────────────┼────────────┘
             │                      │                         │
             ▼                      │                         │
   ┌─────────────────┐              │                         │
   │ ffmpeg          │              │                         │
   │ -re -stream_loop│              │                         │
   │ → libx264       │              │                         │
   │ → MediaMTX      │              │                         │
   │ rtsp://:8554/   │              │                         │
   └────────┬────────┘              │                         │
            │                       │                         │
┌───────────┼───────────────────────┼─────────────────────────┼────────────┐
│           ▼                       ▼                         ▼            │
│    INGEST + AI LAYER (Phase 2)                                            │
│   ┌────────────────────────────────────────────────────────────────────┐ │
│   │  detect_track.py  (YOLO26X + ByteTrack + supervision)              │ │
│   │  • per-frame detections (cars / trucks / buses / motorcycles)      │ │
│   │  • per-track ID via ByteTrack                                       │ │
│   │  • stop-line crossings  → events.ndjson                            │ │
│   │  • per-lane crossings   → events.ndjson                            │ │
│   │  • zone occupancy       → events.ndjson                            │ │
│   │  • approach occupancy   → events.ndjson (1 Hz)                     │ │
│   │  • snapshot every Nth   → /tmp/traffic-intel-phase2-latest.jpg     │ │
│   │  • MJPEG stream         → http://127.0.0.1:8081/stream.mjpeg       │ │
│   └────────────┬──────────────────────┬──────────────────────────────────┘│
│                │                      │                                   │
│                ▼                      │                                   │
│   ┌────────────────────────┐          │                                   │
│   │  ingest_layer.py        │ ◄────────┘                                  │
│   │  (§7.2 unified service) │                                             │
│   │  • tails 3 sources      │                                             │
│   │  • normalises timestamps│                                             │
│   │  • validates schema     │                                             │
│   │  • re-emits unified bus │                                             │
│   └─────────┬───────────────┘                                             │
└─────────────┼─────────────────────────────────────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    ANALYTICS LAYER (Phase 2 + 3)                         │
│                                                                          │
│  ┌──────────────────┐  ┌────────────────────┐  ┌──────────────────────┐ │
│  │ classifier.py    │  │ forecast_ml/       │  │ forecast/optimize.py │ │
│  │ rule + Pass-B    │  │ LightGBM + LSTM    │  │ Webster + HCM        │ │
│  │ (§6.6 + §7.3)    │  │ (§7.4)             │  │ (§7.5 + §8.3)        │ │
│  │                  │  │ +15 / +30 / +60min │  │ green-time + cycle   │ │
│  └────────┬─────────┘  └─────────┬──────────┘  └──────────┬───────────┘ │
│           │                      │                         │            │
│           ▼                      ▼                         ▼            │
│   incident events       per-detector counts       advisory recs        │
│   + JPEG snapshot       ML forecast JSON          (extend / reduce /   │
│   + queue_length        models/forecast_lgb.txt    cycle / congestion) │
│                         models/forecast_lstm.pt                         │
└────────────┬─────────────────────┬─────────────────────────┬────────────┘
             │                     │                         │
             ▼                     ▼                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   STORAGE + LOGGING LAYER                                │
│                                                                          │
│  data/events/phase2.ndjson      data/incidents/<id>.jpg                  │
│  data/forecast/forecast_day.json + .xlsx + .parquet                      │
│  data/research/gmaps/typical_*.parquet                                   │
│  data/labels/clips_manifest.json   (rule-based annotations)              │
│  data/audit.log                    (read-only access trail, §7.7)        │
│  data/ingest_errors.ndjson         (validation failures)                 │
│  models/forecast_lgb.txt + forecast_lstm.pt                              │
└────────────┬───────────────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    DASHBOARD LAYER (Phase 2 §7.6)                        │
│                                                                          │
│   ┌─ Python BaseHTTP (viewer.py, :8000) ──────────────────────────────┐ │
│   │  /api/health         system uptime + FPS + ingest rate           │ │
│   │  /api/status         RTSP probe                                  │ │
│   │  /api/counts         detector counts                              │ │
│   │  /api/events         signal events                                │ │
│   │  /api/phase2         live YOLO event tail                         │ │
│   │  /api/phase2/crossings per-approach + per-lane crossings         │ │
│   │  /api/forecast       BPR-scaled forecast                          │ │
│   │  /api/forecast/ml    LightGBM forecast (NEW)                      │ │
│   │  /api/forecast/optimize  Webster recommendation                   │ │
│   │  /api/gmaps/now      current Google typical-day state             │ │
│   │  /api/history/counts last-N-day detector trends (NEW)             │ │
│   │  /api/audit          recent dashboard requests (NEW)              │ │
│   │  /, /assets/*        React SPA build                              │ │
│   └────────────────────────────────────┬────────────────────────────┘ │
│                                        │                                │
│   ┌─ React + Vite SPA ───────────────────────────────────────────────┐ │
│   │  VideoPage                                                        │ │
│   │   ├ Live MJPEG (polled /ai-thumb.jpg)                             │ │
│   │   ├ Approach + per-lane crossings + Google state                  │ │
│   │   ├ Day forecast heatmap (4 × 48 grid)                            │ │
│   │   ├ Webster auto-recommend (per-time-slot)                        │ │
│   │   ├ HistoricalPanel (NEW — §7.6)                                  │ │
│   │   └ SystemHealthPanel (NEW — §7.6)                                │ │
│   └─────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

## Modules — single source-of-truth files

| Module | Path | Purpose |
|---|---|---|
| RTSP simulator | `phase1-sandbox/scripts/publish_loop.sh` | ffmpeg -re loop into MediaMTX |
| Synth detectors | `phase1-sandbox/src/traffic_intel_sandbox/synth/detector_counts.py` | Poisson-arrival counts per detector |
| Synth signals | `phase1-sandbox/src/traffic_intel_sandbox/synth/signal_logs.py` | NEMA phase event stream |
| Site metadata | `phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json` | Camera, approaches, stop-lines, zones |
| Calibration | `phase1-sandbox/src/traffic_intel_sandbox/forecast/calibrate.py` | Auto-author forecast_site.json + overlay |
| YOLO + tracker | `phase2-feasibility/src/traffic_intel_phase2/detect_track.py` | YOLO26X + ByteTrack + zones |
| Zones / lines | `phase2-feasibility/src/traffic_intel_phase2/zones.py` | NamedZone / NamedLine / NamedLaneZone / NamedLaneLine |
| Homography | `phase2-feasibility/src/traffic_intel_phase2/homography.py` | Optional camera-motion tracker |
| Classifier | `phase2-feasibility/src/traffic_intel_phase2/classifier.py` | Rule (Pass A) + motion (Pass B) incident classification |
| Ingest layer | `phase2-feasibility/src/traffic_intel_phase2/ingest_layer.py` | Unified validate / normalize / fan-out |
| BPR forecast | `phase1-sandbox/src/traffic_intel_sandbox/forecast/predict.py` | Anchor + Google profile, deterministic |
| ML forecast | `phase3-fullstack/src/forecast_ml/{features,train,predict}.py` | LightGBM + LSTM trained on detector history |
| Webster optimiser | `phase1-sandbox/src/traffic_intel_sandbox/forecast/optimize.py` | Webster cycle + HCM delay + §8.3 advisories |
| Dashboard server | `phase1-sandbox/src/traffic_intel_sandbox/viewer.py` | Python BaseHTTP, JSON + static |
| Dashboard SPA | `frontend/src/pages/VideoPage.tsx` + `components/*.tsx` | React + Vite production build |

## Data flows

### F1 — Live AI loop
```
TheVideo.mp4 → ffmpeg → MediaMTX :8554 → detect_track.py → events.ndjson
                                              │
                                              ├── /tmp/phase2-latest.jpg → /ai-thumb.jpg
                                              └── MJPEG :8081 (debug)
```

### F2 — Forecast loop (per slot)
```
data/detector_counts/*.parquet  ──┐
data/signal_logs/*.ndjson       ──┼─► forecast_ml.features → train.py → models/
calendar (day-of-week)          ──┘                             │
                                                                ▼
T request ─► forecast_ml.predict ─► /api/forecast/ml ──► VideoPage
data/research/gmaps/*.parquet ──► forecast.predict (BPR) ──► /api/forecast
                                              │
                                              ▼
                                  forecast.optimize (Webster) ──► /api/forecast/optimize
```

### F3 — Incident loop
```
events.ndjson ─► classifier.classify_clip
                 ├── Pass A: rules over event aggregates
                 └── Pass B: re-run YOLO with motion check
                              │
                              ▼
                 verdict + JPEG snapshot + queue_length
                              │
                              ▼
                 data/labels/clips_manifest.json
                              │
                              ▼
                 dashboard incident alert
```

## Storage + logging layers

| Layer | Path | Format | Retention | §7.x |
|---|---|---|---|---|
| Replay video | `data/raw/youtube/*.mp4`, `/home/admin1/TheVideo.mp4` | H.264 MP4 | indefinite, gitignored | 6.1 |
| Historical clips | `data/historical/YYYY-MM-DD/*.mp4` | H.264 | 14 days | 6.2 |
| Detector logs | `data/detector_counts/counts_*.parquet` | Parquet zstd | 30 days (after B0) | 6.3, 7.4 |
| Signal logs | `data/signal_logs/signal_*.ndjson` | NDJSON | 30 days | 6.4 |
| Site metadata | `phase1-sandbox/src/.../metadata/site1.example.json` | JSON Schema 2020-12 | versioned in git | 6.5 |
| Annotation manifest | `data/labels/clips_manifest.json` | JSON | append-only | 6.6 |
| Live AI events | `data/events/phase2.ndjson` | NDJSON | rotating, manual prune | 7.3 |
| Incident snapshots | `data/incidents/*.jpg` | JPEG | indefinite | 7.3 |
| ML models | `models/forecast_lgb.txt`, `models/forecast_lstm.pt` | LightGBM text + PyTorch state | versioned in git LFS (or ignored) | 7.4 |
| Forecast outputs | `data/forecast/forecast_day.json` + `.xlsx` + `.parquet` | mixed | overwritten per run | 7.4 |
| Audit log | `data/audit.log` | NDJSON | rotating, max 50 MB | 7.7 |
| Ingest errors | `data/ingest_errors.ndjson` | NDJSON | rotating | 7.2 |

## Dashboard interaction flow

1. User opens `http://127.0.0.1:8000/`
2. SPA mounts → polls in parallel:
   - `/ai-thumb.jpg` every 200 ms (live AI snapshot)
   - `/api/phase2/crossings` every 1.5 s (per-approach counts)
   - `/api/gmaps/now` every 30 s (Google state)
   - `/api/forecast/optimize?t=HH:MM` on time-slider change (debounced 120 ms)
   - `/api/health` every 5 s (system indicators)
   - `/api/forecast` and `/api/forecast/ml` once at mount (day heatmap data)
3. User scrubs time slider OR clicks a heatmap cell → both call `setSimTime()`
   → optimizer re-runs → Webster recommendation auto-updates
4. **No write paths exist from the dashboard to operational systems** — the
   only write the SPA can trigger is the audit-log entry of its own GET
   request

## Fault-handling paths

| Failure | Detected by | Mitigation |
|---|---|---|
| RTSP connection drop | `_healthy()` in viewer.py | UI badge flips to off; phase2 reconnects via ultralytics built-in retry; ffmpeg publisher has `nohup` and auto-restart hint in Makefile |
| YOLO model load fail | first-frame load exception | Process exits with stderr; user re-runs `make phase2-live-bg` |
| Empty / malformed event in phase2.ndjson | `_phase2_crossings()` JSON parse | Line skipped; tolerant aggregator continues |
| Missing forecast data for a slot | `_gmaps_state_now()` empty rows | Nearest-slot fallback (already implemented in viewer.py) |
| Optimiser oversaturation (Y ≥ 1) | `webster_cycle()` guard | Clamps cycle to C_MAX (120 s); UI badge shows "out of range" |
| Snapshot file missing | `/ai-thumb.jpg` returns 503 | `<img>` keeps last frame on screen; SPA shows "stale" tag |
| Ingest layer schema violation | `ingest_layer.validate()` | Record diverted to `data/ingest_errors.ndjson`; main flow continues |
| ML model file missing | `forecast_ml.predict` startup | Falls back to BPR-scaled forecast in `forecast.predict`; UI labels which path is used |
| Camera homography failure | `CameraTracker.update()` returns last-good H | Smoothed identity if too few keypoints; never crashes pipeline |

## System-monitoring paths

- `/api/health` — uptime, RTSP status, YOLO FPS, ingest rate, frames seen
- `/api/audit?n=50` — last N dashboard requests (read-only)
- `/api/status` — RTSP healthcheck (codec, resolution, fps, failures)
- Process logs: `/tmp/traffic-intel-{viewer,phase2,ffmpeg,gmaps}.log`
- `data/ingest_errors.ndjson` — validation failures from ingest layer
- `data/events/phase2.ndjson` mtime → live freshness check

## Multi-site scale considerations

The current design is one-site, but every module is keyed by `intersection_id`
so multi-site is a configuration story, not a refactor:

1. **Site config** — one `forecast_site.json` per intersection under
   `data/sites/<site_id>/`. The viewer would discover sites at startup.
2. **Per-site detect_track** — one process per site, each consuming a different
   RTSP path (`rtsp://localhost:8554/site<N>`); event logs partitioned by
   `intersection_id` field already present.
3. **Per-site ML model** — `models/forecast_lgb_<site_id>.txt`. Training script
   already loops per-detector; extending to per-site is one outer loop.
4. **Per-site Google data** — `data/research/gmaps/<site_id>/typical_*.parquet`.
   `gmaps.py` poller already takes a config file with per-corridor coords;
   a `--site` flag selects which YAML to load.
5. **Dashboard** — add a site selector to the topbar; SPA keys all queries by
   selected site; backend already filters by `intersection_id` on every
   query.
6. **Storage** — `data/sites/<site_id>/{events,forecast,incidents}/` partitioning;
   no schema changes.

Estimated effort to go from 1 site → N sites: **~1 day per dimension**
(config loader, per-site detector, per-site model, dashboard selector).
No core algorithm changes.

## Compliance review (handbook §11)

- ✅ Read-only toward source environments — all GETs from MediaMTX + parquet files
- ✅ No outbound to operational infrastructure — only Google Routes API (paid, separate)
- ✅ Localhost-only binds — see `viewer.py` host default `127.0.0.1`
- ✅ Open-source priority — every dependency is OSS (see `pyproject.toml`)
- ✅ Modular — every module above is independently runnable + testable
- ✅ Multi-site ready — see §"Multi-site scale considerations"

## Handbook §7.1 checklist

- [x] all core system modules → §"Modules" table
- [x] relationships between modules → §"Top-level diagram"
- [x] data flows between modules → §"Data flows" F1/F2/F3
- [x] storage and logging layers → §"Storage + logging layers" table
- [x] dashboard interaction flows → §"Dashboard interaction flow"
- [x] fault-handling paths → §"Fault-handling paths" table
- [x] system monitoring paths → §"System-monitoring paths"
- [x] future scale considerations to additional sites → §"Multi-site scale considerations"
