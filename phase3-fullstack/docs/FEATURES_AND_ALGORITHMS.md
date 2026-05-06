# Traffic-Intel — Features & Algorithms (Explainer)

A plain-language tour of the system: what each feature does, how the
algorithm works, the formulas behind it, and where to find the code.

For the formal reference (every threshold, every line cite), see
[`ALGORITHMS.md`](ALGORITHMS.md). This document is shorter and aimed at
"I want to understand how the system thinks."

---

## Top Features at a Glance

| # | Feature | One-line summary |
|---|---|---|
| 1 | Pluggable detectors (YOLO ↔ RF-DETR) | Swap CV backbone with one toggle; same tracker, same downstream pipeline. |
| 2 | ByteTrack multi-object tracking | Stable per-vehicle IDs across frames so we can count crossings, not blobs. |
| 3 | PCE-aware counting (HCM 6th ed.) | A bus is worth 2.0 cars; pressure is in PCE-units, not raw vehicles. |
| 4 | Per-lane subdivision | Lanes induced from real trajectories (Fréchet + DBSCAN) — no manual ROI required. |
| 5 | Camera-motion homography | ORB+RANSAC keeps zone polygons glued to the road as the camera drifts. |
| 6 | LightGBM 15-min demand forecast | Four boosted regressors, one per horizon (now / +15 / +30 / +60). |
| 7 | Google-typical-day prior | A 4×48 congestion grid that anchors live pressure to "what a normal Tuesday looks like." |
| 8 | Webster + HCM signal-timing advisor | Cycle/green-split optimiser; advisory only, with a near-saturation safety guard. |
| 9 | Video-anchored signal simulator | Phase labels stay locked to the video timeline using ffmpeg's start wall-clock. |
| 10 | Fusion layer | One dict per approach: counts + PCE + gmaps prior + pressure + label. |
| 11 | Incident detection | Wrong-way, stalled, abnormal-stop-during-green, queue spillback. |
| 12 | Drift monitor | FPS, signal-log freshness, model age, class-mix KL — all emit `drift_alert` incidents. |
| 13 | LLM advisor + 8 MCP tools | Operator-facing chat with tool calls into live state, history, forecast, recommendation. |
| 14 | JWT + bcrypt + 3-role RBAC | viewer / operator / admin, HS256, 30-min TTL. |
| 15 | Pluggable event mesh | Same publish API over AsyncioBus, Kafka, or RabbitMQ — flip via env var. |

---

## 1. Object Detection — YOLO ↔ RF-DETR

**What it does.** Looks at every video frame and returns vehicle
bounding boxes with class labels (car, motorcycle, bus, truck) and
confidence scores.

**How it works.** Two backends sit behind a `Detector` Protocol:

- **YOLO 26n (ultralytics)** — single-shot CNN, anchor-free,
  COCO 80-class indexing. Class IDs `{2: car, 3: motorcycle, 5: bus, 7: truck}`.
  `imgsz=960`, `conf=0.35`, `iou=0.5`. Runs on Apple MPS / CUDA / CPU.
- **RF-DETR (transformer)** — DETR-style encoder–decoder with refined
  reference points. Uses COCO 91-class (1-indexed) so the IDs are
  shifted: `{3: car, 4: motorcycle, 6: bus, 8: truck}`.

Both backends emit `supervision.Detections` so everything downstream
(tracker, counter, events) is detector-agnostic.

**The 80-vs-91 gotcha.** `supervision`'s wrapper for RF-DETR returns
the wrong `class_name` strings — labels were shifted by one (every
"car" was being shown as "motorcycle"). The fix is a canonical
`COCO_91_NAMES` table the backend uses to overwrite the broken names
post-detection. Without this override the dashboard would still
display the wrong labels even though the IDs were correct.

**Source.** `phase3-fullstack/src/traffic_intel_detector/factory.py`,
`ultralytics_backend.py`, `rfdetr_backend.py`.

---

## 2. Multi-Object Tracking — ByteTrack

**What it does.** Assigns a stable integer `track_id` to each vehicle
across consecutive frames so we can answer "did *this* vehicle cross
the stop bar?" instead of "is there *a* vehicle near the stop bar?"

