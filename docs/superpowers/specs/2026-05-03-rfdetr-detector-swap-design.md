# RF-DETR detector swap

**Status:** built, live-validated 2026-05-03
**Author:** brainstormed with the user (sections 1–3 explicitly approved; sections 4–6 below were collapsed at user request to skip the review gate)

## Problem

The traffic-intel pipeline runs Ultralytics YOLO via `model.track(...)` in two
places:

- `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/tracker.py` —
  the live FastAPI thread that drives the dashboard.
- `phase2-feasibility/src/traffic_intel_phase2/detect_track.py` — the
  heavier feasibility runner (BoT-SORT, supervision overlays, homography,
  MJPEG).

The user wants to evaluate Roboflow's RF-DETR as a drop-in vehicle detector
to see if it gives better detections on the Wadi Saqra footage.

## Decisions (locked during brainstorming)

| Question | Choice |
|---|---|
| Scope | Both phase 2 and phase 3 |
| Strategy | Pluggable backend behind one interface, env-var switched; RF-DETR is the default, YOLO stays as a one-line fallback |
| Tracker for RF-DETR side | `supervision.ByteTrack` (already a transitive dep) — and we move the YOLO side to the same external tracker so the comparison is detector-vs-detector, not detector+tracker-vs-detector+tracker |
| Model size | `rfdetr-base` default; `RFDETR_SIZE=base|large` env knob |
| Eval rigor | Quantitative CSV + side-by-side annotated MP4 per backend |
| Rollback | `DETECTOR_BACKEND=ultralytics` flips back without code changes |

## Architecture

New package `traffic_intel_detector` under `phase3-fullstack/src/`:

```
traffic_intel_detector/
  __init__.py              public re-exports
  base.py                  DetectorBackend Protocol
  ultralytics_backend.py   UltralyticsBackend  (80-class COCO IDs 2,3,5,7)
  rfdetr_backend.py        RFDetrBackend       (91-class COCO IDs 3,4,6,8)
  tracking.py              ByteTrackWrapper    (supervision.ByteTrack)
  factory.py               build_detector(env), build_tracker(env)
```

**Common interface:**

```python
class DetectorBackend(Protocol):
    name: str
    def detect(self, frame_bgr: np.ndarray) -> sv.Detections: ...
    def warmup(self, frame_bgr: np.ndarray) -> None: ...
    def info(self) -> dict: ...
```

Both backends emit `supervision.Detections` so downstream zone/line code
doesn't care which detector is active.

**Critical detail — class IDs differ.** Ultralytics ships 80-class COCO,
where `car=2, motorcycle=3, bus=5, truck=7`. RF-DETR ships 91-class
1-indexed COCO, where `car=3, motorcycle=4, bus=6, truck=8`. The
vehicle-class filter lives **inside each backend**, not in the caller.

## Per-path integration

### Phase 3 (`tracker.py`)

- `from ultralytics import YOLO` removed; replaced with
  `from traffic_intel_detector import build_detector, build_tracker`.
- `model.track(frame, persist=True, tracker=...)` replaced with the pair
  `detections = detector.detect(frame); tracked = tracker.update(detections)`.
- `boxes.id` / `boxes.xyxy` reads converted to `tracked.tracker_id` /
  `tracked.xyxy`.
- `_annotate_jpeg(frame, res, ...)` → `_annotate_jpeg(frame, tracked, ...)`;
  the box/ID overlay was rewritten to consume `sv.Detections`.
- The legacy `TrackerConfig.model_path` is honored on the `ultralytics`
  path via the `YOLO_WEIGHTS` env var so existing site configs keep
  working with no DB migration.

### Phase 2 (`detect_track.py`)

- `from ultralytics import YOLO` removed.
- The `model.track(source=...)` streaming generator replaced with a manual
  `cv2.VideoCapture` + `detector.detect()` + `tracker.update()` loop.
- `sv.Detections.from_ultralytics(result)` removed (backends emit
  `sv.Detections` natively).
- The `--tracker` CLI flag becomes a no-op with a deprecation warning when
  it specifies anything other than ByteTrack — we standardized on
  supervision ByteTrack across both backends.
- The `model.names.get(cid)` label lookup was replaced with the
  per-detection `data["class_name"]` field that supervision populates from
  both backends.

