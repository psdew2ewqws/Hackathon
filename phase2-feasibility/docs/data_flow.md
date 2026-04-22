# Data flow sequences

Companion to `architecture.md` — same flows, but as time-ordered sequences
between components (handbook §7.1 "data flows between modules").

## SQ-1 — Live AI ingest

```
ffmpeg          MediaMTX       detect_track.py         viewer.py        SPA
   │               │                 │                    │              │
   │ frame@15fps   │                 │                    │              │
   ├───RTSP push──►│                 │                    │              │
   │               │                 │                    │              │
   │               │ ◄──RTSP pull────┤                    │              │
   │               │                 │ YOLO26X+ByteTrack  │              │
   │               │                 │ → detections+tracks│              │
   │               │                 │                    │              │
   │               │                 ├─ append events ───►│              │
   │               │                 │   phase2.ndjson    │              │
   │               │                 │                    │              │
   │               │                 ├─ write JPEG snap ──┘              │
   │               │                 │   /tmp/...latest.jpg              │
   │               │                 │                    ▲              │
   │               │                 │  ◄── /ai-thumb.jpg ──── poll 200ms┤
   │               │                 │                    ▲              │
   │               │                 │  ◄─ /api/phase2/crossings  poll 1.5s
```

## SQ-2 — ML forecast lifecycle

```
detector_counts/    forecast_ml.features    forecast_ml.train    LightGBM/LSTM
*.parquet (30 days)        │                        │                  │
       │                   │                        │                  │
       ├──30 files─────────►│                        │                  │
                            │ build feature matrix   │                  │
                            ├────────────────────────►                  │
                            │ X, y                   │                  │
                            │                        │ fit             │
                            │                        ├─────────────────►│
                            │                        │                  │
                            │                        │  models/forecast_lgb.txt
                            │                        │  models/forecast_lstm.pt
                            │                        ◄──────────────────┤
                            │                        │
   GET /api/forecast/ml?t=HH:MM
            │
            ▼
   forecast_ml.predict
            │ load model + assemble features for T
            ▼
   { detector_id: { '+15min': N, '+30min': N, '+60min': N }, ... }
            │
            ▼
   SPA renders next to BPR forecast
```

## SQ-3 — Incident classification

```
events.ndjson      classifier.py        annotated MP4         clips_manifest.json
     │                  │                     │                       │
     ├── Pass A ────────►│                    │                       │
     │  aggregate stats  │                    │                       │
     │                   │ verdict?           │                       │
     │                   │  if normal → done  │                       │
     │                   │  else → Pass B     │                       │
     │                   │                    │                       │
     │                   ├── re-open MP4 ────►│                       │
     │                   │                    │                       │
     │                   │  motion analysis   │                       │
     │                   │  per track         │                       │
     │                   ◄────────────────────┤                       │
     │                   │                                            │
     │                   ├── extract frame at peak ──────► data/incidents/<id>.jpg
     │                   │                                            │
     │                   ├── compute estimated_queue_m                │
     │                   │                                            │
     │                   ├── verdict + snapshot_path + queue ────────►│
     │                   │                                            │
     │                                                                ▼
     │                                                     dashboard alerts list
```

## SQ-4 — Signal-timing recommendation (per slot)

```
SPA (heatmap click)       /api/forecast/optimize       optimize.py        Webster + HCM
       │                          │                        │                    │
       │ T=HH:MM ────────────────►│                        │                    │
       │                          │                        │                    │
       │                          ├ load forecast_day.json │                    │
       │                          │ for T                  │                    │
       │                          │                        │                    │
       │                          ├ inputs (v_A, n_A) ────►│                    │
       │                          │                        │ compute Y, C_opt  │
       │                          │                        ├───────────────────►│
       │                          │                        │ cycle, splits,    │
       │                          │                        │ v/c, delay, recs  │
       │                          │                        ◄────────────────────┤
       │                          ◄────────────────────────┤                    │
       │ JSON: current + webster + delta + advisories                            │
       ◄──────────────────────────┤                        │                    │
       │ render auto-recommend    │                        │                    │
       │ phase cards              │                        │                    │
```

## SQ-5 — Health monitoring

```
SPA                   /api/health             system probes
 │                          │                     │
 │ poll 5s ────────────────►│                     │
 │                          ├ uptime ────────────►│ time.monotonic()
 │                          ├ RTSP ──────────────►│ rtsp_sim.healthcheck
 │                          ├ phase2 alive ──────►│ /tmp/phase2.pid
 │                          ├ FPS (last bin) ────►│ tail phase2.log
 │                          ├ ingest rate ───────►│ phase2.ndjson mtime delta
 │                          │                     │
 │ ◄────────────────────────┤
 │ render SystemHealthPanel │
```

## SQ-6 — Audit trail (every request, §7.7)

```
client → viewer.py → write data/audit.log → respond
                          │
                          └── if log > 50 MB → rotate to audit.log.1, fresh log
```