**How it works.** ByteTrack (`supervision.ByteTrack`) is a two-pass
data association tracker:

1. **High-score pass** — match high-confidence detections to existing
   tracks by IoU + Kalman-predicted location.
2. **Low-score recovery pass** — instead of throwing low-confidence
   detections away (the BYTE in ByteTrack stands for "every detection
   byte counts"), match them to *unmatched* tracks. This is what makes
   it robust under partial occlusion.

Unmatched tracks are kept alive in a `lost_track_buffer` (30 frames
≈ 3 s at 10 fps) so a vehicle briefly hidden behind a bus doesn't get
a new ID when it reappears. Wrapper params: `frame_rate=10`,
`minimum_matching_threshold=0.8`, `minimum_consecutive_frames=1`.

The same tracker is shared across detector backends so the
YOLO-vs-RF-DETR comparison is detector-vs-detector, not
detector-plus-tracker-vs-detector-plus-tracker.

**Source.** `phase3-fullstack/src/traffic_intel_detector/tracking.py`.

---

## 3. PCE-Aware Counting (HCM 6th edition)

**What it does.** Counts vehicles in a way that reflects their
contribution to congestion. A bus takes more space and accelerates
slower than a car, so it should "count more" toward queue pressure.

**How it works.** Each class gets a Passenger Car Equivalent
multiplier from the HCM 6th edition:

| Class | PCE |
|---|---|
| car | 1.0 |
| motorcycle | 0.4 |
| bicycle | 0.4 |
| bus | 2.0 |
| truck | 1.5 |

Per-approach totals are tracked in two parallel ledgers — raw
(`in_zone`, `crossings_total`) and PCE-weighted (`in_zone_pce`,
`crossings_pce_total`) — plus a `mix` histogram (`{car: 12, bus: 1, …}`).

**Why both.** Raw counts are still useful for sanity-checking and for
endpoints that don't care about congestion. PCE is what gets fed into
Webster's flow ratios.

**NULL guard.** Old DB rows have `in_zone_pce` and
`crossings_pce_in_bin` as NULL. The fusion layer falls back to the
raw count when PCE is missing so historical replays still work
(`fusion.py`).

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/counters.py`.

---

## 4. Per-Lane Subdivision — Fréchet + DBSCAN

**What it does.** Discovers the lanes on each approach automatically
from the trajectories ByteTrack gives us. No need to hand-paint
lane polygons in advance.

**How it works.**

1. **Collect** — for every track, store the centroid trail.
2. **Filter** — drop near-stationary tracks (`min_displacement_px=120`).
   Without this, the queue at the stop bar dominates clustering and
   you end up with one giant "lane" centred on the queue.
3. **Resample** — arc-length resample each track to 32 evenly-spaced
   points so trajectories of different lengths are comparable.
4. **Distance matrix** — compute the **discrete Fréchet distance**
   between every pair of trajectories. Fréchet is the
   "dog-walker distance": the minimum leash length needed for a
   person and dog to walk along their respective curves. It captures
   *shape* similarity, not just endpoint distance, which is why it
   beats Euclidean for path comparison.
5. **Cluster** — run **DBSCAN** with `eps=80px`, `min_samples=5`,
   `metric="precomputed"` on that distance matrix. DBSCAN finds
   density-connected groups without needing to know K up-front, and
   its noise label naturally handles outlier paths (illegal U-turns,
   pedestrians).
6. **Centerline** — for each cluster, take a weighted blend
   (0.7 × longest member + 0.3 × bin-mean) as the medial path.
   Inflate ±30 px perpendicular to the local tangent → a
   ~60 px-wide lane polygon.
7. **Lane type** — compare entry vs exit direction (first vs last 25%
   of the track). Turn angle > 25° → "left" or "right"; otherwise
   "through".

**Why this combination.** Fréchet captures shape (so a car drifting
lanes mid-block doesn't merge two clusters), DBSCAN handles
unknown-K and noise, and the displacement filter removes the queue
bias that breaks naive clustering. O(n²) Fréchet is the cost — we
cap at 60 tracks per approach to keep it under 3.5k pairs.

The induced polygons are persisted; the operator can hand-edit them
in `/lanes` (canvas polygon editor: click-add, drag-move,
right-click-delete).

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/lanes.py`.

---

## 5. Camera-Motion Homography — ORB + RANSAC

**What it does.** When the operator's PTZ camera drifts (wind, slow
pan, focus jitter), saved zone and lane polygons would normally
desync from the road. This keeps them stuck to the asphalt.

