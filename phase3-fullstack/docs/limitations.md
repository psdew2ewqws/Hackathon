# Phase 3 — Known Limitations

Honest inventory of the places where the stack is narrower than a
production traffic-intelligence product. Each item lists the constraint,
why it's there, and the concrete next step.

## 1. Google Maps data is "typical day" only

What: `data/research/gmaps/typical_2026-04-26.ndjson` is a single
composite day that the Routes API describes as representative of an average
weekday. No holiday, event, weather or calendar-aware variants.

Why: the gmaps Routes API bills per request and we budgeted one typical-day
sweep for the hackathon window.

Next: schedule a recurring ingest (hourly, 4 corridors) for a multi-week
baseline; keep typical-day as a fallback when live scraping is rate-limited
or blocked.

## 2. LightGBM model has no holiday feature

What: the 12-feature vector is 5 lags + 4 sin/cos calendar terms +
is_weekend + green_active_frac + detector_code. No public-holiday flag,
no weather, no school-term indicator.

Why: we didn't have a Jordanian holiday calendar assembled in time, and
green_active_frac is already the strongest causal signal.

Next: join a public holiday table (Jordan / MENA); retrain and compare
MAE on the 20% validation split. Holidays will most likely help the
y_60min target, which currently has the highest baseline gap.

## 3. Wrong-way detector requires a stabilised camera

What: `wrong_way` in `events.py` compares the unit velocity vector of a
track against the zone's `direction_of_travel`. Any camera jitter larger
than a few pixels inflates the magnitude term and lowers the dot product
toward the wrong-way threshold.

Why: the Wadi Saqra capture is hand-held phone footage. Phase 2 added
video stabilisation (`phase2-feasibility/stabilize`) but the live stack
does not re-stabilise in real time.

Next: either (a) require rigidly mounted cameras, (b) wire the Phase 2
stabiliser into the tracker ingest, or (c) add an outlier filter that
rejects tracks whose velocity flips sign frame-to-frame (jitter
signature).

## 4. Auth passwords live in the SQLite file

What: bcrypt hashes are stored in `users.pw_hash`; there is no secret
vault, no hardware-backed KMS, no key rotation UX. The JWT signing secret
is an env var that may end up in the process table.

Why: a fully-managed identity layer was out of scope for the hackathon.

Next: move user passwords into an external vault (HashiCorp Vault / AWS
Secrets Manager / Kubernetes Secret with CSI), rotate the JWT secret via
a scheduled reissue endpoint, and add mandatory password rotation for the
three default accounts on first login.

## 5. RTSP "live" stream is a file loop

What: `scripts/run_rtsp.sh` does `ffmpeg -re -stream_loop -1` against the
archived mp4. There is no camera reconnect behaviour proven against a real
field failure mode (RTSP authentication challenge, 401 loops, NAT drops,
degraded-bandwidth MPEG corruption).

Why: we don't have a live camera at Wadi Saqra.

Next: point the tracker at a staged "flaky" publisher (mediamtx with
scripted disconnects) and log reconnect latency, dropped-frame counts and
YOLO re-initialisation overhead. Add a supervisor loop in
`scripts/run_rtsp.sh` so the ffmpeg process is restarted on exit.

## 6. Single-day capture

What: the entire live tracker pipeline has only been exercised against one
video (5 min 14 s) captured on 2026-04-22 at 09:57 local. Detector tuning
(conf, imgsz, ByteTrack params) reflects that capture's lighting, weather
and angle.

Why: single visit to the site.

Next: re-capture at morning peak, evening peak, after dark and in rain.
Re-tune thresholds only if the stabilised metric (precision on the
calibration pack) regresses.

## 7. Zones were tuned by eye

What: the 4 approach polygons and stop-lines in
`configs/wadi_saqra_zones.json` were drawn on a static frame by a human.
No homography, no real-world units, no automated calibration.

Why: the hackathon scope allowed pixel-space counting; world-space
projection is Phase 4 territory.

Next: either use the Phase 2 `homography.py` module to produce a pixel
→ ground-plane matrix (given 4 known control points), or switch to a
learned zone-proposal step that uses lane-marking segmentation on the first
frame.

## 8. Event engine severity is rule-based, not learned

What: `queue_spillback` severity is hard-coded to `critical`,
`congestion_class_change` severity comes from a lookup on the target
class. No operator feedback signal; no counterfactual evaluation.

Why: we had no labelled incident dataset.

Next: log operator actions on the Incidents page (resolve / dismiss /
escalate) and use that as supervised feedback to train a severity
calibrator — the schema already has `status`, `resolved_at`, `resolved_by`.

## 9. No retry or dead-letter on the storage sink

What: `StorageSink._flush()` logs exceptions and drops the batch. If
SQLite is locked or the disk fills, records are lost with no on-disk
spillover.

Why: the NDJSON fallback files (`data/{counts,signal_log,events}.ndjson`)
are the effective safety net today.

Next: add a bounded on-disk queue (diskcache / a dedicated ndjson
"wal_pending" file) that the sink drains into SQLite, so nothing is lost
on transient DB outages.
