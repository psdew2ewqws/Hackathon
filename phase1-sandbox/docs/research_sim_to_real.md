# Phase 1 Sim-to-Real Research: Building Without Real Traffic Data

**Status**: research / blueprint — 2026-04-20
**Audience**: hackathon team + future readers picking up Phase 1
**Scope**: handbook §6.1–6.6 (Phase 1 Traffic Data Sandbox) with a forward look at §7.3 (incident detection) and §7.4 (forecasting)

---

## 1. Why this document exists

Real Amman GAM detector counts, signal logs, and CCTV are not available. The sandbox already ships honest synthetics — 22-detector × 96-bin counts, 4-phase NEMA signal logs, 14 days of sampled YouTube clips, a MediaMTX RTSP loopback, and a rule-based classifier over 4 Veo-3 event clips. But three structural gaps block training models that will later transfer to live feeds:

1. **No shared scenario.** Counts, signals, and video are independent synthetics. A count spike in `data/detector_counts/` does not correspond to vehicles visible in `data/historical/`, and signal phases are not coupled to either. Models trained on this will not learn the joint distribution that a real site produces.
2. **Sparse event ground truth.** Four event clips cannot train an incident-detection model. Handbook §6.6 wants stalled / abnormal-stop / unexpected-trajectory / spillback / sudden-congestion labels at volume.
3. **No segmentation layer.** Vehicle masks, lane masks, and a clean background plate do not exist — which blocks both evaluation and the visual-domain approach proposed below.

**The strategy:** use the existing Wadi Saqra YouTube footage as a *visual domain anchor*. Extract frames → segment vehicles → inpaint a clean background plate → drive a SUMO microscopic-traffic simulator to produce internally-consistent counts + signals + trajectories → project trajectories onto the plate → composite segmented vehicle crops (optionally passed through an image-to-video diffusion model) to render labeled synthetic clips at scale.

Result: a Phase-1 sandbox whose training data looks like the eventual target domain *and* whose counts/signals/video share one scenario.

---

## 2. Gap map (handbook § → what's in the repo → what's missing)

| § | Deliverable | What exists | What's synthetic / stubbed | Blocks sim-to-real because… |
|---|---|---|---|---|
| 6.1 | Live RTSP stream | `rtsp_sim/mediamtx.yml`, `scripts/publish_loop.sh` | Loops one file | Only one viewpoint; no diversity for detector training |
| 6.2 | Historical video pack | `data/historical/YYYY-MM-DD/*.mp4` — 14 days, 3 clips/day | Sampled from same source pool | Same visual content repeated; low scene diversity |
| 6.3 | 22 detector counts @ 15 min | `data/detector_counts/*.parquet` — 14 days | Gaussian-peak Poisson, no physical simulation | Counts not linked to any vehicle that appears in video |
| 6.4 | Signal timing log | `data/signal_logs/*.ndjson` — 14 days | Fixed 102 s cycle, ±4 s jitter | Phase transitions independent of demand |
| 6.5 | Intersection metadata | `metadata/site1.example.json` + schema | lat/lon = 0, zone polygons drawn for a notional 1080p frame | No real camera matrix → projection is approximate |
| 6.6 | Ground truth & annotation | `annotation/classifier.py` (Pass A/B), `data/labels/clips_manifest.json` | 4 Veo-3 event clips auto-classified | Training signal too small; no per-frame bbox/mask |
| 7.3 | Incident detection training | — | — | Needs ≥ 100 clips per event class with frame-level labels |
| 7.4 | Forecasting training | — | Uses `data/detector_counts/` only | Forecasting features don't see signal coupling or event context |

---

## 3. Segmentation stack

**Goal**: produce per-frame instance masks for vehicles/pedestrians on Wadi Saqra frames + a clean background plate (vehicles inpainted out).

