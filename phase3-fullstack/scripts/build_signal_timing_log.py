#!/usr/bin/env python3
"""Generate a Phase 1 §6.4 signal timing log for a single calendar day.

Each line of the NDJSON output is a phase-transition event:
    timestamp, intersection_id, phase_number, signal_state
with the extras phase_name, cycle_number, approaches_affected, duration_seconds.

Usage:
    python build_signal_timing_log.py \\
        --site phase3-fullstack/configs/wadi_saqra.json \\
        --date 2026-04-22 \\
        --out data/signal_timing_log/wadi_saqra_2026-04-22.ndjson
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from traffic_intel_phase3.poc_wadi_saqra.signal_sim import CurrentPlan, generate_day


def _resolve_tz(offset_str: str | None) -> timezone:
    if offset_str is None:
        try:
            return ZoneInfo("Asia/Amman")  # type: ignore[return-value]
        except Exception:
            return timezone(timedelta(hours=3))
    sign = 1 if offset_str.startswith("+") else -1
    hh, mm = offset_str[1:].split(":")
    return timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", type=Path, required=True,
                    help="site config JSON with .signal.current_plan")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--tz", default=None,
                    help="Override timezone (e.g. +03:00). Default: Asia/Amman")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    site = json.loads(args.site.read_text())
    site_id = site.get("site_id", args.site.stem)
    cp = (site.get("signal") or {}).get("current_plan") or {}
    plan = CurrentPlan(
        NS_green=float(cp.get("NS_green", 35)),
        EW_green=float(cp.get("EW_green", 35)),
        yellow=float(cp.get("yellow", 3)),
        all_red=float(cp.get("all_red", 2)),
    )

    tz = _resolve_tz(args.tz)
    y, m, d = (int(x) for x in args.date.split("-"))
    start = datetime(y, m, d, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1)

    events = generate_day(plan, site_id, start, end)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fp:
        for ev in events:
            fp.write(json.dumps(ev) + "\n")

    print(f"wrote {args.out}")
    print(f"  intersection={site_id}  date={args.date}  tz={tz}")
    print(f"  cycle={plan.cycle_seconds}s  events={len(events)}")
    print(f"  per_cycle: NS={plan.NS_green}s EW={plan.EW_green}s yellow={plan.yellow}s all_red={plan.all_red}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