**How it works.** Every 2 frames:

1. Extract 1200 **ORB** keypoints + binary descriptors from the
   current frame.
2. Brute-force-match to descriptors from a stored reference frame.
3. Fit a 3×3 **homography** matrix `H` via **RANSAC** — random
   sampling rejects outlier matches (moving vehicles, shadows) so
   only static road features drive the estimate.
4. Smooth the new H against the previous (`smoothing=0.4` blend) to
   damp jitter.
5. Reproject saved polygons through `H` so the lane outline tracks
   the road as the image moves.

**Why ORB + RANSAC.** ORB is rotation-invariant, license-friendly,
and ~100× cheaper than SIFT. RANSAC is the standard answer for
"my data has 30 % outliers and I need a model fit." Together they
give us a ~3–5 ms-per-frame correction with no ML cost.

**Failure modes.** Featureless or low-light scenes (blank asphalt at
night) give too few inlier matches; we hold the last good H rather
than warping to garbage. Large pans (>~5°) can push polygons
off-screen — the renderer falls back to the static (un-warped) copy.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/tracker.py`
(ports `CameraTracker` from phase 2).

---

## 6. LightGBM 15-min Demand Forecast

**What it does.** Predicts vehicles-per-15-min for each approach at
four horizons: now, +15, +30, +60 min.

**How it works.** Four independent **gradient-boosted decision tree**
regressors (LightGBM, MAE objective, 300 rounds, early-stop=30).
Each takes the same 12-feature vector:

| Feature | What it encodes |
|---|---|
| `lag_1`, `lag_2`, `lag_4` | counts at t−15min, t−30min, t−1h |
| `lag_96`, `lag_672` | counts at t−1d, t−7d (same time yesterday / last week) |
| `hour_sin`, `hour_cos` | hour of day, encoded cyclically so 23:45 is close to 00:15 |
| `dow_sin`, `dow_cos` | day of week, same trick |
| `is_weekend` | binary |
| `green_active_frac` | fraction of the bin where this approach's main phase was green |
| `detector_code` | LightGBM-native categorical (no one-hot blowup) |

**Why these features.** Lags carry recent-trend + same-time-yesterday
+ same-time-last-week (capturing daily and weekly cycles).
Sin/cos cyclicality avoids the
"midnight ↔ noon are 12h apart, but `hour=0` and `hour=23` are 23
apart in a tree split" problem. Green fraction lets the model
account for "this approach was held red so its count looks low."

**Performance.** Validation MAE on the held-out 20% is **6.1–6.4 veh
per 15-min bin per detector**, vs **12–42** for a persistence
baseline (`y_t = lag_1`). That's the strawman the model has to beat —
and does, by 2–7×.

**Why LightGBM.** Tabular structured features → boosted trees beat
deep nets at this size, with sub-second training and millisecond
inference. No GPU needed.

**Source.** `phase3-fullstack/src/forecast_ml/{features.py, train.py}`.
Predictions are persisted to the `forecasts` table for forecast-vs-
actual scoring.

---

## 7. Google-Typical-Day Congestion Prior

**What it does.** Provides a "what does this corridor *normally* look
like at 2:30 PM on a Tuesday?" baseline so the LLM and the dashboard
can compare *now vs typical*.

**How it works.** A read-only NDJSON snapshot scraped from the Google
Maps directions API on a representative weekday. 192 rows = 4
corridors (N, S, E, W) × 48 half-hour bins. Each row holds:

```json
{ "corridor": "E", "local_hour": 14.0,
  "congestion_ratio": 1.34, "congestion_label": "moderate",
  "duration_s": 245, "static_duration_s": 183,
  "speed_kmh": 18.2, "static_speed_kmh": 24.0 }
