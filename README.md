# Traffic-Intel — AI Traffic Intelligence for Wadi Saqra

**9XAI Hackathon build.** A full-stack traffic intelligence PoC for the Wadi Saqra intersection in Amman, Jordan. Live CV detection on an RTSP feed, LightGBM demand forecasting, Google-anchored congestion priors, Webster/HCM signal-timing advisory, and an operator-facing React dashboard — all running on a single port with JWT auth and three-role access control.

![Traffic-Intel dashboard](docs/screenshots/02-live.png)

## Demo video

[![Demo video — Wadi Saqra intersection](docs/screenshots/00-video-thumb.jpg)](https://drive.google.com/file/d/1vpw6lIn0ct4-ef6or116nyXB9KHvUT4v/view?usp=drive_link)

Click the thumbnail → Google Drive (≈ 2 min walkthrough of the live app).

## What's new in this batch

This commit lands a sizable production-readiness upgrade. The plan file lives at
`docs/superpowers/specs/2026-05-03-rfdetr-detector-swap-design.md` plus the
broader `~/.claude/plans/3-1-vehicle-detection-gentle-seahorse.md`.

- **Detector swap**: pluggable backend (YOLO ↔ RF-DETR) with a one-click toggle in the dashboard. RF-DETR class IDs are the 91-class COCO space (off-by-one from YOLO's 80-class) — the backend now overrides the broken `class_name` field with a canonical lookup so labels stay correct (`car` not `motorcycle`).
- **PCE-aware counts**: every count now carries an HCM 6th-edition Passenger Car Equivalent. Pressure formula moved from raw vehicles to PCE-units. Per-class breakdown (`mix`) shipped through `/api/counts`, `/api/fusion`, the dashboard cards, and the 15-second bin NDJSON schema.
- **Per-lane subdivision**: lanes induced from ByteTrack trajectories using approach-conditioned Fréchet-distance + DBSCAN clustering. Operator can hand-edit polygons in the new `/lanes` page (canvas-based polygon editor: click-to-add, drag-to-move, right-click delete). Webster's saturation-flow math now consumes measured per-approach lane counts instead of a hardcoded value.
- **Camera-motion homography**: ORB+RANSAC tracks the camera per frame and warps saved lane polygons into current-frame coords so they stay glued to road features even as the camera drifts. Trajectory pre-filter drops near-stationary tracks (`min_displacement_px=120`) to remove queue bias from clustering.
- **Dedicated `/chat` page + MCP server**: full-screen chat UI with conversation sidebar and markdown rendering (uses the existing 7-tool LLM advisor). The same 7 tools are also exposed as a stdio MCP server at `python -m traffic_intel_mcp` so external clients (Claude Desktop, Cursor, agents) can use them. Drop `.mcp.json.example` into Claude Desktop's config to connect.
- **Drift monitoring + measurement harness**: `observability/drift.py` runs 4 drift checks (FPS, signal-log freshness, model age, class-mix KL) and emits `drift_alert` incidents. `scripts/measure_counts.py` produces MAE/recall against a hand-labeled clip. `scripts/bench_detectors.py` produces a side-by-side detector benchmark.
- **Tests**: 148 green (was 111). New: PCE counter, fusion PCE units, Webster lane_count, trajectory buffer, lane induction (Fréchet, DBSCAN, lane-type inference), per-lane counter, MCP server tool registration.

## What's shipped

| Module | Status | Notes |
|---|---|---|
| RTSP ingest (MediaMTX + ffmpeg push loop) | ✅ | Source clip → `rtsp://127.0.0.1:8554/wadi_saqra` |
| **Pluggable detector: YOLO ↔ RF-DETR** | ✅ NEW | One-click toggle in the dashboard. YOLO uses 80-class COCO IDs; RF-DETR uses 91-class with a corrected label table (otherwise everything was off-by-one: car→motorcycle, bus→train) |
| ByteTrack multi-object tracker (external) | ✅ | One tracker class shared by both backends so the comparison is detector-vs-detector, not detector+tracker-vs-detector+tracker |
| **PCE-aware counting** (HCM 6th ed.) | ✅ NEW | car=1.0, motorcycle=0.4, truck=1.5, bus=2.0; `pressure` formula now in PCE-units, `mix` per-class breakdown surfaces in dashboard cards |
| **Per-lane subdivision** | ✅ NEW | Lanes induced from ByteTrack trajectories (Fréchet + DBSCAN, displacement-filtered to remove queue bias). Operator can hand-edit polygons in `/lanes` |
| **Camera-motion homography** | ✅ NEW | ORB+RANSAC keeps saved zone/lane polygons glued to road features even when the camera drifts (ported from phase 2's `CameraTracker`) |
| SQLite store (counts, signals, incidents, audit, **forecasts**, **forecast_score**, **controller_runs**) | ✅ | 10k+ count rows, 7k+ incidents, 3k+ signal events seeded |
| LightGBM 15-min demand forecast (+now/+15/+30/+60) | ✅ | MAE 6.1–6.4 veh vs. 12–42 persistence baseline; **every prediction now persisted** to `forecasts` for forecast-vs-actual scoring |
| Google Maps typical-day congestion prior | ✅ | Read-only NDJSON snapshot, not live API |
| Webster 1958 + HCM Ch. 18 signal-timing advisor | ✅ | Advisory only; **now uses measured per-approach lane counts** instead of a hardcoded `lane_count=2` |
| 3-phase field-observed signal sim (NS → E → W) | ✅ | Video-anchored at `video_ts=23s` when E opens |
| FastAPI + JWT + 3 roles (viewer/operator/admin) | ✅ | HS256, bcrypt, pinned secret via env |
| React SPA served at `/app/` | ✅ | Single-port deploy; dev mode optional on `:3000` |
| **Dedicated `/chat` page (LLM advisor)** | ✅ NEW | Full-screen layout, conversation sidebar, markdown rendering. Reuses the existing 7-tool dispatch and SSE streaming |
| **MCP server (`python -m traffic_intel_mcp`)** | ✅ NEW | Exposes the same 7 tools as a stdio MCP server so Claude Desktop / Cursor / external agents can use them. See `.mcp.json.example` |
| MJPEG annotated stream at `/mjpeg` | ✅ | Per-class boxes (car/truck/bus/motorcycle), tracker IDs, lane labels, HUD with per-approach counters and the active detector backend |
| Incident detection (wrong-way, stopped, spillback) | ✅ | 7k+ seeded, classifier verdicts in `data/labels/`. **`drift_alert` event type now exposed** via `EventEngine.emit_drift_alert()` |
| **Drift monitor (4 checks)** | ✅ NEW | detector FPS, signal-log freshness, model age, class-mix KL — all wired to emit `drift_alert` incidents through the existing event engine |
| **Ground-truth measurement harness** | ✅ NEW | `scripts/measure_counts.py` compares automated counts against a hand-labeled clip (MAE/MAPE/per-class recall) |
| **Side-by-side detector benchmark** | ✅ NEW | `scripts/bench_detectors.py` runs all backends over the same window, dumps `summary.csv` + per-backend annotated MP4 |
| Isolation proof (no outbound writes) | ✅ | `scripts/assert_no_outbound_writes.sh`, CI-style gate |
| Test coverage | ✅ | **148 tests green** (pytest) — counter PCE / lanes, fusion lane_count, lane induction, trajectory buffer, MCP server tool registration, plus the existing event / auth / storage / Webster suite |

## Screenshots

### Login — bcrypt-checked, JWT issued, role embedded in claims
![Login](docs/screenshots/01-login.png)

### Signal Timing — Webster + HCM what-if simulator
![Signal Timing](docs/screenshots/03-signal-timing.png)

### Forecast — 24h pressure heatmap + Webster plan delta
![Forecast](docs/screenshots/04-forecast.png)

### History / Analysis — connects live detection → forecast → recommendation
![History](docs/screenshots/05-history.png)

## Quickstart

```bash
# 1. Launch everything (MediaMTX, ffmpeg RTSP push, uvicorn, tracker, signal sim)
bash phase3-fullstack/scripts/run_full_stack.sh

# 2. Open the SPA
xdg-open http://localhost:8000/app/

# 3. Sign in
#    admin / admin123      — full access
#    operator / operator123 — dashboard + forecasts + recommendations
#    viewer / viewer123     — read-only live view
```

Everything lives on **`http://localhost:8000`**:

| Path | Purpose |
|---|---|
| `/app/` | React SPA (login, live dashboard, signal-timing sim, forecast, history) |
| `/mjpeg` | Annotated MJPEG stream from the tracker |
| `/api/health` | Tracker FPS, queue depth, storage row counts |
| `/api/auth/login` | POST `{username, password}` → `{token, role, expires_at}` |
| `/api/signal/current` | Current phase, cycle, video-anchor debug fields |
| `/api/forecast/ml` | LightGBM per-approach demand forecast |
| `/api/recommendation` | Webster/HCM advisory plan vs. current |
| `/api/incidents` | Last-24h event stream (wrong-way, stopped, spillback, …) |
| `/api/system/isolation` | Read-only sources + outbound-writes assertion |

OpenAPI at `http://localhost:8000/openapi.json`.

## Architecture

```
RTSP feed (MediaMTX :8554)
        │
        ▼
  ┌─────────────────┐
  │  YOLOv8 + BoT-SORT (tracker)
  │  → zone crossings per approach
  └──────┬──────────┘
         │                 ┌───────────────────────────────┐
         ▼                 │ Google Maps typical-day (NDJSON, read-only)
  ┌────────────┐           └───────────────┬───────────────┘
  │   SQLite   │◀──────────────────────────┘
  │ counts · signals · incidents · audit
  └──┬─────────┬────────────┬──────────────┐
     ▼         ▼            ▼              ▼
   /mjpeg   /api/*   LightGBM forecast   3-phase signal sim
                         (.pkl)           (video-anchored)
                             │
                             ▼
                    Webster 1958 + HCM Ch. 18
                    delay model (advisory only)
                             │
                             ▼
                     React SPA /app/
                     (JWT · 3 roles)
```

Deeper docs:
- [Phase-3 architecture](phase3-fullstack/docs/architecture.md)
- [Algorithms (Webster/HCM, LightGBM, BPR-scaling)](phase3-fullstack/docs/ALGORITHMS.md)
- [Security & isolation model](phase3-fullstack/docs/security_and_isolation.md)
- [Handbook deliverable mapping](phase3-fullstack/docs/HANDBOOK_DELIVERABLE.md)

## Principles

- **Read-only toward operational infrastructure** — no control commands ever, per handbook §11. `scripts/assert_no_outbound_writes.sh` is the gate.
- **Reproducible** — one command launches the full stack from a clean checkout.
- **Open-source only** — MIT / Apache / AGPL-3.0 components; no paid lock-in (handbook §11).
- **Typed contracts** — every API payload has a `frontend/src/api/types.ts` definition.

## Licenses

Application code: MIT. See `phase1-sandbox/methodology.md` for the full open-source component list and their individual licenses (YOLOv8 = AGPL-3.0, MediaMTX = MIT, LightGBM = MIT, FastAPI = MIT, …).

## Phases

| Phase | Status | Dir | Purpose |
|---|---|---|---|
| 1. Sandbox | ✅ | [`phase1-sandbox/`](phase1-sandbox/) | Simulated feeds, SUMO scenarios, synthetic datasets |
| 2. Feasibility | ✅ | [`phase2-feasibility/`](phase2-feasibility/) | YOLOv8 detection, forecasting, dashboard quick builds |
| **3. Full-Stack** | ✅ **shipped** | [`phase3-fullstack/`](phase3-fullstack/) | Integrated live system — this README's subject |