| Tool | Repo | License | Role | Notes |
|---|---|---|---|---|
| **SAM 2** | `facebookresearch/sam2` | Apache-2.0 | Promptable video masks — best for tracking vehicles across frames | Meta's v2 — strong temporal coherence |
| **Grounded-SAM 2** | `IDEA-Research/Grounded-SAM-2` | Apache-2.0 | Text-prompt → bbox (GroundingDINO) → mask (SAM 2) | Primary pick: one-shot "car, truck, bus, motorcycle, pedestrian" prompt |
| **Mask2Former** | `facebookresearch/Mask2Former` | MIT | Panoptic baseline (Cityscapes/ADE20K weights) | Useful as a sanity check against Grounded-SAM |
| **YOLOv11-seg / YOLO26-seg** | `ultralytics/ultralytics` | AGPL-3.0 | Fast inference-time instance segmentation | **License caveat**: AGPL; use for internal evaluation only |
| **LaMa** | `advimman/lama` | Apache-2.0 | Large-mask image inpainting — build the clean background plate | CPU-feasible for 1080p |
| **ProPainter** | `sczhou/ProPainter` | NTU S-Lab License | Video inpainting (temporally consistent plate) | Use when we want a moving camera; overkill for a fixed plate |
| **SDXL-Inpainting** | `diffusers` pipeline | CreativeML Open RAIL++-M | Alternative to LaMa for photorealism | Requires GPU; heavier |

**Decision**: primary pipeline is **Grounded-SAM 2 → LaMa**. Grounded-SAM 2 handles both detection and segmentation from one text prompt; LaMa gives us a deterministic, CPU-friendly clean plate. Mask2Former is a fallback / ground-truth reference, not the hot path.

---

## 4. Image → video generation

**Goal**: turn a single Wadi Saqra background plate plus projected vehicle positions into a temporally-coherent video. Two rendering paths are supported — `plain` (alpha composite, CPU-only) and `diffused` (pass composited frames through image-to-video for motion/lighting polish).

| Model | Repo | License | Role | Notes |
|---|---|---|---|---|
| **CogVideoX-5B-I2V** | `THUDM/CogVideo` | Apache-2.0 | **Primary** image-to-video | Open weights, ~5–10 s clips at 720p; GPU (≥ 16 GB VRAM) |
| **Stable Video Diffusion XT** | `Stability-AI/generative-models` | SVD NC Community License | Fallback | **License caveat**: non-commercial research only |
| **LTX-Video** | `Lightricks/LTX-Video` | Open weights (RAIL) | Fast alternative | Lower VRAM, real-time-ish |
| **AnimateDiff** | `guoyww/AnimateDiff` | Apache-2.0 | Motion modules on top of SD1.5 | Stylized; less physical realism |

**Decision**: the `plain` path is mandatory (CPU fallback, deterministic). The `diffused` path uses **CogVideoX-5B-I2V** (Apache-2.0) when a GPU is available. SVD is documented but skipped by default due to license.

---

## 5. Traffic simulator — SUMO

**Goal**: fix the "no shared scenario" gap. One simulation run emits *coupled* detector counts, signal phases, and per-vehicle trajectories.

| Tool | Repo | License | Role |
|---|---|---|---|
| **SUMO** | `eclipse-sumo/sumo` | EPL-2.0 | Microscopic traffic simulator — primary |
| **SUMO-TraCI** | part of SUMO | EPL-2.0 | Python API for runtime mutation (inject stalled vehicle, wrong-way, etc.) |
| **CityFlow** | `cityflow-project/CityFlow` | Apache-2.0 | Large-scale / RL-friendly alternative |
| **FLOW** | `flow-project/flow` | MIT | RL wrappers on SUMO |

**Why SUMO**: emits induction-loop counts (handbook §6.3 format), traffic-light programs that can be logged in our ndjson format (§6.4), and vehicle trajectories that we project to pixel space for compositing. One seed controls all three outputs → per-scenario reproducibility.

