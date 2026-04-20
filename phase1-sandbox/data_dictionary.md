# Data Dictionary — Phase 1 Sandbox

Authoritative reference for every field in every artifact the sandbox produces.

---

## 1. Detector Counts (`data/detector_counts/counts_YYYY-MM-DD.parquet`)

Format: Apache Parquet, Zstandard compression. One row per `(detector, 15-min bin)`. Expected rows per day: **22 × 96 = 2 112**.

| Column | Arrow type | Units | Domain / constraints | Notes |
|---|---|---|---|---|
| `timestamp` | `timestamp[ns, UTC]` | — | Aligned to `:00 :15 :30 :45` | Bin **start** time |
| `intersection_id` | `string` | — | `^[A-Z0-9_-]+$` | Matches `metadata.intersection_id` |
| `detector_id` | `string` | — | `DET-{approach}-{lane}-{index}` | 22 unique per day |
| `approach` | `string` | — | `{N, S, E, W}` (plus diagonals if defined) | |
| `lane` | `int16` | — | 1-based within approach | |
| `lane_type` | `string` | — | `{through, left, right, shared, bus, bike}` | |
| `vehicle_count` | `int32` | vehicles / 15 min | ≥ 0 | Poisson draw per minute, summed |
| `occupancy_pct` | `float32` | % | [0, 95] | Heuristic from count + lane type |
| `quality_flag` | `int8` | — | `0` ok, `1` estimated, `2` gap-filled | All `0` in synthetic data |

Partitioning convention: one file per day; filename carries the date.

---

## 2. Signal Timing Log (`data/signal_logs/signal_YYYY-MM-DD.ndjson`)

Format: newline-delimited JSON. One event per line.

```json
{"timestamp":"2026-04-20T08:15:32.120Z","intersection_id":"SITE1","phase":2,"state":"GREEN_ON"}
```

| Field | Type | Units / format | Domain |
|---|---|---|---|
| `timestamp` | string | ISO 8601 with ms, UTC `Z` | — |
| `intersection_id` | string | — | matches detector counts |
| `phase` | int | NEMA phase number | `{1..8}` |
| `state` | string | — | `{GREEN_ON, YELLOW_ON, RED_ON, PED_WALK, PED_FLASH}` |

**Invariants:** within a single phase, state sequence is `GREEN_ON → YELLOW_ON → RED_ON`. Next phase begins with its own `GREEN_ON`. Nominal cycle 102 s (configurable, ±4 s jitter).

---

## 3. Intersection Metadata (`data/metadata/site1.json`)

Governed by `phase1-sandbox/src/traffic_intel_sandbox/metadata/intersection_schema.json` (JSON Schema draft 2020-12).

### 3.1 Top-level fields
| Field | Type | Required | Description |
|---|---|---|---|
| `intersection_id` | string | ✓ | Stable site identifier |
| `location` | object | ○ | `{lat, lon, city, country, osm_node_id}` |
| `camera` | object | ✓ | Camera pose + stream info |
| `approaches` | array | ✓ | Ordered list of approach definitions |
| `stop_lines` | array | ✓ | Pixel polylines per approach |
| `monitoring_zones` | array | ✓ | Named pixel polygons for detection rules |
| `signal_plan_ref` | string | ○ | Path/URI to the phase plan YAML |

### 3.2 `camera`
| Field | Type | Units | Notes |
|---|---|---|---|
| `stream_url` | uri | — | RTSP/RTMP/HLS endpoint |
| `resolution` | `[int,int]` | px | `[width, height]` |
| `fps` | int | frames/s | 5–30 accepted, 10 canonical |
| `fov_deg` | number | degrees | Horizontal field of view |
| `mounting_height_m` | number | metres | Optional but recommended |
| `bearing_deg` | number | degrees, compass | Camera optical axis |

### 3.3 `approaches[].lanes[]`
| Field | Type | Domain |
|---|---|---|
| `id` | string | e.g. `"N-2"` |
| `type` | string | `{through, left, right, shared, bus, bike}` |
| `detector_id` | string | cross-references detector counts |
| `width_m` | number | 1.5–6.0 |

### 3.4 `stop_lines[]` and `monitoring_zones[]`
Pixel coordinates in the camera frame. Origin top-left, x→right, y→down.

- `stop_lines[].polyline_px`: `[[x,y], ...]` (≥2 points)
- `monitoring_zones[].polygon_px`: `[[x,y], ...]` (≥3 points, closed implicitly)
- `monitoring_zones[].kind`: `{queue_spillback, approach_area, conflict_zone, ped_crossing}`

---

## 4. Annotation Pack (`data/annotations/`)

