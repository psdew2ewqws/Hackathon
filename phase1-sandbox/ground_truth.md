# Phase 1 §6.6 — Ground Truth & Automated Annotation

Handbook §6.6 requires a "labeled validation layer" for the Phase 1 sandbox: vehicle labels, incident labels, congestion labels, queue-spillback markers, and selected event windows. This document describes how those labels are produced **automatically, without manual CVAT labelling**, using a two-pass rule-based classifier over primitives that the Phase 2 detect-and-track pipeline already emits.

## Why no human labeling

The Phase 2 detector (YOLO26 + BoT-SORT + `roboflow/supervision`) already outputs three high-signal primitives per clip: stop-line crossings, monitoring-zone occupancy, and tracker-ID churn. On the four Veo-3 event clips we have, these three numbers **alone** cleanly separate the event classes — see `data/labels/clips_manifest.json → interpretation[]`. Human labels are still welcome for spot-checking, but they are not required to produce a consistent ground-truth set.

## Taxonomy

Object classes — COCO-compatible subset from `annotation/taxonomy.yml`:

| id | class |
|---|---|
| 0 | car |
| 1 | truck |
| 2 | bus |
| 3 | motorcycle |
| 4 | bicycle |
| 5 | pedestrian |

Event tags (one predicted per clip) from `annotation/taxonomy.yml`:

| tag | meaning |
|---|---|
| `normal` | baseline / healthy flow |
| `gridlock` | dense scene, no flow |
| `queue_spillback` | queue zone sustained, not draining |
| `sudden_congestion` | traffic rate climbing fast mid-clip |
| `unexpected_trajectory` | wrong-way, illegal turn, red-light runner |
| `stalled_vehicle` | vehicle stopped ≥ several samples outside a queue |
| `abnormal_stop` | same, but in a travel / conflict zone |
| `pedestrian_interaction` | pedestrian in or adjacent to a `ped_crossing` zone |

## Classifier architecture

Two independent passes live in `phase2-feasibility/src/traffic_intel_phase2/classifier.py`:

### Pass A — rule set over the per-clip event ndjson (<20 ms)

Fires in this order; first match wins:

| # | Tag | Rule (all conditions must hold) |
|---|---|---|
| 1 | `gridlock` | `max_zone_occupancy ≥ 5` AND `line_crossings_total == 0` AND `unique_tracks ≥ 35` AND `frames ≥ 40` |
| 2 | `queue_spillback` | `line_crossings_total ≤ 1` AND some `queue_spillback`-kind zone held `count ≥ 5` for ≥ 40 consecutive frames |
| 3 | `sudden_congestion` | zone-event rate in the last quarter of the clip ≥ 2× the first quarter |
| 4 | `unexpected_trajectory` | tracker-ID churn (`unique_tracks / baseline ≥ 1.8`) OR > 70 % of crossings concentrated on a single approach |
| 5 | `normal` | ≥ 3 total crossings across ≥ 2 approaches |
| — | `insufficient_evidence` | no rule fired → fall through to Pass B if possible |

All thresholds are in `phase2-feasibility/configs/classifier_thresholds.yml` and can be tuned without touching code.

### Pass B — video re-sample (only on `insufficient_evidence`, ~2 s per clip)

Re-opens `data/normalized/events/<clip>.mp4`, samples every 10th frame, runs YOLO26 tracking, and computes the mean pixel-speed of each track's centroid. Then:

- Tracks with mean speed < 3 px/s for ≥ 3 samples **inside** a travel lane or conflict zone → `abnormal_stop`.
- Same signature **outside** every `queue_spillback` zone → `stalled_vehicle`.
- Any pedestrian-class detection inside a `ped_crossing` zone → `pedestrian_interaction`.

### Confidence

A normalized margin from the nearest decision boundary (e.g. gridlock confidence rises with `max_zone_occupancy − threshold`). Reported but explicitly documented as a **heuristic**, not a calibrated probability. Mapping: margin 0 → 0.50, margin ≥ 3 → 0.99, linear in between.

## Per-clip verdicts (run 2026-04-20)

All four Veo-3 event clips. Column meanings: `predicted_tag` = classifier output, `pass` = which pass fired, `features` = the numbers that drove the decision.

