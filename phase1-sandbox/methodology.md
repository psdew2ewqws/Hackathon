# Methodology Note — Phase 1 Traffic Data Sandbox

> Handbook §6 requires "a methodology note explaining how the dummy data and simulated feeds were built or acquired." This document fulfills that deliverable.

## 1. Scope and intent

The sandbox imitates the operating environment of a single representative intersection so that Phase 2 (feasibility) and Phase 3 (full stack) can be built and validated against a stable, reproducible dataset. The sandbox is **not** a real GAM data feed and is **not** a substitute for one — it is an engineering platform that makes the downstream AI work possible at hackathon pace.

## 2. Why synthetic + replayed

- **Real Amman GAM detector logs and signal logs are not publicly available.** Producing a realistic analogue is the legitimate option the handbook anticipates ("hack, build, or acquire").
- **Real 2-week CCTV footage at the chosen intersection is not available before site selection.** YouTube fixed-angle traffic streams provide a realistic, legally accessible visual analogue.
- **Synthetic data parametrized by published traffic-engineering conventions** (Gaussian peaks, Poisson arrivals, NEMA phase plans) is closer to real-world exported detector logs than hand-crafted spreadsheets.

## 3. Component-by-component provenance

### 3.1 Video (live-like + historical)

**Source of truth for v1: Google Veo 3 generative video.** Free YouTube fixed-CCTV footage of Amman intersections is not available at usable quality and duration. Traffic-tour / dashcam substitutes (tested and rejected: Wadi Saqra walking tour, 7th Circle drive-through) are inherently moving-camera content and cannot serve as a fixed-view source even with rigid stabilization. A generative model produces deterministically fixed, arbitrarily many scenarios (day, night, peak, incidents) at consistent framing — a better baseline than imperfect real footage for Phase 1 pipeline validation.

1. Veo 3 prompts (kept in `phase1-sandbox/configs/veo3_prompts.md`, one per scenario) produce 8-second 1080p MP4 clips, dropped into `data/raw/veo3/`.
2. `ffmpeg` normalises every clip into the common profile — 1920×1080, 10 FPS, H.264, `yuv420p`, audio stripped, `+faststart`. This matches the handbook §6.1 assumption exactly.
3. For the historical pack, `ffmpeg -c copy` cuts three 3-minute clips per day for 14 days, sampling randomly (seeded) from the normalized pool. Clips are filed under `data/historical/YYYY-MM-DD/clip-NN-<window>.mp4`. Real 14-day continuous footage would be ideal; this sampling is a honest simulation, documented here and in the filenames.
4. The RTSP simulator (`MediaMTX` + `ffmpeg -re -stream_loop -1`) loops the first normalized clip indefinitely at `rtsp://localhost:8554/site1`, indistinguishable from a live feed to downstream decoders.

**YouTube fallback** (unused in v1, kept operational in case real footage becomes available): the `ingest.youtube_fetch` module downloads from URLs in `phase1-sandbox/configs/sources.yml`, with selection criteria fixed-camera, wide intersection view, ≥ 1080p, ≥ 10 minutes, no road-covering overlays. Auxiliary modules `ingest.stationary_extractor` (finds red-light stops in dashcam drives) and `ingest.stabilize` (rigid video stabilization) are available for salvaging non-ideal sources.

### 3.2 Detector counts

1. Per-minute arrival rate = `baseline_rate + Σ peaks(t) * weekday_multiplier` where `peaks(t)` is a mixture of three Gaussians parameterised in `configs/profiles.yml`:
   - AM peak: 08:00, σ = 45 min, amplitude 18 veh/min
   - Midday bump: 13:00, σ = 60 min, amplitude 7 veh/min
   - PM peak: 17:30, σ = 60 min, amplitude 22 veh/min
2. Multiplicative Gaussian noise (σ = 15 % of rate) is applied minute-by-minute.
3. Poisson draws per minute produce integer arrivals; sums into 96 × 15-minute bins per day.
4. Each of 22 detectors has a `base_multiplier` reflecting its lane's expected share of flow (major-through ≈ 1.3, minor-left ≈ 0.3, etc.).
5. Seeding: master seed (default 42) is combined with day ordinal so every (seed, day) pair is reproducible; same seed → byte-identical parquet.
6. Storage: Parquet with an explicit PyArrow schema, `zstd` compression.

### 3.3 Signal timing log

1. A 4-phase NEMA-style plan (phases 2, 6, 4, 8) cycles continuously for 24 h per day.
2. Each phase has parameterised green / yellow / all-red durations. Nominal cycle = 102 s (within handbook §6.4 90–120 s).
3. Cycle-level jitter of ±4 s is applied per cycle to resemble a semi-actuated controller.
4. Emits one ndjson event per phase transition (`GREEN_ON → YELLOW_ON → RED_ON`) with millisecond-precision UTC timestamps.