### 4.1 Object bounding boxes — `coco/*.json` and `yolo/*.txt`
Class IDs (stable across all exports):

| id | name |
|---|---|
| 0 | car |
| 1 | truck |
| 2 | bus |
| 3 | motorcycle |
| 4 | bicycle |
| 5 | pedestrian |

Formats:
- **COCO**: standard `images[]`, `annotations[]`, `categories[]` JSON.
- **YOLO**: one `.txt` per frame, `class_id x_center y_center w h` (all normalized 0–1).

### 4.2 Event windows — `events/*.csv`

| Column | Type | Description |
|---|---|---|
| `clip_id` | string | filename stem of historical clip |
| `start_frame` | int | 0-based, inclusive |
| `end_frame` | int | 0-based, inclusive |
| `tag` | string | `{stalled_vehicle, abnormal_stop, unexpected_trajectory, queue_spillback, sudden_congestion, normal}` |
| `notes` | string | free-form annotator comment |

---

## 5. Source list (`phase1-sandbox/configs/sources.yml`)

```yaml
sources:
  - slug: <filename-stem>      # required
    url:  <youtube-or-stream-url>  # required
    description: <free text>   # optional — copied into methodology.md
    start: "HH:MM:SS"          # optional yt-dlp trim start
    end:   "HH:MM:SS"          # optional yt-dlp trim end
    tags:  [day, night, ...]   # optional metadata
```

---

## 6. Profiles config (`phase1-sandbox/configs/profiles.yml`)

See inline YAML comments. Key knobs:
- `baseline_rate` — off-peak vehicles per minute per detector (pre-multiplier).
- `peaks[]` — list of Gaussian pulses; each has `center_min`, `width_min`, `amplitude`.
- `weekday_multiplier`, `weekend_multiplier` — day-of-week scaling.
- `noise_pct` — multiplicative gaussian noise, σ as a fraction of rate.
- `detectors[]` — 22 detectors with `id`, `approach`, `lane`, `lane_type`, `base_multiplier`.

---

## 7. Phase plan config (`phase1-sandbox/configs/phase_plan.yml`)

```yaml
phases:
  - { number: <1..8>, name: <str>, green_s: <num>, yellow_s: <num>, all_red_s: <num> }
cycle_jitter_s: <num>    # ± seconds added per cycle to mimic actuation
```

---

## 8. Clip classification manifest (`data/labels/clips_manifest.json`)

Written by `phase2-classify` (rule-based classifier — see `phase1-sandbox/ground_truth.md`). Schema version 1.

Top-level:

```json
{
  "version": 1,
  "schema": "phase1-events-manifest/v1",
  "intersection_id": "SITE1",
  "note": "...",
  "clips": [ { ...per-clip block... } ]
}
```

Per-clip fields:

| Field | Type | Written by | Notes |
|---|---|---|---|
| `clip` | string | `phase2-detect` | Stem matching `data/normalized/events/<clip>.mp4` |
| `class` | string | human | Free-text description from prompt/source |
| `tag` | string \| null | **human only** | Reserved for hand-labeled ground truth; never overwritten by the classifier |
| `frames` | int | `phase2-detect` | Frame count at inference |
| `detections` | int | `phase2-detect` | Sum of per-frame detection counts |
| `tracks` | int | `phase2-detect` | Unique BoT-SORT track IDs seen |
| `line_events` / `zone_events` | int | `phase2-detect` | Count of ndjson events of each type |
| `line_crossings` | object | `phase2-detect` | `{N, S, E, W → int}` |
| `max_zone_occupancy` | int | `phase2-detect` | Max count observed in any monitoring zone |
| `latency_p50_ms` | float | `phase2-detect` | Inference p50 latency per frame |
| `artifacts` | object | `phase2-detect` | Paths to raw / normalized / annotated mp4s + ndjson |
| `interpretation` | array[string] | human | Free-text observations (optional) |
| `predicted_tag` | string | **`phase2-classify`** | One of: `normal`, `gridlock`, `queue_spillback`, `sudden_congestion`, `unexpected_trajectory`, `stalled_vehicle`, `abnormal_stop`, `pedestrian_interaction`, `insufficient_evidence` |
| `predicted_confidence` | float | **`phase2-classify`** | Heuristic margin [0.50 .. 0.99]; see `ground_truth.md` |
| `classifier_version` | string | **`phase2-classify`** | Pinned to `classifier_thresholds.yml → version` |
| `pass_used` | string | **`phase2-classify`** | `"A"` (ndjson rules) or `"B"` (video re-sample) |
| `reasons` | array[string] | **`phase2-classify`** | Human-readable explanation of which rule(s) fired |
