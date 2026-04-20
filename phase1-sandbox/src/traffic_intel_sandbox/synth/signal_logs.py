"""C9 — Synthetic signal timing log generator.

Emits one ndjson per day at ``--out-dir/signal_YYYY-MM-DD.ndjson`` with one
event per phase transition:

    {"timestamp": "...", "intersection_id": "SITE1", "phase": 2, "state": "GREEN_ON"}

Cycle length is derived from the sum of phase green+yellow+allred times in
the phase plan YAML. Cycle lengths are randomized within ±`cycle_jitter_s`
to mimic a semi-actuated controller.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

INTERSECTION_ID_DEFAULT = os.environ.get("INTERSECTION_ID", "SITE1")

STATE_ORDER = ("GREEN_ON", "YELLOW_ON", "RED_ON")


@dataclass(frozen=True)
class Phase:
    number: int
    name: str
    green_s: float
    yellow_s: float
    all_red_s: float  # clearance before next phase begins

    @property
    def duration_s(self) -> float:
        return self.green_s + self.yellow_s + self.all_red_s


@dataclass(frozen=True)
class PhasePlan:
    phases: tuple[Phase, ...]
    cycle_jitter_s: float

    @property
    def nominal_cycle_s(self) -> float:
        return sum(p.duration_s for p in self.phases)

    @staticmethod
    def load(path: Path) -> "PhasePlan":
        with path.open() as fh:
            raw = yaml.safe_load(fh)
        phases = tuple(Phase(**p) for p in raw["phases"])
        return PhasePlan(phases=phases, cycle_jitter_s=float(raw.get("cycle_jitter_s", 0)))


def _iso_ms(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def emit_day(
    day: date,
    plan: PhasePlan,
    intersection_id: str,
    rng: random.Random,
    out_path: Path,
) -> int:
    """Write one day of events to out_path. Returns event count."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    cursor = start
    n_events = 0
    with out_path.open("w") as fh:
        while cursor < end:
            # Pick a random scale factor per cycle within ±jitter
            cycle_scale = 1.0
            if plan.cycle_jitter_s:
                scale_bound = plan.cycle_jitter_s / plan.nominal_cycle_s
                cycle_scale = 1.0 + rng.uniform(-scale_bound, scale_bound)
            for phase in plan.phases:
                # GREEN_ON
                if cursor >= end:
                    break
                _emit(fh, cursor, intersection_id, phase.number, "GREEN_ON")
                n_events += 1
                cursor += timedelta(seconds=phase.green_s * cycle_scale)
                # YELLOW_ON
                if cursor >= end:
                    break
                _emit(fh, cursor, intersection_id, phase.number, "YELLOW_ON")
                n_events += 1
                cursor += timedelta(seconds=phase.yellow_s * cycle_scale)
                # RED_ON (all-red clearance belongs to current phase; next phase
                # begins with its own GREEN_ON event)
                if cursor >= end:
                    break
                _emit(fh, cursor, intersection_id, phase.number, "RED_ON")
                n_events += 1
                cursor += timedelta(seconds=phase.all_red_s * cycle_scale)
    return n_events


def _emit(fh, ts: datetime, intersection_id: str, phase: int, state: str) -> None:
    fh.write(json.dumps({
        "timestamp": _iso_ms(ts),
        "intersection_id": intersection_id,
        "phase": phase,
        "state": state,
    }) + "\n")


def generate(
    phase_plan_path: Path,
    out_dir: Path,
    days: int,
    start_date: date,
    intersection_id: str,
    seed: int,
) -> list[Path]:
    plan = PhasePlan.load(phase_plan_path)
    if not (90 <= plan.nominal_cycle_s <= 120):
        print(
            f"[warn] nominal cycle {plan.nominal_cycle_s:.0f}s is outside handbook §6.4 90–120s",
            file=sys.stderr,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        rng = random.Random(seed * 1_000_003 + day.toordinal())
        out_path = out_dir / f"signal_{day.isoformat()}.ndjson"
        n = emit_day(day, plan, intersection_id, rng, out_path)
        written.append(out_path)
        print(f"[signals] {day}  events={n}  cycle≈{plan.nominal_cycle_s:.0f}s  →  {out_path.name}",
              file=sys.stderr)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic signal timing ndjson logs.")
    parser.add_argument("--phase-plan", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--intersection-id", default=INTERSECTION_ID_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    start = (
        datetime.fromisoformat(args.start_date).date()
        if args.start_date
        else date.today() - timedelta(days=args.days)
    )
    written = generate(args.phase_plan, args.out_dir, args.days, start, args.intersection_id, args.seed)
    print(f"[done] {len(written)} day-ndjson(s) written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