```

`congestion_ratio` is the live-traffic duration divided by the
free-flow duration — > 1 means slower than free-flow.

`tools/build_typical_day_json.py` flattens this NDJSON into a
corridor-keyed JSON consumed by the new `get_typical_day_gmaps`
MCP tool.

**Role in fusion.** The fusion layer uses the gmaps ratio as an
anchor and adds a bounded live multiplier:

```
live_multiplier = min(0.5, live_pressure / 25.0)
final_pressure  = gmaps_intensity × (1 + live_multiplier)
```

So gmaps is the floor; live tracker counts can push it up by at
most 50%. This prevents short-lived noise spikes from flipping the
congestion label.

**Important caveat.** The ratio→veh heuristic is an approximation,
not a per-site calibration. Treat the prior as a *reference curve*,
not ground truth.

**Source.** `data/research/gmaps/typical_2026-04-26.ndjson`,
`tools/build_typical_day_json.py`.

---

## 8. Webster 1958 + HCM Ch. 18 Signal-Timing Advisor

**What it does.** Given current per-approach demand and the
intersection's lost-time / saturation parameters, recommend an
optimal signal cycle length and per-phase green split.

**How it works.**

**Step 1 — flow ratios.** For each approach `i`:

```
y_i = arrival_rate_i / (saturation × lane_count_i)
```

Defaults: `saturation = 30 veh/min/lane` (≈ HCM's 1800 veh/h/lane),
`lane_count` per approach from the zone config (no longer
hard-coded to 2). `y_i` is clamped to [0.02, 0.95] to keep the
formula well-defined.

**Step 2 — Webster's optimal cycle (1958).**

```
Y    = max y over phases (the "critical lane group")
L    = total lost time = num_phases × (yellow + all_red)
       = 3 × (3 + 2) = 15 s for the 3-phase plan (NS → E → W)
C_opt = (1.5 L + 5) / (1 − Y)
```

Capped at 180 s when `Y ≥ 0.95` (formula blows up at saturation).

**Step 3 — green splits.** Effective green per cycle is `g_eff = C − L`,
distributed in proportion to flow ratio:

```
g_i = (y_i / Y) × g_eff,   clamped to [10s, 90s]
```

**Step 4 — uniform delay (Webster).**

```
r = 1 − g/C          (red fraction)
x = min(0.98, y·C/g) (degree of saturation)
d = 0.5 · C · r² / (1 − (g/C)·x)
```

This is the *uniform* term only — incremental and oversaturation
delay terms are not modelled, which underestimates delay above
Y ≈ 0.9. The near-saturation guard below mitigates this.

**Queue-as-rate fallback.** When an approach is on RED in the
current bin, its `demand_per_min` reads 0, which would tell Webster
"this approach needs no green." The fix:

```
arrival_rate = max(demand_per_min, queue × 60 / cycle_seconds)
```

i.e. each queued vehicle counts as one arrival per cycle. Without
this, the model recommends impossibly short cycles for held-red
approaches.

**Near-saturation guard.** If `Y ≥ 0.85` and the computed plan's
delay is *worse* than the field plan, return the field plan
unchanged (`improvement = 0%`). This prevents the dashboard from
ever recommending a provably-worse plan — historically caused a
"−76.9% delay reduction" UI bug at saturation.

**Status.** Advisory only. No control commands are ever sent — see
the isolation gate in `scripts/assert_no_outbound_writes.sh`.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/fusion.py`
(L271–468).

---

## 9. Video-Anchored 3-Phase Signal Simulator

**What it does.** The source RTSP stream is an MP4 in a loop. The
simulator generates synthetic phase-change events (NS → E → W) that
*stay locked to the video timeline*, so when the operator sees E
flowing on screen, `/api/signal/current` says E is green.

**How it works.**

1. `run_rtsp.sh` writes its wall-clock start time atomically to
   `data/ffmpeg_start.txt`.
2. The simulator reads that file (with retry/backoff if it isn't
   written yet).