### Explicitly NOT touched

Zone definitions, signal-timing logic, FastAPI routes, JWT/RBAC, SQLite
schema, dashboard, LLM advisor, forecast model, signal-plan anchoring,
camera-motion homography (phase 2), the MJPEG broadcaster, the per-bin
NDJSON sink.

## Eval harness

`phase3-fullstack/scripts/bench_detectors.py`:

- Iterates every `--backends` spec (`ultralytics`, `rfdetr-base`,
  `rfdetr-large`) over the same `--seconds N` window of `--source`,
  rewinding `CAP_PROP_POS_FRAMES` between runs so each backend sees the
  same frames.
- Each run uses a **fresh** `ByteTrackWrapper` so trackers don't share
  state.
- Per-backend artifacts written to `bench/<UTC timestamp>/`:
  - `<spec>.mp4` — annotated video with boxes, IDs, per-approach HUD.
  - One row in `summary.csv` with `frames`, `fps_mean`, `latency_p50/p95`,
    `vram_peak_mb`, `total_detections`, `unique_tracks`,
    `crossings_{N,S,E,W}`.
- `manifest.json` captures GPU model, torch version, driver, host, the
  full backend list, and the CLI args used.

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `DETECTOR_BACKEND` | `rfdetr` | `ultralytics` to fall back |
| `RFDETR_SIZE` | `base` | `base` or `large` |
| `DETECTOR_DEVICE` | `cuda` | reported only — RF-DETR auto-places to CUDA |
| `DETECTOR_FP16` | `1` | applies to ultralytics; rfdetr default fp32 unless `optimize_for_inference()` upgrades it |
| `YOLO_WEIGHTS` | `<repo>/yolo26n.pt` | only used when `DETECTOR_BACKEND=ultralytics` |
| `TRACKER_FRAME_RATE` | `10` | feeds into ByteTrack timing |

## Dependencies

- `rfdetr` 1.6.5 (pip-installed; pulled `transformers 5.7`,
  `huggingface_hub 1.13`, `peft 0.19` as side effects). No in-repo
  consumer of `transformers` or `huggingface_hub`, so the bumps are safe.
- `supervision` already at 0.27, exposes `sv.ByteTrack` with the
  parameters used.
- `.venv` lives on an external drive that mounts at
  `/media/admin1/.../...fe1` — the repo symlink expects `...fe`. The
  recovery is documented in project memory.

## Rollback

```bash
DETECTOR_BACKEND=ultralytics scripts/run_full_stack.sh   # phase 3
DETECTOR_BACKEND=ultralytics phase2-detect ...           # phase 2
```

Existing `.pt` weights (yolo11n-seg, yolo26n/m/l/x) remain on disk for
this purpose. No code change required.

## Measured baseline (smoke run, 2026-05-03)

5-second window of `data/calibration_pack/real/img_5210/full.mp4` on
RTX 3060 Laptop (6 GB):

| Backend | FPS | p50 lat | VRAM | Dets | Tracks | Total cross. |
|---|---|---|---|---|---|---|
| ultralytics (yolo26n) | 16.5 | 17.9 ms | 38.5 MB | 3398 | 83 | 45 |
| rfdetr-base | 4.4 | 203.8 ms | 296.8 MB | 3707 | 78 | 58 |

RF-DETR-base finds ~9% more detections per frame and 29% more crossings
on the same clip — but at one-quarter the throughput. **At 4.4 FPS on
this GPU it cannot keep up with the 10 FPS ingest target.** Tuning
options for follow-up: lower input resolution
(`RFDETRBase(resolution=560)`), batch-2 inference, or fall back to
ultralytics for the live path while keeping RF-DETR available for the
offline bench.

## Risks / open questions

1. RF-DETR live throughput (4.4 FPS) is below ingest cadence — the
   tracker thread will drop frames. The user accepted this trade-off to
   get a visible side-by-side comparison.
2. Class-name strings differ between backends (e.g. RF-DETR may say
   "car" / "truck" / "bus", ultralytics says the same in 80-class
   space) — labels come from each backend's `class_name` data field, so
   downstream code that pattern-matches on class strings should be
   audited if any exists.
3. The optimize-for-inference path emits a `transformers` deprecation
   warning ("`use_return_dict` is deprecated"). Cosmetic, ignored.