**Network spec** matching `site1.example.json`:
- 4 approaches (N/S/E/W), N/S are major (3 through + 1 left + 1 right), E/W are minor (2 through + 1 left + 1 right)
- 22 induction loops mapped 1-to-1 to `DET-*` IDs in `profiles.yml`
- Signal program mirrors the NEMA plan in `phase_plan.yml` (phases 2/6/4/8 at 35/15/22/10 s green, 102 s cycle)
- Demand curve lifted from `profiles.yml` peaks (AM 08:00, midday 13:00, PM 17:30)

---

## 6. Public datasets

Used for pretraining and evaluation baselines, **never redistributed**.

| Dataset | Size | License | Use |
|---|---|---|---|
| **UA-DETRAC** | 10 h urban traffic | Non-commercial research | Vehicle detection/tracking pretrain |
| **BDD100K** | 100 k driving videos | BSD-3 (videos); labels CC BY-NC-SA | Lane + object pretrain |
| **CityFlow** | 5.25 h multi-camera | Apache-2.0 | Re-ID / multi-camera tracking |
| **AI City Challenge 2024 / 2025** | Multiple tracks | Research use | Benchmarks; reference pipelines |
| **Cityscapes** | 5 k fine + 20 k coarse | CC BY-NC 4.0 | Segmentation pretrain — **training only, no redistribution** |
| **KITTI** | Driving sequences | CC BY-NC-SA 3.0 | 3D detection reference — **training only** |
| **TRANCOS** | 1 244 images | Research | Vehicle crowd counting baseline |
| **PEMS-BAY / METR-LA** | Detector time series | Public research | Forecasting benchmarks (§7.4) |
| **HighD / inD / rounD** | Drone trajectory | Research | Trajectory prediction reference |
| **Waymo Open (Perception)** | Driving LiDAR + camera | Waymo license | Heavy; optional |

For the Wadi Saqra pipeline, the most useful are **UA-DETRAC** (train YOLO/BoT-SORT baselines) and **Cityscapes** (domain reference for road-surface masks).

---

## 7. Tracking & forecasting libraries

**Tracking** (for evaluation and pseudo-labeling of real footage):
- **BoT-SORT** (MIT) — already wired in Phase 2
- **ByteTrack** (MIT) — strong baseline
- **OC-SORT** (MIT) — observation-centric, robust to occlusion
- **DeepSORT** (GPL-3.0) — noted for completeness, license caveat

**Forecasting** (§7.4 prep):
- **Darts** (Apache-2.0) — general-purpose time-series; LSTM, TFT, N-BEATS
- **Nixtla NeuralForecast** (Apache-2.0) — NHITS, TFT, Informer
- **DCRNN / STGCN / GraphWaveNet** — traffic-specific graph models; reference implementations in `liyaguang/DCRNN`, `nnzhan/Graph-WaveNet`
- **Merlion** (Amazon, BSD-3) — time-series benchmarking

---

## 8. The Wadi Saqra compositing pipeline

```
┌─────────────────────────────────┐
│  data/raw/youtube/              │
│    amman-wadi-saqra-tour.mp4    │
└───────────────┬─────────────────┘
                │  01_extract_wadisaqra_frames.py
                ▼
┌─────────────────────────────────┐
│  data/research/frames/*.jpg     │  ← Laplacian + luminance filter
│  data/research/frames/index.json│
└───────────────┬─────────────────┘
                │  02_segment_and_inpaint.py
                ▼
┌─────────────────────────────────┐
│  data/research/segments/*.json  │  ← Grounded-SAM 2 instance masks
│  data/research/crops/*.png      │  ← segmented vehicle cut-outs
│  data/research/plates/*.jpg     │  ← LaMa clean background plate
└───────────────┬─────────────────┘
                │
                │  ┌──────────────────────────────────┐
                │  │ 03_sumo_scenario.py              │
                │  │   SUMO net + routes + signals    │
                │  │   → counts.parquet (site1)       │
                │  │   → signals.ndjson               │
                │  │   → trajectories.parquet (x,y,θ) │
                │  └──────────────┬───────────────────┘
                │                 │
                ▼                 ▼
         ┌────────────────────────────────┐
         │  04_compose_synthetic_video.py │
         │   - homography from site1.json │
         │   - project trajectories       │
         │   - alpha-composite crops       │
         │   - (optional CogVideoX pass)  │
         │   → data/research/video.mp4    │
         │   → data/research/labels.json  │
         └───────────────┬────────────────┘
                         │  05_generate_event_clips.py
                         ▼
         ┌────────────────────────────────┐
         │ data/research/events/          │
         │   stalled_vehicle/ (≥ 100)     │
         │   abnormal_stop/ (≥ 100)       │
         │   unexpected_trajectory/ …     │
         │   queue_spillback/ …           │
         │   sudden_congestion/ …         │
         │   manifest.json                │
         └────────────────────────────────┘
```