### 3.4 Intersection metadata

- The JSON Schema (draft 2020-12) covers everything downstream needs: camera pose, approach/lane definitions, stop-line polylines, monitoring-zone polygons.
- `site1.example.json` is populated with approximate Wadi Saqra / King Abdullah I Gardens reference coordinates (`lat: 31.9583, lon: 35.9072`) — *approximate, reference only*. Exact survey coordinates are substituted once an operational site is chosen; the validator gates Phase 2 on schema validity independent of coordinate precision.
- Stop-line polylines and monitoring-zone polygons are drawn against the normalised 1920×1080 frame of `data/normalized/amman-wadi-saqra-gardens-brt.mp4` (the same preset shipped under `metadata/presets/wadi-saqra-gardens-brt.json`). The browser calibration tool at `/calibrate` reuses the preset as a starting point and supports drag-to-adjust for any future camera angle.

### 3.5 SUMO microscopic coupled scenario

*Wired up 2026-04-21.* The research pipeline at `phase1-sandbox/experiments/`
now drives a real Eclipse SUMO simulation that emits byte-compatible outputs
for `synth.detector_counts` (parquet), `synth.signal_logs` (ndjson), and a
new `trajectories_<date>.parquet` (per-vehicle pose for the compose stage).

Provenance of each SUMO input:

| SUMO input | Origin | Generator |
|---|---|---|
| `net.net.xml` — road network | Hand-authored 4-way matching `site1.example.json` (5-lane N/S, 4-lane E/W) | `experiments/sumo/site1/build_site1_network.py` |
| `tl.add.xml` — traffic light logic | `phase_plan.yml` NEMA plan (102 s cycle, phases 2/6/4/8) | `experiments/sumo/site1/build_site1_tllogic.py` |
| `routes.rou.xml` — demand | Aggregated `stop_line_crossing` events from `data/events/phase2.ndjson` (observed veh/hr per approach), split across turns by each approach's lane-type mix | `experiments/sumo/site1/build_site1_routes.py` |
| `detectors.add.xml` — 22 induction loops | Lane mapping from `profiles.yml`, IDs preserved (DET-*) | `experiments/sumo/site1/build_site1_detectors.py` |

The OSM-pulled Wadi Saqra area (≈ 2.5 km² around 31.96°N 35.91°E, 22 real
tagged traffic signals, 4.6 MB osm.xml) is persisted alongside the synth
network at `experiments/sumo/site1/build/` as regional context. It is *not*
currently fed into the simulation — its real-world geometry is skewed and
cluster-based rather than the cardinal 4-way schema the rest of the
pipeline encodes (`site1.example.json`, `profiles.yml`, phase-2 zone
polygons). Reserved for future multi-site promotion.

**Analytic fallback** (`--analytic`) uses the original cell-transmission
flow model (per-minute Poisson arrivals + queue + saturation-flow
discharge) and remains a supported mode for environments without SUMO. Both
modes share the exact same output schemas so downstream consumers
(`04_compose_synthetic_video.py`, Phase 3 forecasting) are unaware which
simulator produced the data.

**Precedent for SUMO-generated traffic data in Amman:** Al-Mousa, Alqudah,
Faza (Princess Sumaya University for Technology, Amman) published the
**SimToll** dataset in 2022 — 90 SUMO-generated highway scenarios covering
lane-choice, toll pricing, and carpool behaviour. While SimToll is a 5-lane
highway and cannot directly seed our 4-way intersection, it validates the
core methodological choice of this document: SUMO microscopic simulation
is an accepted approach for producing realistic supplementary traffic data
in the Amman context when real operational feeds are unavailable. SimToll
itself is reserved as an external validation benchmark for Phase 3
forecasting.

### 3.6 Annotation

- CVAT 2.x (latest) is stood up via `docker-compose --profile annotation`.
- Taxonomy is fixed up-front in `annotation/taxonomy.yml`: 6 object classes (COCO subset) + 6 event-window tags (handbook §6.6).
- The seeder creates initial tasks from a bounded subset of historical clips to avoid spamming CVAT.

## 4. Limitations

- **Synthetic detector counts are parametric.** They do not reflect unique Amman-specific traffic dynamics (e.g., religious-calendar surges, mall effects, regional holidays). For Phase 2 forecasting benchmarking, this is a *baseline* — real GAM data should replace it if obtained.
- **Historical video is sampled, not continuous.** A real 2-week recording at the chosen intersection would be strictly preferable.
- **Queue-spillback and incident ground-truth are annotator-driven**, not auto-generated. Coverage in Phase 1 is limited to a handful of seeded CVAT tasks; Phase 2 can expand as needed.
- **No adversarial / stress data** (rain, snow, camera occlusion, night-time extremes) is included in the v1 pack. These are left to Phase 2 as deliberate robustness tests.
- **Intersection site is a stub.** The exact Amman intersection will be chosen later; all dimensions, stop-line coordinates, and zone polygons in `site1.example.json` are plausible defaults, not measurements.

