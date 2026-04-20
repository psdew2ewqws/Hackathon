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
- `site1.example.json` is a stubbed instance with placeholder coordinates (`lat: 0, lon: 0`). The user edits it when the actual site is chosen; the validator gates Phase 2 on schema validity.

### 3.5 Annotation

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
