# Traffic-Intel — Algorithms, Event Mesh & Traffic Recommendation Reference

Single reference for every algorithm, formula, threshold, and event-mesh mechanism in the first-site build. Every claim cites the source file and line.

---

## Table of Contents
1. [Event Mesh (Message Bus)](#1-event-mesh-message-bus)
2. [Computer Vision Pipeline](#2-computer-vision-pipeline)
3. [Forecasting Algorithms](#3-forecasting-algorithms)
4. [Incident & Event Detectors](#4-incident--event-detectors)
5. [Fusion Layer](#5-fusion-layer)
6. [Webster's Formula — Signal Timing Recommendation](#6-websters-formula--signal-timing-recommendation)
7. [Video-Anchored Signal Simulator](#7-video-anchored-signal-simulator)
8. [Endpoint ↔ Algorithm Map](#8-endpoint--algorithm-map)

---

## 1. Event Mesh (Message Bus)

Location: `phase3-fullstack/src/traffic_intel_phase3/bus/`

### 1.1 Features

| Feature | Detail |
|---|---|
| **Pluggable backends** | `AsyncioBus` (default, stdlib only), `KafkaBus` (aiokafka), `RabbitMQBus` (aio-pika). One Protocol, three implementations. |
| **Runtime selection** | `TRAFFIC_INTEL_BUS={asyncio\|kafka\|rabbitmq}` — no code change to switch. |
| **Canonical topic catalog** | `bus/topics.py` `Topic(StrEnum)`. Every backend writes/reads the same topic strings. |
| **Typed envelope** | `BusMessage(topic, payload, site_id, producer, ts_unix)` — JSON-serialisable. |
| **Sync + async publish** | `await bus.publish(msg)` from async contexts, `bus.publish_threadsafe(msg)` from daemon threads (tracker, signal sim). |
| **At-most-once semantics (asyncio)** | In-process, unbounded queue, non-durable. |
| **Durable semantics (Kafka / RabbitMQ)** | Broker-side persistence + consumer groups / durable queues. |
| **Subscriber isolation** | Per-subscriber task; a failing handler logs and continues without killing the bus. |
| **Idempotent start/stop** | Tied to FastAPI lifespan; stop cancels drainer tasks cleanly. |
| **Singleton factory** | `get_bus()` returns the process-wide instance (reset helper available for tests). |
| **Additive integration** | Publishes happen *alongside* the existing WebSocket fanout — SPA UX unchanged whether a broker is wired or not. |

### 1.2 Topic catalog

| Topic | Producer | Payload shape |
|---|---|---|
| `detector.counts` | Tracker bin callback (`server._broadcast_bin`) | `{bin_start, bin_end, seconds, in_zone, crossings_in_bin, crossings_total, fps}` |
| `signal.events` | Signal simulator (`server._broadcast_signal`) | `{timestamp, intersection_id, phase_number, phase_name, signal_state, duration_s, cycle_number}` |
| `incidents.detected` | Event engine (`server._broadcast_event`) | `{ts, event_type, approach, severity, confidence, payload{}, snapshot{}}` |
| `forecasts.generated` | `forecast/bridge.py` (reserved) | `{made_at, target_ts, approach, horizon_min, demand_pred, model_version}` |
| `recommendations.created` | `fusion.webster_*` (reserved) | `{ts, mode, cycle_s, ns_green, ew_green, delay_est_s, component_json}` |
| `ingest.errors` | Acquisition layer (reserved) | `{ts, source, reason, record}` |
| `audit.events` | Auth middleware (reserved) | `{ts, user_id, username, role, action, resource, payload, ip}` |

### 1.3 Backend matrix

| Backend | Dependency | Install | Broker required | Persistence | Use case |
|---|---|---|---|---|---|
| `asyncio` | stdlib | — | No | In-memory | Default / single-box |
| `kafka` | `aiokafka>=0.11` | `pip install 'traffic-intel[kafka]'` | Kafka 2.8+ | Log on broker | Multi-process / multi-host |
| `rabbitmq` | `aio-pika>=9.4` | `pip install 'traffic-intel[rabbitmq]'` | RabbitMQ 3.12+ | Durable queues | Multi-process, rich routing |

Kafka env: `TRAFFIC_INTEL_KAFKA_BOOTSTRAP`, `TRAFFIC_INTEL_KAFKA_CLIENT_ID`, `TRAFFIC_INTEL_KAFKA_GROUP_ID`.
RabbitMQ env: `TRAFFIC_INTEL_RABBITMQ_URL`, `TRAFFIC_INTEL_RABBITMQ_EXCHANGE` (topic exchange, default `traffic-intel`).

### 1.4 Wiring (server.py)

```python
_bus = get_bus()

def _broadcast_bin(record):
    ...                                            # existing WebSocket fanout
    _bus.publish_threadsafe(BusMessage(
        topic=Topic.DETECTOR_COUNTS, payload=record,
        site_id=_SITE_ID, producer="tracker",
    ))

@app.on_event("startup")
async def _startup():
    await _bus.start()
    ...
@app.on_event("shutdown")
async def _shutdown():
    ...
    await _bus.stop()
```

### 1.5 Tests

`tests/phase3/test_bus_asyncio.py` — 5 cases: pub/sub roundtrip, topic isolation, threadsafe publish from daemon thread, factory defaults to asyncio, unknown-backend fallback.

---

## 2. Computer Vision Pipeline

### 2.1 Vehicle Detection — YOLO26

- **Model**: ultralytics 8.4.39 — YOLO26 family weights under repo root (`yolo26n.pt`, `yolo26l.pt`, `yolo26m.pt`, `yolo26x.pt`). Default tracker uses `yolo26n` (fast CPU) or `yolo26x` (higher precision).
- **Inference size**: `imgsz=960` (TrackerConfig default).
- **Confidence / IoU thresholds**: `conf=0.2, iou=0.5` — loose to favour recall so ByteTrack can stabilise weak detections.
- **Classes of interest**: COCO vehicle superset (car, motorcycle, bus, truck).
- **Entry point**: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/tracker.py::TrackerService`.

### 2.2 Multi-Object Tracking — ByteTrack

- **Library**: `supervision 0.27` + `boxmot 17` fallback.
- **Config**: `bytetrack.yaml` (ultralytics default, tuned for 8-15 fps video).
- **Track ID persistence**: across frames within one RTSP session; IDs re-mint on stream reconnect.
- **Sustained track requirement**: `WRONG_WAY_HISTORY = 15` frames before the direction-of-travel detector fires — filters out oscillation on weak detections.

### 2.3 Zone Counting & Crossing Detection

Location: `poc_wadi_saqra/counters.py`.

- **Polygon containment**: ray-casting point-in-polygon (`point_in_polygon` at L44) — O(n) per vertex.
- **Stop-line crossing**: segment-segment intersection test with CCW cross-product (`_ccw`, `segments_cross`) plus direction filter (`crossed_in_direction`). A track only counts as "crossing E→W" if its previous→current segment crosses the stop-line *in the approach's declared direction of travel*.
- **Zone registry**: loaded from `configs/sites/wadi_saqra_zones.json`. Each `Zone` has `approach`, `polygon` (N×2 int32), `stop_line` (two endpoints), `direction_of_travel ∈ {up,down,left,right}`.

### 2.4 Approach Labelling via Polygon + Direction Vectors

- **Approach map**: `{track_id → approach_letter | None}` computed per frame.
- **Direction vectors** (`events.py::_DIRECTION_VEC`): `{up: (0,-1), down: (0,1), left: (-1,0), right: (1,0)}` — origin top-left so y grows downward.
- **Used by**: wrong-way detector, queue counting, in-zone presence, per-approach arrival rate.

---

## 3. Forecasting Algorithms

Location: `phase3-fullstack/src/forecast_ml/`.

### 3.1 Feature Engineering

Bin size: **15 minutes** (`BIN_MIN = 15`, `BINS_PER_HOUR = 4`).
Horizons: **+0, +15, +30, +60 min** (`HORIZONS_BINS = [0, 1, 2, 4]`).

**12 features** (`feature_columns()`):

| Feature | Type | Meaning |
|---|---|---|
| `lag_1` | int | Count 1 bin ago (15 min) |
| `lag_2` | int | 2 bins ago (30 min) |
| `lag_4` | int | 4 bins ago (1 hr) |
| `lag_96` | int | 96 bins ago (**24 hr = same-hour yesterday**) |
| `lag_672` | int | 672 bins ago (**168 hr = same-hour same-day-of-week last week**) |
| `hour_sin` | float | `sin(2π × hour / 24)` |
| `hour_cos` | float | `cos(2π × hour / 24)` |
| `dow_sin` | float | `sin(2π × dayofweek / 7)` |
| `dow_cos` | float | `cos(2π × dayofweek / 7)` |
| `is_weekend` | int | 1 if Fri/Sat (MENA week) |
| `green_active_frac` | float | Share of this bin where this approach's signal was GREEN — from `signal_events` |
| `detector_code` | categorical | LGB native categorical handling |

Sin/cos encoding guarantees cyclicity (23:45 is close to 00:15).

### 3.2 LightGBM Gradient Boosted Regression

- **Library**: `lightgbm 4.6`.
- **Structure**: **4 independent regressors** (one per target column: `y_now`, `y_15min`, `y_30min`, `y_60min`). Multi-output without coupling.
- **Hyperparameters** (train.py): `num_boost_round=300`, `early_stopping=30` on val, `objective=regression_l1` (MAE), categorical feature = `detector_code`.
- **Training set**: 38,790 rows; **validation**: 9,698 rows (final 20 % chronologically — no future→past leakage).
- **Persistence**: all four models serialised into a single JSON-of-strings at `models/forecast_lgb.json` via `model.model_to_string()`.
- **Metrics** (veh per 15-min bin per detector):

| Horizon | MAE | Improvement vs persistence |
|---|---|---|
| y_now | 6.283 | 48 % |
| y_15min | 6.360 | 68 % |
| y_30min | 6.247 | 78 % |
| y_60min | 6.105 | **85 %** |

### 3.3 LSTM (scaffolded, skipped this run)

`forecast_ml/train.py::_train_lstm`. Small PyTorch sequence-to-one: the 5 lag values become a 5-step sequence.

```python
LSTM(input_size=1, hidden=16, num_layers=1) → Linear(16, 4) → ReLU → Linear(4, 1)
```

Trained with Adam, MAE loss, 8 epochs. **Not run** for this build (`--skip-lstm`) because LGB already met targets; handbook completeness only.

### 3.4 Persistence Baseline

`_persistence_baseline()`:

```python
pred = X_va["lag_1"]                                   # for every horizon
mae[col] = mean(|pred − y_va[col]|)
```

The *"predict same as last bin"* strawman every forecaster must beat.

### 3.5 Gmaps-Anchored Heuristic

`poc_wadi_saqra/fusion.py::_phase_flow_ratio_hcm` wiring + `server.py::api_forecast_compare`.

Gmaps delivers a **congestion index** (ratio = current_duration / free_flow_duration) and a discrete label (`free|light|moderate|heavy|jam`). It is *not* a flow; we convert to veh/15-min via:

```python
HCM_SAT = 30 * 15 * 2                            # 30 veh/min/lane × 15 min × 2 lanes = 900
TYPICAL_UTIL_AT_FREE = 0.25
util = min(0.7, TYPICAL_UTIL_AT_FREE + max(0, ratio − 0.8) × 0.35)
flow_veh_per_15min = util × HCM_SAT
```

Interpretation:
- ratio ≤ 0.8 (free flow) → util = 0.25 → 225 veh/15-min
- ratio = 1.3 (moderate)  → util = 0.425 → 383 veh/15-min
- ratio = 2.0 (heavy)     → util = 0.67 → 603 veh/15-min
- ratio ≥ 2.06 (jam)      → util = 0.7 (capped) → 630 veh/15-min

Treat as a **typical-day reference curve**, never as ground truth.

### 3.6 Pressure Score & Classification

`fusion.py::gmaps_intensity` and `classify_pressure`:

```python
base = max(0, ratio - 0.8) * 5.0
label_boost = {"free":0, "light":3, "moderate":7, "heavy":12, "jam":20}[label]
intensity = max(base, 0.6 × label_boost + base)
```

With live tracker added:

```python
pressure = gmaps_intensity × (1 + live_multiplier)     # live_multiplier ∈ [0, 0.5]
label = {p<3: free, <7: light, <12: moderate, <20: heavy, ≥20: jam}
```

---

## 4. Incident & Event Detectors

Location: `poc_wadi_saqra/events.py`.

### 4.1 Stalled Vehicle

```python
STOP_DISP_PX       = 3.0     # centroid motion < 3 px ⇒ stationary
STALL_DURATION_S   = 20.0    # stationary ≥ 20 s in any zone
```

Fires once per track (`stalled_emitted = True`), resets when track exits the zone or starts moving.

- Severity: `warning`, confidence: 0.8
- Payload: `{track_id, stationary_seconds}`

### 4.2 Abnormal Stopping

Stopped **during own approach's GREEN phase** for ≥ 8 s.

```python
STOP_DURATION_S = 8.0
```

Fire-once-per-green-phase debounce (`abnormal_emitted_for_phase_start`).

- Severity: `warning`, confidence: 0.7
- Payload: `{track_id, stationary_seconds, signal_phase, signal_state}`

### 4.3 Wrong-Way

```python
WRONG_WAY_HISTORY            = 15     # frames of history
WRONG_WAY_MIN_SPEED_PX_PER_S = 8.0    # must be actually moving
WRONG_WAY_DOT                = -0.30  # dot(actual, expected) ≤ -0.3 ⇒ opposite
```

Math:
```python
dx, dy = pos[-1] - pos[0]                         # path vector over 15 frames
speed  = hypot(dx, dy) / dt
v̂      = (dx, dy) / |(dx, dy)|                    # unit vector
expected = _DIRECTION_VEC[approach_direction]     # e.g. (-1, 0) for W→E
dot    = v̂ · expected                             # range [-1, 1]
if speed >= 8 and dot <= -0.30: fire
```

Fire-once-per-track. Severity `critical`, confidence 0.85.

### 4.4 Queue Spillback

```python
SPILLBACK_QUEUE_THRESHOLD  = 20    # cars in the approach zone
SPILLBACK_MIN_DURATION_S   = 10.0  # sustained
```

Fires once per streak, then mutes for 30 s (`above_since = bin_end + 30.0`).

- Severity: `critical`, confidence: 0.9
- Payload: `{queue_count, queue_length_m = count × 7 m, threshold, duration_s}`

### 4.5 Congestion Class Change (Sudden Buildup)

State-machine over `{free, light, moderate, heavy, jam}` with hysteresis:

```python
CONGESTION_HYSTERESIS_S = 5.0   # new class must persist ≥ 5 s before firing
```

Each approach has `last_label`, `pending_label`, `pending_since`. Transitions fire `congestion_class_change` with `direction = up|down` from `_CLASS_RANK`.

- Severity: mapped from target class (`_severity_from_class`)
- Payload: `{from, to, direction, pressure, gmaps_label, queue_count, queue_length_m}`

### 4.6 Why hysteresis?

The pressure score is computed per bin (15 s) so it flickers at class boundaries. Without hysteresis, the operator dashboard spams `free↔light↔free` transitions. 5 s debounce empirically cuts the event stream by ~70% without losing real transitions.

---

## 5. Fusion Layer

Location: `fusion.py::fuse` and `build_heatmap`.

### 5.1 Per-approach fused state

For each approach `a ∈ {N, S, E, W}`:

```python
gmaps_row       = load_gmaps(_gmaps_path, current_local_hour)[corridor_for(a)]
intensity       = gmaps_intensity(gmaps_row)             # see §3.6
live_mult       = min(0.5, tracker.pressure(a) / SATURATION_PRESSURE)
pressure        = intensity × (1 + live_mult)
label           = classify_pressure(pressure)
demand_per_min  = crossings_last_bin × 60 / bin_seconds
in_zone         = len(tracks currently in zone(a))
```

Fused record:
```python
{
  "pressure": float,
  "label": "free|light|moderate|heavy|jam",
  "demand_per_min": float,
  "in_zone": int,
  "gmaps_ratio": float,
  "gmaps_label": str,
  "gmaps_speed_kmh": float,
}
```

### 5.2 Heatmap

`build_heatmap` produces a 24-hour × 4-approach grid of `(pressure, label, gmaps_ratio, gmaps_label, gmaps_speed_kmh, scale_vs_now)` for the Forecast page heatmap.

---

## 6. Webster's Formula — Signal Timing Recommendation

Location: `fusion.py::webster_two_phase` and `webster_three_phase`.

### 6.1 Classical Webster (1958)

Given a signalised intersection with total lost time **L**, saturation flow **s**, and arrival rates **q_i** on the critical lane group of each phase:

**Flow ratio per phase:**
```
y_i = q_i / s_i
```

**Sum of critical flow ratios:**
```
Y = Σ y_i     (must be < 1 for the intersection to be undersaturated)
```

**Optimum cycle length (minimises total delay):**
```
         1.5 L + 5
C_o = ─────────────       (seconds)
           1 − Y
```

**Effective green time:**
```
g_eff = C_o − L
```

**Green split per phase** (proportional to critical flow ratio):
```
g_i = (y_i / Y) × g_eff
```

**Total lost time:**
```
L = Σ (yellow_i + all_red_i)   = N_phases × (yellow + all_red)
```

### 6.2 Our parameter defaults

```python
saturation        = 30.0   veh/min/lane    # HCM 1800 veh/h/lane
yellow_per_phase  = 3.0    s
all_red_per_phase = 2.0    s
min_green         = 10.0   s               # per-phase floor
max_green         = 90.0   s               # per-phase ceiling
lane_count        = 2                      # per approach
# → capacity per approach = 30 × 2 = 60 veh/min = 900 veh/15-min
```

### 6.3 HCM flow-ratio (replaces naïve pressure-based ratio)

`_phase_flow_ratio_hcm` (L253–276):

```python
capacity_per_approach = saturation_flow_per_min × lane_count    # = 60 veh/min
for each approach a in phase:
    arrival = _approach_arrival_rate(row, cycle_seconds)
    y_a = arrival / capacity_per_approach
    y_a = clamp(y_a, 0.02, 0.95)
return max(y_a)    # critical lane group per Webster
```

Clamps at **[0.02, 0.95]** — prevents:
- `y → 0` from collapsing the cycle to the minimum (momentarily empty intersection)
- `y → 1` from blowing up `1/(1−Y)`

### 6.4 Arrival-rate fallback (queue proxy)

`_approach_arrival_rate` (L237–250):

```python
demand = row.demand_per_min            # live measured crossings / min
queue  = row.in_zone                   # cars currently in zone
queue_as_rate = queue × 60 / cycle_seconds     # treat queue = 1-cycle of arrivals
return max(demand, queue_as_rate)
```

**Why the fallback matters.** When an approach is on RED, `demand_per_min` reads 0 (no one is crossing), but the queue is piling up. Using the queue as "arrivals accumulated over one cycle" keeps Webster honest when a phase is held red. `max()` uses whichever is larger — live flow while green, queue-proxy while red.

### 6.5 Webster's uniform delay (for comparison)

```
        0.5 · C · (1 − g/C)²
d = ────────────────────────────
       1 − (g/C) · x
```
where
- `C` = cycle length
- `g` = effective green for this phase
- `x = min(0.98, y · C / g)` = degree of saturation

Implemented in `_delay()` (L400 and L585 for 3-phase). This is the **uniform** term of the HCM delay equation — the incremental (random + oversaturation) terms are dropped because near-saturation behaviour is handled by the separate near-saturation guard (§6.7).

### 6.6 2-phase vs 3-phase

**2-phase** (`webster_two_phase`, L290): NS (N+S) and EW (E+W) open together.
- Lost time `L = 2 × (yellow + all_red) = 10 s`.

**3-phase** (`webster_three_phase`, L450): NS → E → W in sequence (the **actual** Wadi Saqra field plan).
- Lost time `L = 3 × (yellow + all_red) = 15 s`.
- Split: `g_NS, g_E, g_W = (y_NS, y_E, y_W) / Y × g_eff` — three independent flow ratios, three independent critical approaches.

Current field plan: `{NS_green: 35, E_green: 35, W_green: 35, yellow: 3, all_red: 2}` → 120 s cycle.

### 6.7 Near-saturation guard (the "never worse than the field plan" rule)

Near saturation, Webster's formula-optimal cycle grows very long (`C → ∞` as `Y → 1`), which the uniform-delay term penalises for phases with small `y`. The computed plan can be **worse** than the currently-running plan.

Logic:

```python
d_cur = _delay(cur_cycle, cur_NS, y_NS) + _delay(cur_cycle, cur_EW, y_EW)
d_rec = _delay(rec_cycle, rec_NS, y_NS) + _delay(rec_cycle, rec_EW, y_EW)

near_saturation = (Y >= 0.85) or (d_rec >= d_cur)

if near_saturation and d_rec >= d_cur:
    # echo the field plan verbatim; show delay_reduction_pct = 0
    rec = current
    improvement = 0.0
else:
    improvement = 100 × (d_cur − d_rec) / d_cur
```

This is the fix for the `−76.9 % delay reduction` bug observed pre-HCM migration. The dashboard now guarantees "we never recommend a plan we can prove is worse."

### 6.8 Green-time clamps

```python
g_NS = clamp(g_NS, min_green=10, max_green=90)
g_EW = clamp(g_EW, min_green=10, max_green=90)
```

Max-green 90 s prevents cycles that starve cross-streets. Min-green 10 s prevents phases too short for pedestrian crossings and start-up lost time.

### 6.9 Output schema

```json
{
  "mode": "three_phase",
  "cycle_seconds": 115.0,
  "lost_time_seconds": 15.0,
  "flow_ratio_total": 0.42,
  "phases": {
    "NS": {"green_seconds": 38.4, "flow_ratio": 0.18, "approaches": {...}},
    "E":  {"green_seconds": 30.2, "flow_ratio": 0.12, "approaches": {...}},
    "W":  {"green_seconds": 31.4, "flow_ratio": 0.12, "approaches": {...}}
  },
  "per_approach": {"N": {...}, "S": {...}, "E": {...}, "W": {...}},
  "near_saturation": false,
  "comparison": {
    "current":     {"NS_green": 35, "E_green": 35, "W_green": 35, "cycle_seconds": 120, "uniform_delay_sec_per_veh": 24.6},
    "recommended": {"NS_green": 38.4, "E_green": 30.2, "W_green": 31.4, "cycle_seconds": 115, "uniform_delay_sec_per_veh": 22.1},
    "delay_reduction_pct": 10.2,
    "near_saturation": false
  }
}
```

### 6.10 Forecast-based recommendation

`/api/recommendation/forecast` (server.py) runs the same Webster machinery but feeds it **predicted** demand (`forecast_ml` at +1 h) instead of live demand, and also reports the peak congestion horizon in the next 2 h. This is the signal that drives the AnticipatedCongestionBanner.

---

## 7. Video-Anchored Signal Simulator

Location: `poc_wadi_saqra/signal_sim.py`.

**Purpose**: The source RTSP is a looping MP4. To give realistic signal-phase labels on the dashboard, the sim is **anchored** to the video's timeline:

```python
anchor = VideoAnchor(phase_name="E", video_ts=23.0)
# At video_ts=23 s (every loop), the E phase begins GREEN.
```

The sim then free-runs forward from that anchor through the 3-phase cycle (NS → E → W, 35 s each + 3 s yellow + 2 s all-red = 120 s cycle) until the next loop restart, when it resynchs.

**Why:** without the anchor, sim and video drift; the Live page shows "NS GREEN" while the actual footage shows E flowing. With the anchor, `/api/signal_state` is always consistent with what the operator sees on screen.

**Fail-loud invariant:** if the configured `phase_name` isn't a valid phase in the active cycle definition, startup raises. The old silent-fallback produced hours of wrong labels before anyone noticed.

---

## 8. Endpoint ↔ Algorithm Map

| Endpoint | Algorithm / module | Auth |
|---|---|---|
| `/mjpeg` | YOLO26 + ByteTrack annotated frames (§2) | viewer |
| `/api/counts` | Tracker zone counters (§2.3) | viewer |
| `/api/gmaps` | Gmaps row loader (§3.5) | viewer |
| `/api/fusion` | Fusion layer (§5) | viewer |
| `/api/heatmap` | `build_heatmap` (§5.2) | viewer |
| `/api/forecast/ml` | LightGBM bundle (§3.2) | viewer |
| `/api/forecast/ml/metrics` | Static JSON from `models/forecast_metrics.json` | viewer |
| `/api/forecast/demand_15min` | Historical `detector_counts` + LGB append | viewer |
| `/api/forecast/compare` | LGB (§3.2) vs gmaps heuristic (§3.5) | viewer |
| `/api/recommendation/current` | `webster_three_phase` on live demand (§6) | viewer |
| `/api/recommendation/forecast` | `webster_three_phase` on +1 h predicted demand (§6.10) | viewer |
| `/api/incidents` | Event detectors (§4) | viewer |
| `/api/signal_state` | Video-anchored sim (§7) | viewer |
| `/api/ingest/detector_log` | External NDJSON ingest | operator |
| `/api/ingest/signal_log` | External NDJSON ingest | operator |
| `/api/ingest/metrics` | Acquisition metrics | viewer |
| `/api/system/isolation` | `assert_no_outbound_writes.sh` | viewer |
| `/api/audit/log` | `audit_log` table | admin |
| `ws /ws/counts` | Fanout of detector bins | viewer |
| `ws /ws/signal` | Fanout of signal events | viewer |
| `ws /ws/events` | Fanout of incidents | viewer |

Each `/ws/*` also publishes to the matching `bus/topics.py::Topic.*` — so the same events are available on Kafka/RabbitMQ if a downstream consumer is wired.

---

## 9. Known Algorithmic Limitations

| Area | Limitation | Impact |
|---|---|---|
| LGB | Single chronological 80/20 split; early-stop target = val set | True generalisation error is probably ~10 % worse than reported (~6.7 MAE instead of 6.1) |
| LGB | Per-detector model; approach-level error = sum of correlated detector errors | Approach MAE ≈ 15–25 veh (S/N), 8–12 veh (E/W) |
| LGB | Predictions above 900 veh/15-min/approach are outside training range | Dashboard caps interpretation; Webster's `clamp(y, 0.02, 0.95)` handles the rest |
| Gmaps | Ratio→veh heuristic is approximation only, not calibrated per site | Reference curve, not a predictor |
| YOLO + tracker | Loop re-mints track IDs per video loop | `wrong_way` counts inflate; documented in limitations.md |
| Webster | Uniform-delay term only (no incremental/oversaturation terms) | Underestimates delay at `Y > 0.9`; mitigated by near-saturation guard |
| Webster | `saturation = 30 veh/min/lane` is HCM default, not measured | Field calibration would shrink `y` and shorten recommended cycles |
| Spillback | Threshold = 20 cars is static | Does not adapt to zone size; works because Wadi Saqra zones are sized similarly |
| Stalled/stop | Pixel displacement threshold does not account for perspective | Vehicles far from camera may appear stationary; partially mitigated by only firing for in-zone tracks |

---

*Generated 2026-04-23 from repo HEAD. Re-generate whenever `fusion.py`, `events.py`, or `forecast_ml/` change.*
