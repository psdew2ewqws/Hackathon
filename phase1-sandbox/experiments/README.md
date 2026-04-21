# Phase 1 Research Prototypes — Sim-to-Real Without Real Traffic Data

Five small scripts that close the gaps identified in
[`../docs/research_sim_to_real.md`](../docs/research_sim_to_real.md). Run them in
order to go from "Wadi Saqra YouTube video + SUMO simulation" to labeled
synthetic training clips.

All outputs land under `data/research/` and never touch the existing sandbox
outputs in `data/detector_counts/`, `data/signal_logs/`, `data/historical/`, etc.

## Prerequisites

Minimum (all deterministic, CPU-only, no extra weights):
- Python 3.12+ with the base sandbox venv (`pip install -e '.[dev]'`)
- `opencv-python`, `numpy`, `pandas`, `pyarrow`, `pyyaml` (already in the base install)
- ffmpeg (already required by the sandbox)

**Stage 03 — SUMO — is now wired up (as of 2026-04-21).** `sumo`, `sumolib`,
`traci`, and `pyproj` are installed on the dev machine; `03_sumo_scenario.py`
drives a real micro-simulation against a hand-authored 4-way network living
in `phase1-sandbox/experiments/sumo/site1/synth/`. See §Stage 03 below.

Optional (better segmentation, diffusion polish). Each stage degrades
gracefully to a documented fallback if a weight/library is absent.

```
# Stage 02: preferred segmentation backends
pip install ultralytics                              # YOLO-seg (AGPL-3.0, internal eval only)
pip install simple-lama-inpainting                   # LaMa background inpainter
# For the top-tier Grounded-SAM 2 stack, see:
#   https://github.com/IDEA-Research/Grounded-SAM-2

# Stage 03: real SUMO (already installed on the dev machine; `--analytic`
#                      forces the cell-transmission-model fallback)
sudo apt install sumo sumo-tools sumo-doc
pip install eclipse-sumo traci sumolib pyproj

# Stage 04: diffusion polish (optional — GPU ≥ 16 GB VRAM)
pip install diffusers accelerate transformers
#   then: huggingface-cli login
#   then: huggingface-cli download THUDM/CogVideoX-5b-I2V
```

## Stage-by-stage

### 01 — Extract keyframes from Wadi Saqra footage

```
python experiments/01_extract_wadisaqra_frames.py \
  --video data/raw/youtube/amman-wadi-saqra-tour.mp4 \
  --out-dir data/research/frames \
  --stride-s 2.0 --max-frames 400 --seed 42
```

- Samples frames at a fixed stride, rejects blur (Laplacian variance) and
  extreme luminance.
- Writes `data/research/frames/wadisaqra_f<idx>.jpg` + `index.json`.

### 02 — Segment vehicles + build a clean plate

```
python experiments/02_segment_and_inpaint.py \
  --frames-dir data/research/frames \
  --out-segments data/research/segments \
  --out-crops    data/research/crops \
  --out-plates   data/research/plates \
  --backend auto
```

Backend selection (first available wins):
1. **Grounded-SAM 2** (text-prompted masks, best quality)
2. **Ultralytics YOLO-seg** (widely available, AGPL)
3. **HOG fallback** (zero-dep; pedestrian-only, good enough to smoke-test)

Plate builder uses a temporal-median approach — for each pixel, the median of
the frames where that pixel was *not* under a vehicle mask. LaMa polish runs if
`simple-lama-inpainting` is installed.

### 03 — SUMO coupled scenario

Two modes share a single output schema contract:

**Real SUMO (default).** Drives a TraCI-controlled simulation against the
hand-authored 4-way network at `sumo/site1/synth/net.net.xml`. Demand is
calibrated from Phase 2's observed `stop_line_crossing` events; signal plan
is translated from `phase_plan.yml` into a SUMO `<tlLogic>` block; induction
loops mirror the 22 DET-* IDs in `profiles.yml`.

```
python experiments/03_sumo_scenario.py \
  --profiles phase1-sandbox/configs/profiles.yml \
  --phase-plan phase1-sandbox/configs/phase_plan.yml \
  --site-meta phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \
  --out-dir data/research/sumo \
  --date 2026-04-20 --seed 42
#   add --analytic to force the fallback
#   add --duration-s 3600 to limit sim length (default: full day, 86400s)
```

Three outputs that share *one* scenario seed:
- `counts_<date>.parquet` — **schema-identical to `synth.detector_counts.SCHEMA`**
  (passes `phase1-sandbox/tests/test_synth_counts.py`)