3. Every tick it computes:

   ```
   video_ts        = (now − ffmpeg_start) mod video_duration
   offset_in_cycle = (video_ts − anchor.video_ts_seconds) mod cycle_3phase
   ```

   The `anchor` is the known fact "at video_ts = 23 s, E goes GREEN."

4. It rotates the (NS, E, W) sequence so the anchor entry is first,
   then walks `offset_in_cycle` forward to find the current
   (phase_num, phase_name, signal_state, duration).

5. Emits a signal event on every state transition, so the bus and
   the WebSocket fanout see the same event stream a real controller
   would publish.

**Why.** Without anchoring, signal labels and the visible video
drift apart over the day. The dashboard would say "NS GREEN" while
the footage shows E flowing, which destroys operator trust.

**Restart hook.** `POST /api/video/restart` kills the ffmpeg PID and
re-anchors the start file, so a fresh dashboard load shows a clean
cycle from frame 0.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/signal_sim.py`.

---

## 10. Fusion Layer

**What it does.** Combines the per-frame tracker output with PCE
weights and the Google-typical-day prior into one state dict per
approach, keyed by approach name (N/S/E/W). This is the input to
both the dashboard and Webster.

**How it works.** For each approach:

```
demand_per_min     = crossings × 60 / bin_seconds
pce_demand_per_min = crossings_pce × 60 / bin_seconds
gmaps_ratio        = gmaps.congestion_ratio  (or 1.0 if missing)
penalty            = max(0, gmaps_ratio − 1.0) × 2.0
pressure           = pce_demand_per_min + 0.5 × in_zone_pce × (1 + penalty)
label              = classify_pressure(pressure)
                     # one of: free | light | moderate | heavy | jam
```

Output dict carries `in_zone`, `crossings_in_bin`, `in_zone_pce`,
`mix`, `demand_per_min`, `pce_demand_per_min`, `queue`,
`gmaps_congestion_ratio`, `gmaps_label`, `gmaps_speed_kmh`,
`pressure`, `label`.

**Why this shape.** Webster wants flow ratios, the dashboard wants
human-readable labels, the LLM wants both. One dict keeps everyone
honest about which numbers came from where.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/fusion.py`.

---

## 11. Incident Detection

**What it does.** Detects four classes of operational anomalies and
emits them as `incident` events.

| Type | Trigger | Severity |
|---|---|---|
| Wrong-way | direction-of-travel disagrees with approach's expected vector | critical |
| Stalled | centroid displacement < 3 px for ≥ 20 s while in-zone | warning |
| Abnormal stop | stopped during *own approach's* GREEN phase ≥ 8 s | warning |
| Queue spillback | queue ≥ 20 cars sustained ≥ 10 s | critical |

**Wrong-way logic.**

1. Keep the last 15 frames of (x, y) per track.
2. Path vector `(dx, dy) = pos[-1] − pos[0]`.
3. Speed = `hypot(dx,dy) / dt`. Skip if < 8 px/s (false positives
   from idling).
4. Normalise to unit vector `v̂`.
5. Compute `dot = v̂ · expected_direction` for the approach
   (e.g. `(-1, 0)` for west-bound).
6. Fire if `dot ≤ −0.30` — i.e. the vehicle is moving notably
   against the expected flow.
7. Fire-once per `track_id` so a single u-turner doesn't emit 30
   events.

**Why a dot product.** It captures angular agreement directly:
+1 = perfect alignment, 0 = perpendicular, −1 = exactly reversed.
A threshold of −0.30 corresponds to roughly > 100° off from the
expected heading, which is the right "this is genuinely going the
wrong way" line.

**Spillback logic.** Streak detection. While the queue is ≥ 20 we
track when the streak started; once it crosses 10 s of continuous
high queue we fire one incident, then mute for 30 s so the same
streak doesn't re-fire.

