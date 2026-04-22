"""Webster-based signal-timing optimizer — §8.3-compliant recommendations.

Consumes the per-approach demand forecast (`forecast_day.json` produced by
``forecast.predict``) and produces, for a chosen time-of-day T, an
academically-grounded evaluation + recommendation for the four NEMA phases
of a standard isolated-intersection signal plan. Output is **advisory
only**, consistent with the Hackathon Handbook §11 isolation rule.

Two modes
---------

* ``evaluate`` — for a user-supplied set of green times, compute per-
  approach v/c and delay. Used by the dashboard slider.
* ``recommend`` — compute Webster-optimal cycle + split from scratch
  based on the demand. Used by the dashboard "Webster Recommend" button.

Algorithm references (one canonical source per formula)
-------------------------------------------------------

* **Webster, F. V. (1958)**. *Traffic Signal Settings.* Road Research
  Technical Paper No. 39, Her Majesty's Stationery Office, London.
    - Flow ratio:        y_i = v_i / (s · n_i)
    - Critical Y:        Y = Σ_{critical i} y_i
    - Optimal cycle:     C_opt = (1.5·L + 5) / (1 − Y)
    - Green split:       g_i = (y_i / Y) · (C_opt − L)

* **Highway Capacity Manual (HCM), Transportation Research Board, 6th ed.,
  Chapter 18 — Signalised Intersections.**
    - Saturation flow:   s ≈ 1800 veh/hr/lane for typical urban
    - Degree of sat'n:   X_i = (v_i · C) / (s · n_i · g_i)
    - Uniform delay:     d_i = 0.5 · C · (1 − g_i/C)² / (1 − min(1, X_i) · g_i/C)

* **9XAI Hackathon Handbook §8.3** — recommendation categories: extend
  green, reduce green, cycle adjustment, congestion identification.

Calibration caveat
------------------

Demand ``v_A(T)`` is read from ``forecast.predict``'s per-approach count.
Those counts are zone-entry deltas from YOLO tracking, which over-count
~5× versus true vehicle-throughput (documented in predict.py). The
optimizer applies a global ``correction_factor`` (default 0.2) that undoes
this inflation before Webster's math runs. The factor is configurable via
CLI or function argument.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path


# ── Static parameters (HCM defaults) ─────────────────────────────────────
S_PER_LANE          = 1800.0   # HCM typical urban saturation flow, veh/hr/lane
L_PHASE_SECONDS     = 5        # yellow (3) + all-red (2) per NEMA phase
NUM_PHASES          = 4        # Phases 2, 6, 4, 8
LOST_TIME_TOTAL     = L_PHASE_SECONDS * NUM_PHASES   # 20 s per cycle
C_MIN               = 60       # §6.4 handbook lower bound
C_MAX               = 120      # §6.4 handbook upper bound
MIN_GREEN           = 7        # pedestrian crossing minimum
MAX_GREEN           = 60       # single-phase upper bound for NEMA practice
DEFAULT_CORRECTION  = 0.2      # undo the ~5× YOLO over-count (see caveat)


# ── Phase ↔ approach wiring (mirrors phase_plan.yml + site1.example.json) ──
# Each NEMA phase serves one or two movement groups. The ``critical``
# attribute marks which phases contend for the Webster cycle calc: phase 2
# (N/S through) and phase 4 (E/W through) are the critical pair because N/S
# left (phase 6) runs *within* the same cycle segment as N/S through, so
# we take the max — not sum — at the critical-y calculation.

@dataclass(frozen=True)
class PhaseMap:
    number:    int
    name:      str
    approach:  str          # "N", "S", "E", or "W"
    lane_type: str          # "through" or "left"
    critical:  bool         # is this a through-phase in the critical sum?


PHASES: list[PhaseMap] = [
    PhaseMap(2, "N/S through", "N", "through", True),
    PhaseMap(2, "N/S through", "S", "through", True),    # dupe for both approaches
    PhaseMap(6, "N/S left",    "N", "left",    False),
    PhaseMap(6, "N/S left",    "S", "left",    False),
    PhaseMap(4, "E/W through", "E", "through", True),
    PhaseMap(4, "E/W through", "W", "through", True),
    PhaseMap(8, "E/W left",    "E", "left",    False),
    PhaseMap(8, "E/W left",    "W", "left",    False),
]

DEFAULT_GREEN_S = {2: 35, 6: 15, 4: 22, 8: 10}   # matches phase_plan.yml


# ── Data classes ─────────────────────────────────────────────────────────
@dataclass
class ApproachInput:
    approach:  str    # "N"|"S"|"E"|"W"
    volume_vph: float # demand in veh/hr AFTER correction factor
    lanes:     int    # number of approach lanes


@dataclass
class EvalRow:
    approach:  str
    phase:     int
    green_s:   float
    volume_vph: float
    lanes:     int
    flow_ratio_y: float     # v_i / (s · n_i)
    capacity_vph: float     # s · n_i · g_i / C
    x:         float        # degree of saturation
    delay_s:   float        # HCM uniform delay per vehicle
    recommendation: str     # §8.3 advisory
    signal_color: str       # "green"|"yellow"|"red"


@dataclass
class EvalResult:
    cycle_s:         int
    lost_time_s:     int
    critical_y:      float     # Y = y_NSthru + y_EWthru
    rows:            list[EvalRow] = field(default_factory=list)
    summary:         dict = field(default_factory=dict)


# ── Core math ────────────────────────────────────────────────────────────
def flow_ratio(volume_vph: float, lanes: int) -> float:
    """y_i = v_i / (s · n_i). Webster 1958."""
    if lanes <= 0:
        return 0.0
    return volume_vph / (S_PER_LANE * lanes)


def critical_y(approach_inputs: dict[str, ApproachInput]) -> float:
    """Y = y_NSthru + y_EWthru (the two critical through-movements).

    We use the max of N/S as the NS-critical and max of E/W as EW-critical
    because opposing through movements share the cycle time.
    """
    def y_of(a: str) -> float:
        ap = approach_inputs.get(a)
        return flow_ratio(ap.volume_vph, ap.lanes) if ap else 0.0
    y_ns = max(y_of("N"), y_of("S"))
    y_ew = max(y_of("E"), y_of("W"))
    return y_ns + y_ew


def webster_cycle(Y: float,
                  lost_time_s: float = LOST_TIME_TOTAL,
                  c_min: int = C_MIN, c_max: int = C_MAX) -> int:
    """Webster optimal cycle length.
    C_opt = (1.5·L + 5) / (1 − Y), clamped to [C_min, C_max].
    Falls back to C_max when Y ≥ 1 (oversaturated — stretch the cycle)."""
    if Y >= 1.0:
        return c_max
    c = (1.5 * lost_time_s + 5.0) / (1.0 - Y)
    return max(c_min, min(c_max, int(round(c))))


def webster_split(approach_inputs: dict[str, ApproachInput],
                  cycle_s: int,
                  lost_time_s: int = LOST_TIME_TOTAL) -> dict[int, int]:
    """Return {phase_number: green_seconds} via Webster's proportional
    allocation, then clamp to [MIN_GREEN, MAX_GREEN]."""
    # Per-phase critical volume: the HIGHER of the two approaches that share
    # the phase. NS-through is phase 2, shared by N and S approaches; etc.
    def phase_critical(phase_num: int) -> ApproachInput | None:
        candidates = [p.approach for p in PHASES if p.number == phase_num]
        best: ApproachInput | None = None
        for a in candidates:
            ap = approach_inputs.get(a)
            if ap and (best is None or ap.volume_vph > best.volume_vph):
                best = ap
        return best

    ys: dict[int, float] = {}
    for ph in (2, 6, 4, 8):
        ap = phase_critical(ph)
        ys[ph] = flow_ratio(ap.volume_vph, ap.lanes) if ap else 0.0
    Y = sum(ys.values()) or 1.0   # avoid div-by-zero

    usable_green = max(0, cycle_s - lost_time_s)
    raw = {ph: (ys[ph] / Y) * usable_green for ph in (2, 6, 4, 8)}
    clamped = {ph: max(MIN_GREEN, min(MAX_GREEN, int(round(g))))
               for ph, g in raw.items()}

    # Rescale so total green + lost_time equals cycle (integer drift happens)
    total = sum(clamped.values()) + lost_time_s
    drift = cycle_s - total
    if drift != 0:
        # Nudge the largest phase by drift
        biggest = max(clamped, key=lambda p: clamped[p])
        clamped[biggest] = max(MIN_GREEN, min(MAX_GREEN,
                                              clamped[biggest] + drift))
    return clamped


def hcm_uniform_delay(cycle_s: float, green_s: float, x: float) -> float:
    """HCM 6th ed. uniform delay (Eq. 18-17, simplified).
    d1 = 0.5 · C · (1 − g/C)² / (1 − min(1, X) · g/C)"""
    if cycle_s <= 0 or green_s <= 0:
        return 0.0
    green_ratio = green_s / cycle_s
    x_eff = min(1.0, x)
    denom = 1.0 - x_eff * green_ratio
    if denom <= 0:
        return 9999.0   # oversaturated sentinel
    return 0.5 * cycle_s * (1 - green_ratio) ** 2 / denom


def signal_color(x: float) -> str:
    """v/c → dashboard colour mapping (aligned with Google-style bands)."""
    if x < 0.85: return "green"
    if x < 1.00: return "yellow"
    return "red"


def recommendation(x: float, green_s: float, cycle_s: int,
                   cycle_saturated: bool) -> str:
    """Handbook §8.3 advisory rule fire.
    Only one recommendation fires per call; fall through to silent."""
    if x >= 1.0:
        if cycle_saturated:
            return f"v/c = {x:.2f}. Phase saturated; raise cycle toward {C_MAX}s."
        return f"v/c = {x:.2f}. Extend green on this approach by +5 s."
    if x > 0.9:
        suggested = min(MAX_GREEN, int(green_s) + 5)
        return f"v/c = {x:.2f}. Extend green to {suggested} s (high demand)."
    if x < 0.5:
        suggested = max(MIN_GREEN, int(green_s) - 5)
        return f"v/c = {x:.2f}. Reduce green to {suggested} s (low demand)."
    return f"v/c = {x:.2f}. Within target range; no change."


# ── Top-level API ────────────────────────────────────────────────────────
def _approach_inputs(forecast_rows: list[dict],
                     target_hhmm: str,
                     approach_lanes: dict[str, int],
                     correction_factor: float) -> dict[str, ApproachInput]:
    """Pull per-approach demand at target_hhmm, apply correction factor, and
    convert from observed count to vph by scaling to the forecast anchor
    window. The anchor reports count over a 30-s-ish YOLO window; we assume
    the forecast already encodes counts in comparable units across slots.

    Design choice: since the forecast's ``count`` field is on the same scale
    regardless of slot, we treat a count of N at a slot as a proxy for
    N · correction_factor · (3600 / anchor_window_s) vph. We pass-through
    the anchor duration-scaled value supplied by the caller — this function
    just multiplies by correction_factor and returns the per-approach map.
    """
    out: dict[str, ApproachInput] = {}
    for row in forecast_rows:
        if row.get("time") != target_hhmm:
            continue
        appr = row.get("approach")
        if appr not in ("N", "S", "E", "W"):
            continue
        count = row.get("count") or 0
        vph = count * correction_factor
        lanes = approach_lanes.get(appr, 3)
        out[appr] = ApproachInput(
            approach=appr, volume_vph=float(vph), lanes=int(lanes))
    return out


def evaluate(approach_inputs: dict[str, ApproachInput],
             green_s: dict[int, int],
             cycle_s: int | None = None) -> EvalResult:
    """Score the given split. Cycle defaults to sum(green) + lost_time."""
    cycle = int(cycle_s) if cycle_s else (sum(green_s.values()) + LOST_TIME_TOTAL)
    Y = critical_y(approach_inputs)
    cycle_saturated = Y >= 0.85   # §8.3 cycle-pressure threshold

    rows: list[EvalRow] = []
    per_phase = {ph.number: ph for ph in PHASES}
    total_volume = 0.0
    total_delay_weighted = 0.0

    for pmap in PHASES:
        ai = approach_inputs.get(pmap.approach)
        if ai is None:
            continue
        g = green_s.get(pmap.number, DEFAULT_GREEN_S.get(pmap.number, 20))
        y = flow_ratio(ai.volume_vph, ai.lanes)
        capacity = S_PER_LANE * ai.lanes * g / cycle
        x = (ai.volume_vph / capacity) if capacity > 0 else 99.0
        delay = hcm_uniform_delay(cycle, g, x)
        rec = recommendation(x, g, cycle, cycle_saturated)
        rows.append(EvalRow(
            approach=pmap.approach, phase=pmap.number,
            green_s=g, volume_vph=ai.volume_vph, lanes=ai.lanes,
            flow_ratio_y=round(y, 4),
            capacity_vph=round(capacity, 1),
            x=round(x, 3), delay_s=round(delay, 1),
            recommendation=rec,
            signal_color=signal_color(x),
        ))
        total_volume += ai.volume_vph
        total_delay_weighted += delay * ai.volume_vph

    avg_delay = (total_delay_weighted / total_volume) if total_volume else 0.0
    summary = {
        "cycle_s": cycle,
        "lost_time_s": LOST_TIME_TOTAL,
        "critical_y": round(Y, 4),
        "cycle_saturated": cycle_saturated,
        "weighted_avg_delay_s": round(avg_delay, 1),
        "approach_worst_x": round(max((r.x for r in rows), default=0.0), 3),
    }
    return EvalResult(cycle_s=cycle, lost_time_s=LOST_TIME_TOTAL,
                      critical_y=round(Y, 4), rows=rows, summary=summary)


def recommend(approach_inputs: dict[str, ApproachInput]) -> tuple[int, dict[int, int]]:
    """Webster-optimal cycle + split for the given demand."""
    Y = critical_y(approach_inputs)
    c = webster_cycle(Y)
    g = webster_split(approach_inputs, c)
    return c, g


# ── CLI ──────────────────────────────────────────────────────────────────
def _load_forecast(path: Path) -> dict:
    return json.loads(path.read_text())


def _lanes_from_site(site_path: Path) -> dict[str, int]:
    try:
        site = json.loads(site_path.read_text())
        return {a["name"]: len(a.get("lanes", [])) for a in site.get("approaches", [])}
    except (OSError, json.JSONDecodeError):
        return {"N": 3, "S": 3, "E": 3, "W": 3}


def _dump_eval_table(res: EvalResult) -> None:
    print(f"cycle = {res.cycle_s}s   lost = {res.lost_time_s}s   "
          f"Y = {res.critical_y}   avg delay = {res.summary['weighted_avg_delay_s']}s")
    print(f"{'appr':<5} {'phase':>5} {'green':>6} {'vph':>6} {'cap':>6} "
          f"{'v/c':>6} {'delay':>7} {'color':<7} recommendation")
    for r in res.rows:
        print(f"{r.approach:<5} {r.phase:>5} {r.green_s:>5.0f}s "
              f"{r.volume_vph:>5.0f} {r.capacity_vph:>5.0f} "
              f"{r.x:>6.2f} {r.delay_s:>6.1f}s {r.signal_color:<7} "
              f"{r.recommendation}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--forecast", type=Path,
                   default=Path("data/forecast/forecast_day.json"))
    p.add_argument("--site", type=Path,
                   default=Path("data/forecast/forecast_site.json"))
    p.add_argument("--t", required=True, help="Target HH:MM (e.g. 17:00)")
    p.add_argument("--correction", type=float, default=DEFAULT_CORRECTION,
                   help="Correction factor for forecast over-count (default 0.2)")
    p.add_argument("--green", nargs=4, type=int, metavar=("gN_S", "gE_W", "glNS", "glEW"),
                   default=None,
                   help="Override phase 2/4/6/8 green times; skip for plan defaults")
    p.add_argument("--recommend", action="store_true",
                   help="Print Webster-optimal split instead of current eval")
    p.add_argument("--out", type=Path,
                   default=Path("data/forecast/optimize_latest.json"))
    args = p.parse_args(argv)

    forecast = _load_forecast(args.forecast)
    lanes = _lanes_from_site(args.site)
    inputs = _approach_inputs(forecast.get("rows", []),
                              args.t, lanes, args.correction)

    if not inputs:
        print(f"[optimize] no forecast data for T={args.t}")
        return 2

    # Evaluate the current (or user-specified) split
    if args.green:
        gN_S, gE_W, glNS, glEW = args.green
        green_map = {2: gN_S, 4: gE_W, 6: glNS, 8: glEW}
    else:
        green_map = dict(DEFAULT_GREEN_S)
    current = evaluate(inputs, green_map)
    print(f"\n── CURRENT plan @ T={args.t} ─────────────────────────────")
    _dump_eval_table(current)

    # Webster recommendation
    c_rec, g_rec = recommend(inputs)
    rec_eval = evaluate(inputs, g_rec, cycle_s=c_rec)
    print(f"\n── WEBSTER RECOMMENDATION @ T={args.t} ───────────────────")
    _dump_eval_table(rec_eval)

    # Delta
    cur_delay = current.summary["weighted_avg_delay_s"]
    rec_delay = rec_eval.summary["weighted_avg_delay_s"]
    if cur_delay > 0:
        reduction = (cur_delay - rec_delay) / cur_delay * 100
        print(f"\nExpected delay reduction: {reduction:+.1f}%  "
              f"({cur_delay}s → {rec_delay}s avg per vehicle)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "t":                 args.t,
        "correction_factor": args.correction,
        "approach_inputs":   {a: {"volume_vph": i.volume_vph, "lanes": i.lanes}
                              for a, i in inputs.items()},
        "current": {
            "green": green_map,
            "cycle_s": current.cycle_s,
            "rows":    [r.__dict__ for r in current.rows],
            "summary": current.summary,
        },
        "webster": {
            "green": g_rec,
            "cycle_s": c_rec,
            "rows":    [r.__dict__ for r in rec_eval.rows],
            "summary": rec_eval.summary,
        },
    }, indent=2))
    print(f"\n[optimize] full output → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
