# Phase 2 — Crack-the-Code Feasibility Build

Real-time vehicle detection + tracking on the Phase 1 RTSP stream, using Ultralytics YOLO26 + built-in BoT-SORT tracker + `roboflow/supervision` overlays.

## Architecture (P2 quick-builds)

```
rtsp://localhost:8554/site1 ─► YOLO26n.pt ─► sv.Detections
                                    │              │
                                    ▼              ▼
                               BoT-SORT      sv.LineZone (stop-line counters)
                                 (tracks)    sv.PolygonZone (queue spillback, etc.)
                                    │              │
                                    ▼              ▼
                          annotated frames   ndjson event log
                           data/annotated/   data/events/phase2.ndjson
```

## Run

**Prereq:** Phase 1 stream must be live.
```bash
make sandbox-up stream-check
```

Then:
```bash
make phase2-detect                      # 30 s by default → annotated mp4 + events ndjson
make phase2-detect PHASE2_SECONDS=120   # 2 min run
make phase2-detect PHASE2_TRACKER=bytetrack.yaml   # switch tracker
make phase2-detect PHASE2_MODEL=yolo26s.pt          # bigger detector
```

Or drive directly:
```bash
.venv/bin/python -m traffic_intel_phase2.detect_track \
    --source rtsp://localhost:8554/site1 \
    --model yolo26n.pt --tracker botsort.yaml \
    --metadata phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \
    --events-out /tmp/p2.ndjson --video-out /tmp/p2.mp4 \
    --max-frames 300
```

## What it writes

| Artifact | Path | Format | Schema |
|---|---|---|---|
| Annotated video | `data/annotated/phase2.mp4` | MP4 | boxes + track IDs + zones + stop-lines |
| Event log | `data/events/phase2.ndjson` | ndjson | `{timestamp, intersection_id, event_type, ...}` |

Event types emitted:
- `run_start` / `run_end` — bookends with config + summary
- `stop_line_crossing` — per approach, as tracked vehicles cross the pixel polyline defined in `site1.json`
- `zone_occupancy` — vehicle count inside each monitoring zone (queue spillback, conflict zone, ped crossing)

## Outputs drive Phase 3

- Forecasting (Phase 3 §8.3) trains on zone-occupancy + stop-line crossing event rates, not raw frame data — so this log is the P2 → P3 handoff.
- Incident detection (§8.2) consumes the same event log and classifies patterns (stalled vehicles, abnormal stops, queue spillback) on top of these primitives.

## Devices

Auto-detects GPU:
- **CUDA**: uses `device=0` (RTX 3060 6GB is enough for yolo26n/s at 10 FPS)
- **No GPU**: falls back to CPU. YOLO26's NMS-free design + edge optimization makes CPU inference ~43 % faster than YOLOv11 per upstream benchmarks.

## Licenses

- [`ultralytics/ultralytics`](https://github.com/ultralytics/ultralytics) — AGPL-3.0
- [`roboflow/supervision`](https://github.com/roboflow/supervision) — MIT
