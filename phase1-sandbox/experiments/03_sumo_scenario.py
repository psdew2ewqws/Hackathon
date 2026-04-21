"""Experiment 03 — SUMO microscopic scenario: coupled counts + signals + tracks.

Stage 3 of the sim-to-real pipeline (see docs/research_sim_to_real.md).

One simulation run emits three *internally-consistent* outputs:
  1. data/research/sumo/counts_<date>.parquet    — matches synth.detector_counts SCHEMA
  2. data/research/sumo/signal_<date>.ndjson     — matches synth.signal_logs format
  3. data/research/sumo/trajectories_<date>.parquet — per-vehicle (t, x, y, θ, approach)

Fixes the "no shared scenario" gap: a count spike at DET-N-2-1 now corresponds
to specific vehicles whose trajectories can be projected onto the Wadi Saqra
background plate by 04_compose_synthetic_video.py.

The default path drives real SUMO via TraCI against the network at
``phase1-sandbox/experiments/sumo/site1/synth/`` (built by build_site1_*.py).
Pass ``--analytic`` to force the deterministic analytic simulator fallback
(cell-transmission-model style), which is what this script used to be before
SUMO was wired up.

Usage
-----
    python experiments/03_sumo_scenario.py \\
        --profiles phase1-sandbox/configs/profiles.yml \\
        --phase-plan phase1-sandbox/configs/phase_plan.yml \\
        --site-meta phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \\
        --out-dir data/research/sumo \\
        --date 2026-04-20 --seed 42
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

# Reuse the production SCHEMA so any consumer downstream gets byte-compatible
# output.
try:
    from traffic_intel_sandbox.synth.detector_counts import SCHEMA as COUNTS_SCHEMA
    from traffic_intel_sandbox.synth.detector_counts import BINS_PER_DAY
except ImportError:
    COUNTS_SCHEMA = pa.schema([
        pa.field("timestamp",       pa.timestamp("ns", tz="UTC")),
        pa.field("intersection_id", pa.string()),
        pa.field("detector_id",     pa.string()),
        pa.field("approach",        pa.string()),
        pa.field("lane",            pa.int16()),
        pa.field("lane_type",       pa.string()),
        pa.field("vehicle_count",   pa.int32()),
        pa.field("occupancy_pct",   pa.float32()),
        pa.field("quality_flag",    pa.int8()),
    ])
    BINS_PER_DAY = 96


SCENARIO_DIR = Path("phase1-sandbox/experiments/sumo/site1/synth")
DEFAULT_TL_ID = "site1_center"


@dataclass
class DetectorSpec:
    id: str
    approach: str
    lane: int
    lane_type: str
    base_multiplier: float


@dataclass
class PhaseSpec:
    number: int
    name: str
    green_s: float
    yellow_s: float
    all_red_s: float

    @property
    def duration_s(self) -> float:
        return self.green_s + self.yellow_s + self.all_red_s


def _load_detectors(profiles_path: Path) -> tuple[list[DetectorSpec], dict]:
    raw = yaml.safe_load(profiles_path.read_text())
    dets = [DetectorSpec(**d) for d in raw["detectors"]]
    return dets, raw


def _load_phases(phase_plan_path: Path) -> tuple[list[PhaseSpec], float]:
    raw = yaml.safe_load(phase_plan_path.read_text())
    phases = [PhaseSpec(**p) for p in raw["phases"]]
    jitter = float(raw.get("cycle_jitter_s", 0))
    return phases, jitter


# ─── SUMO state-string → NEMA phase lookup ──────────────────────────────────
# Built to mirror build_site1_tllogic.py EXPECTED_ORDER. Kept as lookup rather
# than re-derived so a signal-plan change here causes an explicit mismatch in
# tests rather than silent phase mislabeling.
_STATE_TO_PHASE_KIND: dict[str, tuple[int, str]] = {
    "GGGGrrrrrGGGGrrrrr": (2, "GREEN_ON"),
    "yyyyrrrrryyyyrrrrr": (2, "YELLOW_ON"),
    "rrrrGrrrrrrrrGrrrr": (6, "GREEN_ON"),
    "rrrryrrrrrrrryrrrr": (6, "YELLOW_ON"),
    "rrrrrGGGrrrrrrGGGr": (4, "GREEN_ON"),
    "rrrrryyyrrrrrryyyr": (4, "YELLOW_ON"),
    "rrrrrrrrGrrrrrrrrG": (8, "GREEN_ON"),
    "rrrrrrrryrrrrrrrry": (8, "YELLOW_ON"),
    # All-red is ambiguous w.r.t. NEMA phase; we tag with the *preceding*
    # phase in _traci_driver so it reads as "phase 2 RED_ON" → "phase 6 GREEN_ON"
    # which is the schema the analytic generator already emits.
    "rrrrrrrrrrrrrrrrrr": (None, "RED_ON"),  # pyright: ignore[reportAssignmentType]
}


# ─── Real SUMO path (TraCI) ─────────────────────────────────────────────────
def run_sumo(
    scenario_dir: Path,
    profiles_path: Path,
    site_meta_path: Path,
    out_dir: Path,
    day: date,
    intersection_id: str,
    seed: int,
    duration_s: float,
    traj_sample_frac: float,
) -> dict[str, Path]:
    """Drive a real SUMO simulation for ``duration_s`` seconds (default: full
    day, 86400). Emits the same three output files as run_analytic()."""
    os.environ.setdefault("SUMO_HOME", "/usr/share/sumo")
    try:
        import traci  # type: ignore
    except ImportError as exc:
        raise RuntimeError("traci not installed; run `.venv/bin/pip install "
                           "traci sumolib` or pass --analytic") from exc

    sumocfg = scenario_dir / "sim.sumocfg"
    if not sumocfg.exists():
        raise FileNotFoundError(f"SUMO scenario not found at {sumocfg}. Run "
                                f"build_site1_network.py + tllogic + routes "
                                f"+ detectors first.")

    detectors, _profile_cfg = _load_detectors(profiles_path)
    site_meta = json.loads(site_meta_path.read_text())
    stop_line_by_approach = {sl["approach"]: sl["polyline_px"]
                             for sl in site_meta["stop_lines"]}
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rng = random.Random(seed * 1_000_003 + day.toordinal())

    step_length_s = 1.0
    total_steps = int(duration_s)

    # Per-detector counters: one scalar that accumulates, stamped into 15-min
    # bins at the end.
    det_second_counts = {d.id: np.zeros(total_steps + 1, dtype=np.int32)
                         for d in detectors}
    det_second_occupied = {d.id: np.zeros(total_steps + 1, dtype=bool)
                           for d in detectors}
    # Edge-triggered counting: only count a vehicle the first step it lands on
    # the loop (matches real-world loop semantics). Without this, vehicles
    # queued on the loop inflate counts by one per step they sit there.
    det_last_ids: dict[str, set[str]] = {d.id: set() for d in detectors}

    # Signal transitions
    signal_events: list[dict] = []
    last_state: str | None = None
    last_phase: int | None = None

    # Trajectory sampling — we sample a fraction of the time steps to record
    # *every* active vehicle's pose. A vehicle seen multiple times appears
    # multiple times (useful for compositing).
    trajectory_rows: list[dict] = []

    sumo_cmd = [
        "sumo", "-c", str(sumocfg),
        "--end", str(duration_s),
        "--step-length", str(step_length_s),
        "--no-step-log", "true",
        "--seed", str(seed),
        "--time-to-teleport", "300",
    ]
    print(f"[sumo] launch  {' '.join(sumo_cmd)}", file=sys.stderr)
    traci.start(sumo_cmd)

    try:
        det_ids = [d.id for d in detectors]
        approach_by_edge = {f"in_{a}": a for a in ("N", "S", "E", "W")}

        step = 0
        while step <= total_steps:
            traci.simulationStep()

            # 1. Induction-loop counts (edge-triggered per vehicle crossing)
            for det_id in det_ids:
                current_ids = set(
                    traci.inductionloop.getLastStepVehicleIDs(det_id))
                new_ids = current_ids - det_last_ids[det_id]
                if new_ids:
                    det_second_counts[det_id][step] = len(new_ids)
                if current_ids:
                    det_second_occupied[det_id][step] = True
                det_last_ids[det_id] = current_ids

            # 2. Signal transitions
            state = traci.trafficlight.getRedYellowGreenState(DEFAULT_TL_ID)
            if state != last_state:
                mapping = _STATE_TO_PHASE_KIND.get(state)
                if mapping is not None:
                    ph_num, kind = mapping
                    if kind == "RED_ON" and ph_num is None:
                        ph_num = last_phase  # all-red tagged to preceding phase
                    if ph_num is not None:
                        ts = day_start + timedelta(seconds=step)
                        signal_events.append({
                            "ts": ts, "phase": ph_num, "state": kind,
                        })
                        if kind == "GREEN_ON":
                            last_phase = ph_num
                last_state = state

            # 3. Trajectory sampling
            if rng.random() < traj_sample_frac:
                veh_ids = traci.vehicle.getIDList()
                for vid in veh_ids:
                    x, y = traci.vehicle.getPosition(vid)
                    angle = traci.vehicle.getAngle(vid)
                    # Origin approach = first edge in the vehicle's route
                    # (always an in_* edge by routes.rou.xml construction).
                    # Tagging by origin (not current edge) keeps the compose
                    # replay direction consistent even for vehicles that have
                    # already crossed the intersection.
                    route = traci.vehicle.getRoute(vid)
                    origin_edge = route[0] if route else ""
                    approach = approach_by_edge.get(origin_edge, "?")
                    lane_idx = traci.vehicle.getLaneIndex(vid)
                    speed = traci.vehicle.getSpeed(vid)
                    ts = day_start + timedelta(seconds=step)
                    # stop_line_px_x/y anchor each trajectory sample to its
                    # approach's pixel-space stop-line midpoint. This is the
                    # contract 04_compose_synthetic_video.py expects; we
                    # preserve it alongside SUMO world coords for future use.
                    sl = stop_line_by_approach.get(approach,
                                                   [[960, 540], [960, 540]])
                    sx_px = (sl[0][0] + sl[1][0]) / 2
                    sy_px = (sl[0][1] + sl[1][1]) / 2
                    trajectory_rows.append({
                        "timestamp": ts,
                        "vehicle_id": vid,
                        "approach": approach,
                        "lane": int(lane_idx),
                        "x_m": float(x),
                        "y_m": float(y),
                        "angle_deg": float(angle),
                        "speed_ms": float(speed),
                        "stop_line_px_x": float(sx_px),
                        "stop_line_px_y": float(sy_px),
                    })

            step += 1
    finally:
        traci.close()

    # ── Roll counts into 15-min bins ────────────────────────────────────────
    rows: list[dict] = []
    bin_len_s = int(86400 / BINS_PER_DAY)  # 900 s
    bins_in_sim = min(BINS_PER_DAY, total_steps // bin_len_s)
    bin_ts = [pd.Timestamp(day_start + timedelta(minutes=15 * i))
              for i in range(BINS_PER_DAY)]

    for det in detectors:
        seconds = det_second_counts[det.id][:bins_in_sim * bin_len_s]
        occ_seconds = det_second_occupied[det.id][:bins_in_sim * bin_len_s]
        counts = seconds.reshape(bins_in_sim, bin_len_s).sum(axis=1)
        occupancy = occ_seconds.reshape(bins_in_sim, bin_len_s).mean(axis=1) * 100.0

        # Fill remainder of the day with zero for schema parity. If the sim
        # was less than 24h, we mark short-run bins with quality_flag=2.
        full_counts = np.zeros(BINS_PER_DAY, dtype=np.int32)
        full_occ = np.zeros(BINS_PER_DAY, dtype=np.float32)
        full_counts[:bins_in_sim] = counts
        full_occ[:bins_in_sim] = occupancy.astype(np.float32)

        for i, ts in enumerate(bin_ts):
            quality = 0 if i < bins_in_sim else 2
            rows.append({
                "timestamp": ts,
                "intersection_id": intersection_id,
                "detector_id": det.id,
                "approach": det.approach,
                "lane": int(det.lane),
                "lane_type": det.lane_type,
                "vehicle_count": int(full_counts[i]),
                "occupancy_pct": float(full_occ[i]),
                "quality_flag": int(quality),
            })

    out_dir.mkdir(parents=True, exist_ok=True)
    counts_path = out_dir / f"counts_{day.isoformat()}.parquet"
    df = pd.DataFrame.from_records(rows)
    pq.write_table(pa.Table.from_pandas(df, schema=COUNTS_SCHEMA,
                                        preserve_index=False),
                   counts_path, compression="zstd")

    # ── Write signal ndjson ────────────────────────────────────────────────
    signal_path = out_dir / f"signal_{day.isoformat()}.ndjson"
    with signal_path.open("w") as fh:
        for ev in signal_events:
            ts: datetime = ev["ts"]
            if ts >= day_start + timedelta(days=1):
                break
            fh.write(json.dumps({
                "timestamp": ts.astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                "intersection_id": intersection_id,
                "phase": ev["phase"],
                "state": ev["state"],
            }) + "\n")

    # ── Trajectories parquet ───────────────────────────────────────────────
    traj_path = out_dir / f"trajectories_{day.isoformat()}.parquet"
    if trajectory_rows:
        traj_df = pd.DataFrame.from_records(trajectory_rows)
        pq.write_table(pa.Table.from_pandas(traj_df, preserve_index=False),
                       traj_path, compression="zstd")
    else:
        traj_path.write_bytes(b"")

    print(f"[sumo] {day}  bins={bins_in_sim}/{BINS_PER_DAY}  count rows={len(rows)}  "
          f"signal events={len(signal_events)}  traj rows={len(trajectory_rows)}  "
          f"→ {out_dir}", file=sys.stderr)
    return {"counts": counts_path, "signals": signal_path, "trajectories": traj_path,
            "mode": Path("sumo")}


# ─── Analytic fallback simulator ─────────────────────────────────────────────
# Philosophy: SUMO gives us physics, but if SUMO isn't available we can still
# produce schema-valid *coupled* outputs. We gate the per-minute arrival rate
# of each detector by whether its approach's phase is currently green; vehicles
# accumulate during red and discharge at saturation flow during green. That
# single coupling rule is what makes counts + signals share a scenario.

APPROACH_TO_PHASE = {
    "N": 2, "S": 2,   # N/S through / major arterial
    "E": 4, "W": 4,   # E/W through / minor
}
LEFT_PHASE = {"S": 6, "N": 6, "W": 8, "E": 8}
SATURATION_FLOW_VPH_PER_LANE = 1800  # typical urban saturation
HEADWAY_S = 2.0  # target headway on saturation flow


def _gaussian_peak(t_min: float, center: float, width: float, amp: float) -> float:
    return amp * math.exp(-((t_min - center) ** 2) / (2 * width * width))


def _per_minute_demand(profile_cfg: dict, det: DetectorSpec, is_weekend: bool) -> np.ndarray:
    """Return 1440 per-minute arrival rates (veh/min) for this detector."""
    base = float(profile_cfg["baseline_rate"]) * det.base_multiplier
    day_mult = float(profile_cfg["weekend_multiplier"] if is_weekend else profile_cfg["weekday_multiplier"])
    rates = np.full(1440, base, dtype=np.float32)
    for peak in profile_cfg["peaks"]:
        for t in range(1440):
            rates[t] += _gaussian_peak(t, peak["center_min"], peak["width_min"], peak["amplitude"]) * det.base_multiplier
    rates *= day_mult
    return rates


def _phase_active_seconds(
    phases: list[PhaseSpec],
    jitter: float,
    day_start: datetime,
    rng: random.Random,
) -> tuple[list[dict], dict[int, np.ndarray]]:
    """Walk the day emitting signal events; return (event list, per-phase active
    1/0 mask at 1-second resolution)."""
    n_sec = 86400
    active = {p.number: np.zeros(n_sec, dtype=bool) for p in phases}
    nominal = sum(p.duration_s for p in phases)
    scale_bound = jitter / nominal if nominal else 0.0
    cursor = 0
    events: list[dict] = []
    while cursor < n_sec:
        scale = 1.0 + rng.uniform(-scale_bound, scale_bound) if scale_bound else 1.0
        for ph in phases:
            g_end = int(cursor + ph.green_s * scale)
            y_end = int(g_end + ph.yellow_s * scale)
            r_end = int(y_end + ph.all_red_s * scale)
            active[ph.number][cursor:min(g_end, n_sec)] = True
            ts_g = day_start + timedelta(seconds=cursor)
            ts_y = day_start + timedelta(seconds=g_end)
            ts_r = day_start + timedelta(seconds=y_end)
            if cursor < n_sec:
                events.append({"ts": ts_g, "phase": ph.number, "state": "GREEN_ON"})
            if g_end < n_sec:
                events.append({"ts": ts_y, "phase": ph.number, "state": "YELLOW_ON"})
            if y_end < n_sec:
                events.append({"ts": ts_r, "phase": ph.number, "state": "RED_ON"})
            cursor = r_end
            if cursor >= n_sec:
                break
    return events, active


def _simulate_detector(
    det: DetectorSpec,
    per_min_demand: np.ndarray,
    phase_active: dict[int, np.ndarray],
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (counts_per_15min[96], occupancy_pct_per_15min[96])."""
    per_sec_rate = np.repeat(per_min_demand / 60.0, 60)
    arrivals = rng.poisson(per_sec_rate).astype(np.int32)

    main_phase = APPROACH_TO_PHASE[det.approach]
    left_phase = LEFT_PHASE[det.approach]
    active_main = phase_active.get(main_phase, np.zeros(86400, dtype=bool))
    active_left = phase_active.get(left_phase, np.zeros(86400, dtype=bool))
    green = active_main if det.lane_type in ("through", "right", "shared") else active_left

    sat_per_s = SATURATION_FLOW_VPH_PER_LANE / 3600.0
    queue = 0.0
    discharge = np.zeros(86400, dtype=np.int32)
    for t in range(86400):
        queue += arrivals[t]
        if green[t]:
            d = min(queue, sat_per_s)
            queue -= d
            d_int = int(d)
            frac = d - d_int
            if frac > 0 and rng.random() < frac:
                d_int += 1
            discharge[t] = d_int
        else:
            discharge[t] = 0

    bins = discharge.reshape(BINS_PER_DAY, 900).sum(axis=1)
    on_loop = (discharge > 0).reshape(BINS_PER_DAY, 900).mean(axis=1) * 100.0
    return bins.astype(np.int32), on_loop.astype(np.float32)


