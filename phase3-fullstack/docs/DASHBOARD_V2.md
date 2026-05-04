# Dashboard v2 — Architecture

`/app/dashboard` is a re-imagined operator console that ships alongside the
existing `/app/` Live page. The Live page stays untouched (it's the operator
calibration surface — MJPEG editing, lane drawing, zone redraw); the v2
dashboard is the **monitoring + decision-support** surface.

## Routing & shell

| | Live page (`/app/`) | Dashboard v2 (`/app/dashboard`) |
| --- | --- | --- |
| Top nav | Global green-pill `Nav.tsx` | Custom `OperatorTopBar` |
| Width | Centered, max 1280 | Full-bleed (no max-width cap) |
| Aesthetic | Phase-2 inherited | Geist + Geist Mono, dotted-grid bg |
| Primary use | Calibration, edits, deep tabs | Monitoring, advisor, forecast |

The `Shell` in `frontend/src/App.tsx` hides `<Nav>` when `pathname ==
'/dashboard'` so the operator topbar doesn't clash. `<AdvisorDrawer>` stays
visible on both.

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ OperatorTopBar (sticky, 48px)                                    │
│ Brand · Nav · DET · FPS · PHASE · clock · user                   │
├────────────────────────────────────┬──────────────────────────────┤
│ LiveFeedPanel                      │ AIStackPanel                 │
│ MJPEG, scanlines, telemetry strip  │ 6 models, live console       │
├────────────────────────────────────┴──────────────────────────────┤
│ AIPipelineStrip                                                   │
│ RTSP → detect → track → counts → fuse → forecast → optimise → advise │
├────────────────────────────────────┬──────────────────────────────┤
│ LiveKpiRow (4 approaches)          │ LiveSignalState              │
│ Pressure index 30px Geist bold     │ NS / E / W phase progress    │
├───────────────────────────────────────────────────────────────────┤
│ HeatmapPanel · 48 × 4 gmaps grid                                  │
├────────────────────────────────────┬──────────────────────────────┤
│ ForecastStrip                      │ WebsterBar                   │
│ 4 corridor sparklines, +60 delta   │ Current vs Webster, delay Δ  │
├────────────────────────────────────┼──────────────────────────────┤
│ LiveEventsPanel                    │ RecentSignalPanel            │
│ §6.6 incidents                     │ Signal log                   │
├───────────────────────────────────────────────────────────────────┤
│ AdvisorChatPanel · embedded Claude/MCP chat                       │
└───────────────────────────────────────────────────────────────────┘
```

## Components

All under `frontend/src/components/v2/`. Each polls its own endpoints; no
shared store.

| Component | Endpoints | Polling |
| --- | --- | --- |
| `OperatorTopBar.tsx` | `/api/tracker/backend`, `/api/health`, `/api/signal/current` | 2 s |
| `LiveFeedPanel.tsx` | `/mjpeg`, `/api/health`, `/api/tracker/backend` | 2 s |
| `AIStackPanel.tsx` | `/api/tracker/backend`, `/api/forecast/ml`, `/api/health`, `/api/llm/status`, `/api/recommendation` | 2 s |
| `AIPipelineStrip.tsx` | `/api/health` | 2.5 s |
| `LiveKpiRow.tsx` | `/api/fusion` | 1 s |
| `LiveSignalState.tsx` | `/api/signal/current` | 0.4 s + 100 ms render tick |
| `HeatmapPanel.tsx` | `/api/heatmap` | once + manual refresh |
| `ForecastStrip.tsx` | `/api/forecast/ml` | 60 s |
| `WebsterBar.tsx` | `/api/recommendation` | 1 s |
| `LiveEventsPanel.tsx` | `/api/events?limit=20` | 2 s |
| `RecentSignalPanel.tsx` | `/api/signal/log?limit=24` | 2 s |
| `AdvisorChatPanel.tsx` | `/api/llm/status`, `/api/llm/chat` (SSE) | event-driven |

## AI inference console (the "go all in" panel)

`AIStackPanel.tsx` replaces what was a vertical list of cards with a single
dense console where every model has its own visualisation:

1. **Detector battle** — 2-column showdown (RF-DETR vs YOLO 26n). Each card
   shows mAP / size / latency as horizontal bars (latency bar is inverted —
   shorter fill = faster). The active backend gets an amber `IN USE` ribbon
   and the switch button is disabled. The other side has an active "switch
   to this" button that POSTs to `/api/tracker/backend` (operator role).
2. **Tracking** — single dense row with a 30-sample fps sparkline (live
   history kept in a `useRef`).
3. **Forecast** — same row layout, but the spark slot shows per-corridor
   `now → +60` deltas with `↑↓→` arrows tinted by direction.
4. **Optimizer** — `current → webster` delay bar with the saved percentage as
   the headline number.
5. **Advisor** — the 8-tool palette as colour-coded chips so the operator
   knows what natural-language questions can be answered.

Each section uses a left-edge accent stripe in its family hue:

| Family | Hue | Var |
| --- | --- | --- |
| Detection | cyan | `--ai` |
| Tracking | amber | `--accent` |
| Forecast | violet | `#a78bfa` |
| Optimizer | green | `--good` |
| Advisor | pink | `#f0a5d4` |

## Typography

`frontend/index.html` loads:
- **Geist** (300/400/500/600/700/800) — display + body
- **Geist Mono** (400/500/600/700) — data, codes, all-caps labels
- **JetBrains Mono** (fallback for Geist Mono)

CSS variables in `frontend/src/index.css`:
- `--display`, `--sans` → both Geist (no editorial serif)
- `--mono` → Geist Mono with JetBrains Mono fallback

Big numbers use `font: 700 30px var(--sans)` with negative letter-spacing.
Tabular nums (`.tabular` utility) on streaming digits.

## Build & test

```bash
cd frontend
npm run build             # tsc -b && vite build
# served from phase3-fullstack/src/.../server.py via StaticFiles mount /app
```

Smoke tests for the v2 surface:
- `curl http://localhost:8000/app/dashboard`     → 200 (SPA fallback)
- `curl http://localhost:8000/api/heatmap`       → 200
- `curl http://localhost:8000/api/fusion`        → 200 (regression for the
  `crossings_pce_in_bin` NULL fix)
- `curl http://localhost:8000/api/forecast/ml`   → 200, `available: true`

## Known limitations

- No mobile/tablet layout — designed for ≥ 1280 px wide.
- The advisor chat doesn't persist the current conversation across page
  refresh (it does persist server-side; the panel just reloads the empty
  state). This is intentional — operators want a fresh slate per shift.
- The `/api/llm/status` 401 you may see in the console is from the
  AdvisorDrawer fetching status without a token; harmless — chat itself
  is authed.