- `signal_<date>.ndjson` — **schema-identical to `synth.signal_logs` output**
- `trajectories_<date>.parquet` — per-vehicle (t, x_m, y_m, angle, speed)
  *plus* projected `stop_line_px_x` / `stop_line_px_y` so stage 04 compose
  consumes the file unchanged from its analytic-fallback era.

**Analytic fallback** (`--analytic`, or automatic if `traci` import fails):
- Per-minute Poisson arrivals driven by `profiles.yml` peaks
- Queue accumulates during red, discharges at saturation flow during green
  (phase state from `phase_plan.yml`)
- Single seed governs counts, signal jitter, and trajectory sampling

**Regenerating the SUMO scenario** after editing `site1.example.json` or
`phase_plan.yml`:

```
make sumo-build              # nodes + edges + net.net.xml
make sumo-tllogic            # phase_plan.yml → tl.add.xml
make sumo-routes             # phase2.ndjson → routes.rou.xml (calibrated demand)
make sumo-detectors          # profiles.yml → detectors.add.xml (22 induction loops)
make sumo-scenario           # all four above, in order
```

Regional OSM context for Wadi Saqra (≈ 2.5 km² around `lat 31.96, lon 35.91`,
22 real tagged TLS) is kept alongside the synth network at
`sumo/site1/build/osm_bbox.osm.xml` + `net.net.xml`. It is not currently
consumed by the simulation — its real-world geometry does not cleanly map to
the cardinal N/S/E/W approach schema `site1.example.json` enforces. It is
reserved for future multi-site work.

### 04 — Composite labeled video

```
python experiments/04_compose_synthetic_video.py \
  --plate data/research/plates/wadisaqra_plate.jpg \
  --crops-dir data/research/crops \
  --trajectories data/research/sumo/trajectories_2026-04-20.parquet \
  --site-meta phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \
  --out-video data/research/composed/video.mp4 \
  --out-labels data/research/composed/labels.json \
  --seconds 30 --seed 42
```

- Projects each SUMO spawn onto pixel space using the stop-line polylines in
  `site1.example.json` and a fixed travel speed (150 px/s).
- Alpha-composites the segmented vehicle crops from step 02 along the
  projected path.
- Writes 1920×1080 H.264 MP4 at 10 fps + per-frame COCO-style labels
  (bbox, track_id, class, approach).

GPU polish (optional): feed each composited frame into CogVideoX-5B-I2V for
motion/lighting realism. Not wired in by default — see the Decisions log in the
research doc for rationale.

### 05 — Generate labeled event clips

```
python experiments/05_generate_event_clips.py \
  --out-root data/research/events --per-class 10 --seconds 15 --seed 42
```

For each of the handbook §6.6 event classes (stalled_vehicle, abnormal_stop,
unexpected_trajectory, queue_spillback, sudden_congestion), seed a scenario
and render N labeled clips. Output:
- `data/research/events/<class>/<clip_name>.mp4`
- `data/research/events/<class>/<clip_name>.json` (per-frame labels with an
  `event_actor`+`event_role` tag marking the vehicle that realises the event)
- `data/research/events/manifest.json`

Target for training runs: `--per-class 100 --seconds 20`.

## Makefile targets

```
make research-frames    # 01
make research-segment   # 02
make research-sumo      # 03
make research-compose   # 04
make research-events    # 05
make research-all       # full pipeline
```

## Self-check

The existing rule-based classifier (`phase1-sandbox/src/traffic_intel_sandbox/annotation/classifier.py`)
can be pointed at `data/research/events/` to self-check that the composited
clips are visually valid (i.e. the rules that classified Veo-3 clips recover
the seeded labels ≥ 70% of the time). This is a sanity check, *not* a training
signal — the seeded labels are the ground truth.

## Deterministic contract

Every script accepts `--seed` and, given the same inputs + seed, produces
byte-identical outputs. This includes:
- Frame selection (seeded shuffle)
- Segmentation backend order (but not the backend's internal weights, which
  the user controls)
- SUMO arrivals (Poisson), signal jitter, trajectory subsampling
- Composite spawn schedule, crop selection

## What's deliberately not here

- **Weights are not shipped.** The research doc documents the one-time
  `huggingface-cli download` commands. Keep the repo honest.
- **The OSM-pulled Wadi Saqra network is parked, not piped.** It is too
  geometrically skewed (real-world T-junctions, non-cardinal bearings,
  clustered junctions) to serve the cardinal N/S/E/W schema the rest of the
  pipeline is built on. Promoted when we do multi-site support.
- **GPU-only features** (CogVideoX, SVD) are documented but off by default.