**Drift alerts** (see §12) use the same emit path:
`EventEngine.emit_drift_alert()` → `incidents` table → bus topic
`incidents.detected`.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/events.py`.

---

## 12. Drift Monitor

**What it does.** Polls four health signals continuously and emits
`drift_alert` incidents when something starts going wrong silently.

| Check | Threshold | Why it matters |
|---|---|---|
| Detector FPS | < 2.0 fps | Tracker is starving — RTSP stalled or model thrashing |
| Signal log freshness | mtime > 300 s ago | The signal sim or controller stream stopped |
| Model age | mtime > 30 days | Time to retrain the LightGBM forecaster |
| Class-mix KL | > 0.5 | Distribution of detected classes drifted from baseline |

**Class-mix drift — symmetric KL.**

```
KL(p ‖ q) = Σ p_k · log(p_k / q_k)
KL_sym    = 0.5 · ( KL(p ‖ q) + KL(q ‖ p) )
```

p = baseline class histogram, q = recent-window histogram. Symmetric
KL is used because plain KL is asymmetric (KL(p‖q) ≠ KL(q‖p)) and
either direction alone misses some drifts. ε = 1e-6 prevents log(0)
on classes that disappeared.

A KL of 0.5 is a roughly noticeable reweighting — e.g. baseline 90%
cars / 10% trucks vs recent 60% cars / 40% trucks would clear
threshold and fire.

**Rate limiting.** Each check has its own `AlertGate` with a 300 s
cooldown so a stuck-bad signal doesn't fire on every tick.

**Source.** `phase3-fullstack/src/traffic_intel_phase3/observability/drift.py`.

---

## 13. LLM Advisor + 8 MCP Tools

**What it does.** The `/chat` page (and the floating drawer on the
dashboard) lets an operator ask natural-language questions —
"is anything unusual happening on E right now?", "what does Webster
recommend for the next 30 minutes?". The LLM answers by calling
one or more of these eight tools:

| # | Tool | Purpose |
|---|---|---|
| 1 | `get_current_state` | per-approach counts, queue, gmaps congestion, current phase |
| 2 | `get_forecast` | LightGBM prediction at horizon ∈ {0, 15, 30, 60} min |
| 3 | `get_history` | historical counts in [start_iso, end_iso] grouped by N min |
| 4 | `get_recommendation` | Webster plan + delay-reduction %, near-saturation flag |
| 5 | `list_incidents` | recent incidents, optionally filtered by type |
| 6 | `get_signal_plan` | the field plan (greens, yellows, all-red, anchor) |
| 7 | `get_typical_day_gmaps` | gmaps congestion grid (4 corridors × 48 half-hour bins) |
| 8 | `query_sqlite` | SELECT-only allowlisted SQL, max 1000 rows, 5 s timeout |

**Why MCP.** The same 8 tools are exposed in two places:

- *In-process* — the FastAPI server registers them and the `/chat`
  endpoint dispatches; live providers (tracker, forecast, Webster)
  can be called directly.
- *Stdio MCP server* — `python -m traffic_intel_mcp` exposes the
  identical tool surface to external clients (Claude Desktop, Cursor,
  agents). Drop `.mcp.json.example` into the client's config and the
  same operator queries work from outside the dashboard.

**The new tool — `get_typical_day_gmaps`.** Lets the LLM compare
"now vs typical" cleanly. With no args it returns the whole grid;
with `corridor` and `hour` it returns just that cell. Hour is
half-hour-snapped (14.2 → 14.0, 14.3 → 14.5).

**Safety.** `query_sqlite` is a SELECT-only escape hatch. The
allowlist is `detector_counts`, `incidents`, `forecasts`,
`recommendations`, `signal_events`, `system_metrics`, `audit_log`.
Anything else (DELETE, UPDATE, attaching other DBs, `pragma`) raises
a validation error before it ever reaches sqlite.

**Source.**
`phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/llm/tools.py`,
`phase3-fullstack/src/traffic_intel_mcp/`,
`phase3-fullstack/docs/MCP_TOOLS.md`.

---

## 14. Auth & RBAC

**What it does.** Login, signed sessions, and role-gated endpoints.

**How it works.**

- **Password hashing** — bcrypt with `gensalt()` defaults. Stored
  hash format `$2b$…` in the SQLite `users` table.
- **JWT issue** — on successful `bcrypt.checkpw`, sign a payload
  `{sub, role, iss, iat, exp}` with HS256 using
  `TRAFFIC_INTEL_JWT_SECRET`. TTL = 30 min
  (`TRAFFIC_INTEL_JWT_TTL_MIN`).
- **JWT verify** — every protected endpoint reads `Authorization:
  Bearer <token>`, calls `JwtService.verify`, and rejects on
  expired/invalid/wrong-signature.
- **Roles** — `viewer`, `operator`, `admin`, in increasing power.
  Endpoints declare a minimum role; the JWT's `role` claim is
  checked against it.

| Role | Can access |
|---|---|
| viewer | live MJPEG, counts, fusion, forecast, recommendation (read-only) |
| operator | viewer + signal-log writes, detector-log ingest, lane editor |
| admin | operator + audit log, user management |

**Production note.** If `TRAFFIC_INTEL_JWT_SECRET` is unset, the
service falls back to an ephemeral random secret per process, so
tokens are invalidated on restart. Fine for dev — pin a secret in
prod.

**Source.**
`phase3-fullstack/src/traffic_intel_phase3/auth/{jwt_service.py, users.py}`.

---

## 15. Pluggable Event Mesh

**What it does.** Same `publish` API, three swappable backends:
asyncio (in-process), Kafka (durable), RabbitMQ (rich routing).

**Protocol.**

```python
class MessageBus(Protocol):
    async def start() / stop() / publish(msg)
    def publish_threadsafe(msg)
    async def subscribe(topic, handler)