def run_analytic(
    profiles_path: Path,
    phase_plan_path: Path,
    site_meta_path: Path,
    out_dir: Path,
    day: date,
    intersection_id: str,
    seed: int,
) -> dict[str, Path]:
    """Deterministic non-SUMO fallback (cell-transmission-style)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    detectors, profile_cfg = _load_detectors(profiles_path)
    phases, jitter = _load_phases(phase_plan_path)

    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rng_np = np.random.default_rng(seed * 1_000_003 + day.toordinal())
    rng_py = random.Random(seed * 1_000_003 + day.toordinal())
    signal_events, phase_active = _phase_active_seconds(phases, jitter,
                                                        day_start, rng_py)

    is_weekend = day.weekday() >= 5
    bin_ts = [pd.Timestamp(day_start + timedelta(minutes=15 * i))
              for i in range(BINS_PER_DAY)]

    rows: list[dict] = []
    trajectory_rows: list[dict] = []
    meta = json.loads(site_meta_path.read_text())
    stop_line_by_approach = {sl["approach"]: sl["polyline_px"]
                             for sl in meta["stop_lines"]}
    vehicle_id_counter = 0
    for det in detectors:
        demand = _per_minute_demand(profile_cfg, det, is_weekend)
        counts, occ = _simulate_detector(det, demand, phase_active, rng_np)
        for i, ts in enumerate(bin_ts):
            rows.append({
                "timestamp": ts,
                "intersection_id": intersection_id,
                "detector_id": det.id,
                "approach": det.approach,
                "lane": int(det.lane),
                "lane_type": det.lane_type,
                "vehicle_count": int(counts[i]),
                "occupancy_pct": float(occ[i]),
                "quality_flag": 0,
            })
        sample_frac = 0.05
        n_sample = int(counts.sum() * sample_frac)
        if n_sample > 0:
            probs = counts / counts.sum() if counts.sum() else None
            bins_sel = rng_np.choice(BINS_PER_DAY, size=n_sample, p=probs)
            for b in bins_sel:
                t_offset_s = int(rng_np.integers(0, 900))
                ts = bin_ts[b].to_pydatetime() + timedelta(seconds=int(t_offset_s))
                sl = stop_line_by_approach.get(det.approach, [[960, 540], [960, 540]])
                sx = (sl[0][0] + sl[1][0]) / 2
                sy = (sl[0][1] + sl[1][1]) / 2
                trajectory_rows.append({
                    "timestamp": ts,
                    "vehicle_id": f"V{vehicle_id_counter:07d}",
                    "approach": det.approach,
                    "lane": int(det.lane),
                    "detector_id": det.id,
                    "stop_line_px_x": float(sx),
                    "stop_line_px_y": float(sy),
                })
                vehicle_id_counter += 1

    df = pd.DataFrame.from_records(rows)
    counts_path = out_dir / f"counts_{day.isoformat()}.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=COUNTS_SCHEMA,
                                        preserve_index=False),
                   counts_path, compression="zstd")

    signal_path = out_dir / f"signal_{day.isoformat()}.ndjson"
    with signal_path.open("w") as fh:
        for ev in signal_events:
            ts: datetime = ev["ts"]
            if ts >= day_start + timedelta(days=1):
                break
            fh.write(json.dumps({
                "timestamp": ts.astimezone(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                "intersection_id": intersection_id,
                "phase": ev["phase"],
                "state": ev["state"],
            }) + "\n")

    traj_path = out_dir / f"trajectories_{day.isoformat()}.parquet"
    if trajectory_rows:
        traj_df = pd.DataFrame.from_records(trajectory_rows)
        pq.write_table(pa.Table.from_pandas(traj_df, preserve_index=False),
                       traj_path, compression="zstd")
    else:
        traj_path.write_bytes(b"")

    print(f"[analytic] {day}  counts rows={len(rows)}  "
          f"signal events={len(signal_events)}  "
          f"traj rows={len(trajectory_rows)}  →  {out_dir}", file=sys.stderr)
    return {"counts": counts_path, "signals": signal_path,
            "trajectories": traj_path, "mode": Path("analytic")}


# ─── Entry point ────────────────────────────────────────────────────────────
def run(
    profiles_path: Path,
    phase_plan_path: Path,
    site_meta_path: Path,
    out_dir: Path,
    day: date,
    intersection_id: str,
    seed: int,
    use_sumo: bool,
    duration_s: float,
    traj_sample_frac: float,
) -> dict[str, Path]:
    if use_sumo:
        return run_sumo(
            scenario_dir=SCENARIO_DIR,
            profiles_path=profiles_path,
            site_meta_path=site_meta_path,
            out_dir=out_dir,
            day=day,
            intersection_id=intersection_id,
            seed=seed,
            duration_s=duration_s,
            traj_sample_frac=traj_sample_frac,
        )
    return run_analytic(
        profiles_path=profiles_path,
        phase_plan_path=phase_plan_path,
        site_meta_path=site_meta_path,
        out_dir=out_dir,
        day=day,
        intersection_id=intersection_id,
        seed=seed,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profiles", type=Path, default=Path("phase1-sandbox/configs/profiles.yml"))
    p.add_argument("--phase-plan", type=Path, default=Path("phase1-sandbox/configs/phase_plan.yml"))
    p.add_argument("--site-meta", type=Path,
                   default=Path("phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"))
    p.add_argument("--out-dir", type=Path, default=Path("data/research/sumo"))
    p.add_argument("--date", type=str, default=date.today().isoformat())
    p.add_argument("--intersection-id", default="SITE1")
    p.add_argument("--seed", type=int, default=42)

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--sumo", dest="use_sumo", action="store_true", default=True,
                      help="Drive real SUMO via TraCI (default)")
    mode.add_argument("--analytic", dest="use_sumo", action="store_false",
                      help="Force analytic fallback (no SUMO needed)")

    p.add_argument("--duration-s", type=float, default=86400.0,
                   help="Simulated seconds for SUMO mode (default: full day)")
    p.add_argument("--traj-sample-frac", type=float, default=0.05,
                   help="Fraction of SUMO steps to sample all vehicle poses")
    args = p.parse_args(argv)

    result = run(
        profiles_path=args.profiles,
        phase_plan_path=args.phase_plan,
        site_meta_path=args.site_meta,
        out_dir=args.out_dir,
        day=date.fromisoformat(args.date),
        intersection_id=args.intersection_id,
        seed=args.seed,
        use_sumo=args.use_sumo,
        duration_s=args.duration_s,
        traj_sample_frac=args.traj_sample_frac,
    )
    print(json.dumps({k: str(v) for k, v in result.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