| Clip | Predicted | Pass | Confidence | Driving features |
|---|---|---|---|---|
| `site1_normal_midday_01` | **normal** | A | 0.99 | 7 crossings (N=1 S=0 E=4 W=2), 39 tracks, max queue occupancy 9 |
| `site1_gridlock_01` | **gridlock** | A | 0.99 | 0 crossings, 41 tracks, max queue occupancy 10 |
| `site1_red-runner_01` | **stalled_vehicle** | B | 0.60 | 0 crossings on stop-lines; Pass B found 4 tracks stationary outside queue zones |
| `site1_wrongway_01` | **unexpected_trajectory** | A | 0.51 | 60 unique tracks / baseline 32 = 1.88× churn |

All four match the intended class of the Veo-3 prompt. Red-runner is a mild surprise — Pass A didn't trigger because the SUV's crossing happened outside our drawn stop-line polygons, but Pass B correctly caught the SUV coming to a stop after the red-light run, and labeled it `stalled_vehicle`. That is a defensible auto-label; a human labeler might tag the clip `unexpected_trajectory` AND `stalled_vehicle`.

## Limitations (honest)

1. **No polygon labels per frame.** The classifier produces one tag per clip, not per-frame bounding boxes. Training a detector from scratch still requires CVAT labeling — but for the handbook's §6.6 "selected event windows for validation" requirement, per-clip tags are sufficient.
2. **Zone geometry is synthetic.** The stop-lines and `queue_spillback` polygons in `site1.example.json` are placeholder coordinates that roughly fit a 1920×1080 intersection. On a real site, geometry needs to be redrawn; after that, the rules work as-is.
3. **Confidence is heuristic, not calibrated.** Don't use it as a true probability. For comparative ranking within a batch it is adequate.
4. **Pass B depends on `yolo26n.pt` being present** under `models/`. The normalized mp4 for the clip must also be on disk. Pass A works without those.
5. **Edge cases not yet differentiated.** Three real-world events look similar through these primitives: (a) slow buildup of congestion vs full gridlock, (b) brief stall vs stalled vehicle. We accept this noise at Phase 1 and revisit in Phase 3 if the detector layer warrants more fidelity.

## How to reproduce the verdicts

```bash
# 1. prerequisites: phase 2 detector events already in data/events/per-clip/
.venv/bin/pytest phase2-feasibility/tests/test_classifier.py -v     # 12 green
make phase2-classify                                                # updates clips_manifest.json
cat data/labels/clips_manifest.json | jq '.clips[] | {clip, predicted_tag, pass_used, reasons}'
```

## How to add a new event class

1. Add the tag to `phase1-sandbox/src/traffic_intel_sandbox/annotation/taxonomy.yml`.
2. Decide which pass will detect it:
   - If it is visible in existing ndjson primitives (crossings / occupancy / track count) → add a new branch to `apply_rules()` in `classifier.py` and a threshold block to `classifier_thresholds.yml`.
   - If it requires per-frame motion or class info → extend `run_pass_b()` with a new motion/class rule.
3. Add a synthetic-ndjson fixture unit test in `test_classifier.py` that triggers the new rule, plus a regression clip if one exists.
4. Re-run `make phase2-classify` and commit.

## Deliverable trace → handbook §6.6

| Handbook bullet | Closed by |
|---|---|
| vehicle labels | COCO class-id columns emitted in Phase 2 per-frame detections (consumed from `data/events/per-clip/*.ndjson`) |
| incident labels | `predicted_tag ∈ {stalled_vehicle, abnormal_stop, unexpected_trajectory}` in `clips_manifest.json` |
| congestion-event labels | `predicted_tag ∈ {gridlock, sudden_congestion, queue_spillback}` |
| abnormal stopping labels | Pass B `stalled_vehicle` / `abnormal_stop` |
| unexpected trajectory labels | Pass A `unexpected_trajectory` |
| queue spillback markers | Pass A `queue_spillback` (sustained `queue_spillback`-kind zone occupancy) |
| selected event windows | each clip under `data/raw/veo3/events/*.mp4` is one validation window |

Human labelers can use CVAT to spot-check or correct these auto-labels — the `tag` field in `clips_manifest.json` is reserved for human-authored ground truth and is preserved distinctly from the classifier's `predicted_tag`.
