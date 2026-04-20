# Phase 2 — Crack-the-Code Feasibility Build (planned)

De-risk the hardest parts of the first-site scope by building minimal-viable quick-builds of every mandatory module, benchmarking them, and proving that the full Phase 3 stack is achievable.

Not yet implemented. Depends on Phase 1 sandbox artifacts.

## Target modules (handbook §7)

- Architecture design (diagrams, data flows, fault-handling paths)
- Data Acquisition Layer quick build
- Real-Time Incident Detection quick build — **YOLO26 + built-in BoT-SORT / ByteTrack**
- Traffic Flow Forecasting quick build — LSTM or XGBoost on detector counts
- Signal optimization support quick build
- Dashboard quick build — **FastAPI + React + shadcn/ui**
- Security, read-only, and system-isolation proof
- Benchmark report (ingestion stability, detection P/R, forecasting MAE/MAPE, dashboard responsiveness)

## Inputs from Phase 1

| From P1 | Used for |
|---|---|
| `rtsp://localhost:8554/site1` | Detection pipeline source |
| `data/detector_counts/*.parquet` | Forecasting training |
| `data/signal_logs/*.ndjson` | Signal-aware forecasting features |
| `data/metadata/site1.json` | Zone polygons, stop-line geometry |
| `data/annotations/*` | Detector fine-tuning + incident-event validation |