Each stage is seedable and writes under `data/research/` so it never touches the existing sandbox outputs.

---

## 9. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| License contamination (Cityscapes / KITTI NC) | Blocks redistribution | Use for training only; never bundle into the submission pack |
| Compute (CogVideoX needs ≥ 16 GB VRAM) | Diffusion path unavailable | `plain` composite path is CPU-only and mandatory; diffusion is optional polish |
| Single-camera domain gap | Low viewpoint diversity | Augment with affine warps, time-of-day transfer (CycleGAN / image-to-image), and inject BDD100K frames during pretrain |
| No real camera matrix | Projection is approximate | Homography derived from stop-line polylines in `site1.example.json`; rebuild when a real site is chosen |
| SUMO realism for Amman driving | Behaviour gap | Tune car-following parameters; compare against UA-DETRAC flow statistics |
| Auto-classifier circular validation | Self-congratulatory eval | Hold out 10% of generated clips; manually label; report agreement separately |
| Weight downloads gated offline | Broken first-run | README documents the one-time `huggingface-cli download` commands; scripts degrade gracefully when weights are absent |

---

## 10. Decisions log (short)

- **Primary segmenter**: Grounded-SAM 2 (Apache-2.0, one-shot text prompts).
- **Primary background inpainter**: LaMa (Apache-2.0, CPU-feasible).
- **Primary video generator**: alpha compositing (CPU) with CogVideoX-5B-I2V (GPU) as an optional polish pass; SVD skipped by default on license grounds.
- **Traffic simulator**: SUMO (EPL-2.0) — fixes the count/signal/video coupling gap.
- **Pretrain datasets**: UA-DETRAC + BDD100K. Cityscapes only if a segmentation head is added.
- **Keep existing pure-synthetic generators** alongside SUMO for cheap CI-friendly fallback.

---

## 11. Runnable prototypes

Implemented under `phase1-sandbox/experiments/`. See `experiments/README.md` for end-to-end instructions.

1. `01_extract_wadisaqra_frames.py`
2. `02_segment_and_inpaint.py`
3. `03_sumo_scenario.py`
4. `04_compose_synthetic_video.py`
5. `05_generate_event_clips.py`

Makefile targets: `research-frames`, `research-segment`, `research-sumo`, `research-compose`, `research-events`, `research-all`.

Each prototype is deterministic (seeded), gracefully skips missing-weight paths with a clear message, and writes only under `data/research/` so the existing sandbox outputs are untouched.

---

## 12. References

- 9XAI Hackathon Handbook — AI-Based Traffic Monitoring and Traffic Flow Forecasting (provided).
- SUMO docs: <https://sumo.dlr.de/docs/>
- Grounded-SAM 2: <https://github.com/IDEA-Research/Grounded-SAM-2>
- LaMa: <https://github.com/advimman/lama>
- CogVideoX: <https://github.com/THUDM/CogVideo>
- UA-DETRAC: <https://detrac-db.rit.albany.edu/>
- BDD100K: <https://www.vis.xyz/bdd100k/>
- PEMS-BAY / METR-LA benchmarks: <https://github.com/liyaguang/DCRNN>