```

`get_bus()` reads `TRAFFIC_INTEL_BUS` and returns a process-wide
singleton. Switching brokers requires *no code change*.

**Why this matters.** Producers (the tracker thread, signal sim,
event engine) call `publish_threadsafe(BusMessage(...))` and don't
care whether the message ends up in an asyncio queue, a Kafka
partition, or a RabbitMQ topic exchange.

**Canonical topics.**

```
detector.counts          signal.events             incidents.detected
forecasts.generated      recommendations.created
ingest.errors            audit.events
```

Same strings on every backend, so a Kafka consumer subscribing to
`detector.counts` sees the same JSON payload an asyncio subscriber
would.

**Subscriber isolation.** Each subscriber runs in its own task; if
one handler raises, the bus logs and continues. One bad consumer
doesn't take down the whole event stream.

**Backend tradeoffs.**

| Backend | Persistence | Use case |
|---|---|---|
| asyncio | none (in-memory) | single-box dev, demos |
| Kafka | broker log, consumer groups | multi-host, replay-needed |
| RabbitMQ | durable queues, topic exchange | multi-process fan-out |

**Source.** `phase3-fullstack/src/traffic_intel_phase3/bus/`.

---

## How the Pieces Fit Together

```
RTSP stream  ─►  Detector (YOLO|RF-DETR)  ─►  ByteTrack  ─►  Counter (PCE)
                                                                  │
                                                                  ├──► Lane induction (Fréchet+DBSCAN)
                                                                  │
                                                                  ├──► Event engine (incidents)
                                                                  │
                                                                  └──► Fusion ◄── gmaps typical-day
                                                                          │
                                                                          ├──► LightGBM forecast
                                                                          │
                                                                          └──► Webster + HCM advisor
                                                                                  │
            Camera-motion homography ──► warps zone polygons frame-by-frame       │
                                                                                  ▼
                  Signal sim (video-anchored)  ──►  Event mesh (asyncio | Kafka | RabbitMQ)
                                                                                  │
                                                                                  ▼
                                                                  Dashboard (JWT + 3 roles)
                                                                                  │
                                                                                  ▼
                                                                       LLM advisor (8 MCP tools)
                                                                                  │
                                                                                  └──► Drift monitor (4 checks)
```

Every block is independently testable; the bus + the fusion dict are
the two seams that keep them decoupled.

---

## Further Reading

- [`ALGORITHMS.md`](ALGORITHMS.md) — formal reference, file:line cites for every threshold.
- [`MCP_TOOLS.md`](MCP_TOOLS.md) — full MCP tool schemas and example calls.
- [`DASHBOARD_V2.md`](DASHBOARD_V2.md) — operator console architecture.
- [`security_and_isolation.md`](security_and_isolation.md) — read-only-toward-infrastructure model.
