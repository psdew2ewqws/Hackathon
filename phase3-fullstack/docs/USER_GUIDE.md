# Phase 3 — Operator User Guide

Plain-English walkthrough of every page in the Wadi Saqra dashboard.
Written for a traffic control room operator, not a developer. Each page
section covers: what it shows, what decisions you'd make from it, and the
caveats you should know.

## Logging in

Open the dashboard in your browser (default `http://localhost:8000/app`).
You will be asked for a username and password. Three roles are seeded on
first run:

- **viewer** — read-only access to Live, Signal, Forecast, Incidents.
- **operator** — viewer + can mark incidents as resolved/dismissed.
- **admin** — operator + Audit Log + Signal Timing edits + user
  management.

Tokens expire after 30 minutes. You will be bounced back to the login
screen when your session lapses; there is no silent refresh.

## Live

Purpose: the "what is happening right now" view.

What it shows:

- An annotated MJPEG frame: coloured approach zones, vehicle bounding
  boxes with track IDs, and the four stop-lines.
- Per-approach counters — `in zone` (how many vehicles currently sit in
  the approach polygon), `cross total` (since stack start), `cross bin`
  (in the last 15 s), and the fused congestion class (free / light /
  moderate / heavy / jam).
- The gmaps "typical day" label for the same corridor and hour.

What to do with it:

- Compare "cross bin" against the gmaps label. When the live class is
  two steps worse than the gmaps label for more than one bin, something
  unusual is happening on that approach — cross-check with the Incidents
  page.
- Watch the "in zone" counter for a sustained spike. That's queue
  build-up; it's the input that drives the queue_spillback detector.

Caveats:

- The MJPEG feed has a 100 ms buffer in the server. If the RTSP publisher
  dies the feed freezes but `/api/counts` will still report `running:
  false` — use the System page to confirm.
- Counts are pixel-space, not real-world. An 80% in-zone frame doesn't
  literally mean 80 cars; it means 80 centroids sit inside the polygon.

## Signal

Purpose: verify the field signal plan vs the simulator and Webster's
recommendation.

What it shows:

- Two timing rows — "Current (field)" and "Recommended".
- Webster detail: total flow ratio Y, per-phase y_NS and y_EW, estimated
  delay reduction in percent.
- A live lamp indicator for NS and EW (GREEN/YELLOW/RED) with a progress
  bar showing how far through the current phase we are.
- A scrolling log of the last 40 phase transitions.

What to do with it:

- When the "delay reduction" badge reads > 20 %, consider raising a
  change request to the traffic authority. Keep in mind the estimate is
  uniform-delay only (Webster term one), which ignores queue overflow.
- If the delay reduction is small (< 5 %), the current plan is already
  close to optimal for this hour — no action.

Caveats:

- The simulator runs with a 80 s cycle (35 NS + 35 EW + 2×3 yellow +
  2×2 all-red). The "current" comparison always uses exactly those
  numbers unless you edit `configs/wadi_saqra.json → signal.current_plan`.
- Delay units are seconds per vehicle per approach, summed across both
  phases. Don't compare across sites without normalising by demand.

## Forecast

Purpose: see what traffic looks like in the next N hours and what the
signal plan should be at each tick.

What it shows:

- 24-hour half-hour heatmap (4 approaches × 48 columns) coloured by
  predicted class.
- Drag the slider to pick an hour; the row below fills in the predicted
  per-approach pressure, gmaps ratio, expected speed, and the Webster
  cycle/green split for that exact moment.
- A "next 12 hours" rolling forecast table with peak class, peak hour,
  max pressure and the hours-heavy+ count per approach.

What to do with it:

- Use the heatmap to pre-stage the signal plan for the next shift.
  Approaches that show 3+ hours of `heavy` (orange) are candidates for a
  longer green in the morning plan; `jam` (red) spans warrant a temporary
  plan swap.
- If an approach flips from `light` to `heavy` within 30 minutes and the
  pressure delta exceeds 5 units, that's an early-warning for a peak —
  lean on the operator response plan.

Caveats:

- The forecast anchors on the gmaps "typical day" row. It does not know
  about today's weather, a public holiday, or a reported accident. Treat
  it as a prior, not a guarantee.
- The live multiplier is capped at +50 %, so the tracker can boost but
  not zero out the gmaps prediction.

## Incidents

Purpose: triage every event the §6.6 detectors emit.

What it shows: a reverse-chronological feed of events with columns for
time, severity, event type, approach and a short payload snippet
(`from=light`, `queue_count=24`, `track_id=99`, etc.). Six event types:
congestion_class_change, queue_spillback, abnormal_stopping,
stalled_vehicle, wrong_way, and composite `incident`.

What to do with it:

- **wrong_way critical** — dispatch immediately; this is a safety event.
- **queue_spillback critical** — check Live for the queue, then decide
  whether to extend the green on the offending approach for one cycle.
- **stalled_vehicle warning** — radio patrol; it's usually a breakdown,
  not a crash.
- **abnormal_stopping warning** — if it recurs on the same approach,
  check for a signal-to-loop misalignment (driver stops on green).

Caveats:

- The wrong-way detector is sensitive to camera jitter — see
  `limitations.md`. Verify against the Live feed before dispatching.
- Severity comes from a hard-coded rule table. Your judgment trumps the
  automated label.

## System

Purpose: a health dashboard for the stack itself.

What it shows: tracker running/FPS/last error, signal simulator status,
SQLite row counts per major table, the storage sink queue depth, and
(when populated) system_metrics entries per module.

What to do with it:

- `tracker.fps` should sit near the configured 10 FPS. A drop to < 5
  means CPU starvation or a corrupt RTSP source — restart `run_rtsp.sh`.
- `sink_queue` should stay at or near zero. A climbing queue means
  SQLite is under contention; check disk IO.

Caveats:

- System metrics auto-populate only when a module periodically pushes a
  `system_metric` record. Not all modules do yet.

## Audit

Purpose: compliance and forensics — who did what and when.

What it shows: the most recent 100 rows from `audit_log`. Each row has
timestamp, username, role, action (e.g. `login`, `login_failed`,
`emit_demo_events`), resource path, JSON payload and IP address.

What to do with it:

- Review weekly. Three consecutive `login_failed` entries for the same
  username warrant a password rotation for that account.
- After any "unusual" operator action, the audit log is your evidence
  trail.

Caveats:

- Admin-only. Viewer and operator roles will see a 403.
- IP is whatever `request.client.host` reports, which behind a reverse
  proxy will be the proxy's address unless you preserve the
  `X-Forwarded-For` chain.

## History

Purpose: look back at a past window of counts and events.

What it shows: date + time range picker; per-approach count chart over
the range; overlay of incidents that fired in the same window.

What to do with it: use it to answer "what did morning rush look like
last Tuesday?" or "when did we first see queue_spillback on the east
approach?"

Caveats:

- SQLite is single-writer. On a very long range (many days) the query
  can take a few hundred ms; the UI will show a spinner.

## Signal Timing

Purpose: review the offline 24 h signal log generated by
`scripts/build_signal_timing_log.py` and compare against live.

What it shows: day-long timeline of GREEN/YELLOW/RED bars per phase, with
cycle boundaries highlighted.

What to do with it: sanity-check the field plan against the simulator.
If the recorded pattern drifts from the configured 80 s cycle by more
than a few seconds per hour, the field controller is not on the plan
you think it is.

Caveats:

- Admin-only in the current build because the page also exposes raw JSON
  export that could be misused for scraping.
- The "offline" log is generated from the `CurrentPlan`; it does not yet
  reflect detector-actuated behaviour.