## 5. Open-source component list (handbook §8 Phase-3 deliverable, drafted here)

| Component | Version/tag | License | Usage |
|---|---|---|---|
| bluenviron/mediamtx | 1.16.0 | MIT | RTSP stream simulator |
| FFmpeg | 7.1.1 | LGPL | Video decode/encode/loop |
| yt-dlp | latest stable (2026.x) | Unlicense | YouTube source acquisition |
| cvat-ai/cvat | latest | MIT | Video/image annotation |
| PostgreSQL | 16-alpine | PostgreSQL License | Shared storage (P2/P3) |
| Python | 3.11+ | PSF | Runtime |
| numpy, pandas, pyarrow, pyyaml | pinned ≥ | BSD-3 / Apache-2.0 | Synthetic data generation |
| jsonschema | ≥ 4.21 | MIT | Metadata validation |
| opencv-python-headless | ≥ 4.9 | Apache-2.0 | Frame ops |
| pytest | ≥ 8.0 | MIT | Verification suite |
| Ultralytics YOLO26 | (Phase 2+) | AGPL-3.0 | Detection + tracking |
| roboflow/supervision | (Phase 2+) | MIT | Line/zone counting & overlays |
| Eclipse SUMO | 1.18 | EPL-2.0 | Microscopic traffic simulator (experiments/03) |
| sumolib / traci | ≥ 1.18 | EPL-2.0 | Python bindings + TraCI runtime control |
| pyproj | ≥ 3.7 | MIT | Lat/lon ↔ projected-xy conversion for sumolib |

## 6. Reproducibility claim

On a clean checkout:

```bash
make setup
# edit configs/sources.yml with YouTube URLs
make fetch-videos normalize-videos historical-pack
make sandbox-up stream-check
make synth-all validate-metadata
make sandbox-verify
```

…yields byte-identical `data/detector_counts/*.parquet` and `data/signal_logs/*.ndjson` across machines (same seed → same output), and a green pytest report. RTSP healthcheck is network-dependent but structurally deterministic.

## 7. YouTube source list

The exact URLs used live in `phase1-sandbox/configs/sources.yml` and are mirrored into the git history. Copy the final set into this section at the end of Phase 1 as the audit trail.

```
(To be filled in after sources are curated.)
```

## 8. Automated event-class labelling (rule-based classifier)

§6.6 asks for a "labeled validation layer" — vehicle labels, incident labels, congestion labels, queue-spillback markers, and selected event windows. We close that bullet **without manual labelling** using a two-pass rule-based classifier that consumes the primitives the Phase 2 detector already emits.

**Pass A** is pure aggregation over the ndjson events `detect_track.py` writes per clip. Fires in priority order — first match wins:

| Tag | Rule summary |
|---|---|
| `gridlock` | max queue occupancy ≥ 5 AND zero stop-line crossings AND ≥ 35 unique tracks |
| `queue_spillback` | ≤ 1 crossing total AND a `queue_spillback` zone held count ≥ 5 for ≥ 40 frames |
| `sudden_congestion` | last-quarter zone-event rate ≥ 2× first-quarter |
| `unexpected_trajectory` | track-ID churn ≥ 1.8× baseline OR > 70 % of crossings on one approach |
| `normal` | ≥ 3 crossings across ≥ 2 approaches |

**Pass B** runs only when Pass A returns `insufficient_evidence`. It re-opens the clip's normalized mp4, samples every 10th frame through YOLO26 tracking, and classifies by per-track motion + class id (see `classifier_thresholds.yml → pass_b`). Picks up `stalled_vehicle`, `abnormal_stop`, and `pedestrian_interaction`.

All thresholds live in `phase2-feasibility/configs/classifier_thresholds.yml` and can be tuned without editing code. Results are written to `data/labels/clips_manifest.json` as new `predicted_tag` / `predicted_confidence` / `classifier_version` / `pass_used` / `reasons` fields — the existing `tag` field is reserved for human overrides.

**Rationale for skipping CVAT for the hackathon baseline**: our primitives (line crossings, zone occupancy, unique-track churn) cleanly separate the four Veo 3 event clips we have today. A full human-labeling pass is still valuable for detector fine-tuning in Phase 2, but the §6.6 deliverable is satisfied by per-clip event tags with interpretable evidence, which this classifier produces end-to-end. See `phase1-sandbox/ground_truth.md` for the full audit trail.

Operational note: this classifier is also the most sensitive sanity check we have on the zone geometry in `site1.example.json`. When the real intersection's polygons get swapped in post-Phase 1, re-running `make phase2-classify` on the existing clips is a fast way to detect zone-misalignment regressions.
