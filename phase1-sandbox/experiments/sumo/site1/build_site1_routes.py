"""Calibrate SUMO demand (routes.rou.xml) from phase2.ndjson crossings.

The Phase 2 detector (detect_track.py + zones.py) emits `stop_line_crossing`
events as vehicles physically cross each approach's stop-line. Summing those
gives a directly-observed per-approach inbound flow rate. We split it across
3 outbound directions (right/through/left) using the lane-type mix from
site1.example.json, which is the cleanest prior available without ground-truth
turning counts.

Input contract:
    --events  — ndjson with {event_type: stop_line_crossing, approach, timestamp}
    --site-meta — provides lane counts per approach (used for turn split)
    --duration — seconds of simulated traffic to emit (default 3600)

Output:
    routes.rou.xml  — <vType> + <flow> elements scaled to observed rates.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# Turn split strategy: proportional to lane-type counts on the approach.
#   N has 5 lanes  (1 right, 3 through, 1 left) → 20/60/20
#   E has 4 lanes  (1 right, 2 through, 1 left) → 25/50/25
# We read the real counts from site1.json rather than hardcode.

TURN_TARGETS = {
    "N": {"right": "W", "through": "S", "left": "E"},
    "S": {"right": "E", "through": "N", "left": "W"},
    "E": {"right": "N", "through": "W", "left": "S"},
    "W": {"right": "S", "through": "E", "left": "N"},
}


def _lane_type_mix(site_meta: dict, approach: str) -> dict[str, float]:
    """Return {right/through/left: fraction} based on lane counts."""
    counts = Counter()
    for appr in site_meta["approaches"]:
        if appr["name"] == approach:
            for lane in appr["lanes"]:
                lt = lane["type"]
                counts[lt if lt != "shared" else "through"] += 1
            break
    total = sum(counts.values()) or 1
    mix = {lt: counts.get(lt, 0) / total for lt in ("right", "through", "left")}
    # Renormalise if one type is missing (e.g., a rare all-through approach)
    s = sum(mix.values())
    if s > 0:
        mix = {k: v / s for k, v in mix.items()}
    return mix


def _parse_ts(ts_str: str) -> datetime:
    return datetime.strptime(ts_str.replace("Z", "+0000"),
                             "%Y-%m-%dT%H:%M:%S.%f%z")


def _aggregate_crossings(events_path: Path) -> tuple[Counter, float]:
    """Return (crossings_by_approach, observed_span_seconds)."""
    counts: Counter = Counter()
    min_ts: datetime | None = None
    max_ts: datetime | None = None
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event_type") != "stop_line_crossing":
            continue
        appr = e.get("approach")
        if appr not in ("N", "S", "E", "W"):
            continue
        counts[appr] += 1
        ts = _parse_ts(e["timestamp"])
        if min_ts is None or ts < min_ts:
            min_ts = ts
        if max_ts is None or ts > max_ts:
            max_ts = ts

    span_s = (max_ts - min_ts).total_seconds() if (min_ts and max_ts) else 0.0
    return counts, span_s


def build(site_meta: dict,
          crossings: dict[str, int],
          observed_span_s: float,
          duration_s: float,
          out_path: Path) -> dict:
    """Emit routes.rou.xml with one <flow> per (approach, turn)."""
    root = ET.Element("routes")

    # vType — one generic passenger car
    ET.SubElement(root, "vType",
                  id="car",
                  accel="2.6", decel="4.5", sigma="0.5",
                  length="5.0", maxSpeed="15",
                  color="1,1,0",
                  vClass="passenger")

    # Define routes (site1 has an inbound edge per approach and outbound to each other approach)
    # Route id convention: r_<FROM>2<TO>
    for frm in ("N", "S", "E", "W"):
        for turn, to_appr in TURN_TARGETS[frm].items():
            route_id = f"r_{frm}2{to_appr}"
            ET.SubElement(root, "route",
                          id=route_id,
                          edges=f"in_{frm} out_{to_appr}")

    # Flows — one per (approach, turn) scaled by lane-type mix
    per_approach_vph: dict[str, float] = {}
    for appr, n_cross in crossings.items():
        if observed_span_s <= 0:
            vph = 0.0
        else:
            vph = n_cross / observed_span_s * 3600.0
        per_approach_vph[appr] = vph

    flow_rows = []
    for appr in ("N", "S", "E", "W"):
        mix = _lane_type_mix(site_meta, appr)
        base_vph = per_approach_vph.get(appr, 0.0)
        for turn, to_appr in TURN_TARGETS[appr].items():
            share = mix.get(turn, 0.0)
            vph = base_vph * share
            if vph <= 0:
                continue
            flow_id = f"f_{appr}2{to_appr}"
            route_id = f"r_{appr}2{to_appr}"
            ET.SubElement(root, "flow",
                          id=flow_id,
                          route=route_id,
                          type="car",
                          begin="0",
                          end=str(int(duration_s)),
                          vehsPerHour=f"{vph:.1f}",
                          departLane="best",
                          departSpeed="max")
            flow_rows.append({"approach": appr, "turn": turn,
                              "to": to_appr, "vehsPerHour": round(vph, 1),
                              "share": round(share, 3)})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(out_path, encoding="utf-8",
                               xml_declaration=True)

    return {
        "out": str(out_path),
        "observed_span_s": round(observed_span_s, 1),
        "total_crossings": int(sum(crossings.values())),
        "per_approach_vph": {k: round(v, 1) for k, v in per_approach_vph.items()},
        "flow_rows": flow_rows,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--events", type=Path,
                   default=Path("data/events/phase2.ndjson"))
    p.add_argument("--site-meta", type=Path,
                   default=Path("phase1-sandbox/src/traffic_intel_sandbox/"
                                "metadata/site1.example.json"))
    p.add_argument("--out", type=Path,
                   default=Path("phase1-sandbox/experiments/sumo/site1/synth/"
                                "routes.rou.xml"))
    p.add_argument("--duration", type=float, default=3600.0,
                   help="Simulated seconds to emit flows over")
    args = p.parse_args(argv)

    meta = json.loads(args.site_meta.read_text())
    counts, span_s = _aggregate_crossings(args.events)
    if span_s == 0:
        print("[warn] no stop_line_crossing events found — writing empty routes")
    summary = build(meta, counts, span_s, args.duration, args.out)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
