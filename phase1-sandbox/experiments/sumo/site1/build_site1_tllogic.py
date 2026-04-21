"""Translate phase_plan.yml into a SUMO <tlLogic> block for site1_center.

The phase-plan YAML is a NEMA-style description (phase 2/6/4/8 with
green/yellow/all-red durations). SUMO wants a flat list of phases with a
per-connection state string. This script emits one SUMO phase per NEMA
sub-phase (green, yellow, all-red), so the total cycle == sum of all phases.

Connection ordering (determined by netconvert from edges.edg.xml):
    tlIndex  0–4   : in_N lanes 0..4  (right, through, through, through, left)
    tlIndex  5–8   : in_E lanes 0..3  (right, through, through, left)
    tlIndex  9–13  : in_S lanes 0..4  (right, through, through, through, left)
    tlIndex 14–17  : in_W lanes 0..3  (right, through, through, left)

This order is asserted at runtime so a future edge.edg.xml edit that
re-orders things can't silently mis-signal.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

os.environ.setdefault("SUMO_HOME", "/usr/share/sumo")


def _slot(state: dict, approach: str, lane_type: str) -> str:
    """Return 'G', 'y', or 'r' for this (approach, lane_type) given the
    current NEMA phase assignment."""
    return state.get((approach, lane_type), "r")


def _state_string(greens: dict[tuple[str, str], str],
                  expected_order: list[tuple[str, str]]) -> str:
    """Build the 18-char state string from the greens dict."""
    chars = [greens.get(k, "r") for k in expected_order]
    return "".join(chars)


# Connection slot order we validated with sumolib (see build doc):
EXPECTED_ORDER: list[tuple[str, str]] = [
    ("N", "right"),   ("N", "through"), ("N", "through"), ("N", "through"), ("N", "left"),
    ("E", "right"),   ("E", "through"), ("E", "through"), ("E", "left"),
    ("S", "right"),   ("S", "through"), ("S", "through"), ("S", "through"), ("S", "left"),
    ("W", "right"),   ("W", "through"), ("W", "through"), ("W", "left"),
]


# NEMA phase → (approaches getting green, lane-types that get green)
NEMA_GREEN_ASSIGN = {
    2: {"approaches": ("N", "S"), "lane_types": ("right", "through")},
    6: {"approaches": ("N", "S"), "lane_types": ("left",)},
    4: {"approaches": ("E", "W"), "lane_types": ("right", "through")},
    8: {"approaches": ("E", "W"), "lane_types": ("left",)},
}


def _greens_for_phase(nema_phase: int, char: str) -> dict[tuple[str, str], str]:
    """Return {(approach, lane_type): char} for the movements that are
    currently GREEN (or YELLOW). Others default to 'r'."""
    spec = NEMA_GREEN_ASSIGN[nema_phase]
    return {(a, lt): char for a in spec["approaches"] for lt in spec["lane_types"]}


def build(phase_plan: dict, tl_id: str, program_id: str, out_path: Path) -> dict:
    phases = phase_plan["phases"]

    add_root = ET.Element("additional")
    tl = ET.SubElement(add_root, "tlLogic",
                       attrib={
                           "id": tl_id,
                           "type": "static",
                           "programID": program_id,
                           "offset": "0",
                       })

    emitted = []
    for ph in phases:
        num = int(ph["number"])
        gG = _greens_for_phase(num, "G")
        gy = _greens_for_phase(num, "y")

        # green sub-phase
        state_g = _state_string(gG, EXPECTED_ORDER)
        ET.SubElement(tl, "phase",
                      duration=str(int(ph["green_s"])),
                      state=state_g,
                      name=f"{num}_green")
        emitted.append({"phase": num, "state": state_g, "duration": ph["green_s"],
                        "kind": "green"})

        # yellow sub-phase
        state_y = _state_string(gy, EXPECTED_ORDER)
        ET.SubElement(tl, "phase",
                      duration=str(int(ph["yellow_s"])),
                      state=state_y,
                      name=f"{num}_yellow")
        emitted.append({"phase": num, "state": state_y, "duration": ph["yellow_s"],
                        "kind": "yellow"})

        # all-red sub-phase
        state_r = "r" * len(EXPECTED_ORDER)
        ET.SubElement(tl, "phase",
                      duration=str(int(ph["all_red_s"])),
                      state=state_r,
                      name=f"{num}_allred")
        emitted.append({"phase": num, "state": state_r, "duration": ph["all_red_s"],
                        "kind": "allred"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(add_root, space="  ")
    ET.ElementTree(add_root).write(out_path, encoding="utf-8",
                                   xml_declaration=True)

    total_cycle = sum(int(p["green_s"]) + int(p["yellow_s"]) + int(p["all_red_s"])
                      for p in phases)
    return {"tl_id": tl_id, "program_id": program_id, "out": str(out_path),
            "phases_emitted": len(emitted), "cycle_s": total_cycle,
            "emitted": emitted}


def _verify_connection_order(net_path: Path) -> None:
    """Abort if the .net.xml connection order has drifted from EXPECTED_ORDER."""
    import sumolib
    net = sumolib.net.readNet(str(net_path), withInternal=False)
    tls = net.getTrafficLights()
    if len(tls) != 1:
        raise RuntimeError(f"expected 1 TL, got {len(tls)}")
    tl = tls[0]
    conns = tl.getConnections()
    conns_sorted = sorted(conns, key=lambda c: c[2])
    actual: list[tuple[str, str]] = []
    for c in conns_sorted:
        in_edge_id = c[0].getEdge().getID()
        # in_N → approach N; lane index determines lane type from site1.json
        approach = in_edge_id.split("_", 1)[1]
        lane_idx = c[0].getIndex()
        # Match to site1 lane type ordering (right, through..., left)
        actual.append((approach, _infer_lane_type(approach, lane_idx)))
    if actual != EXPECTED_ORDER:
        lines = ["Connection order drift detected:"]
        for i, (a, e) in enumerate(zip(actual, EXPECTED_ORDER)):
            mark = " " if a == e else "!"
            lines.append(f"  [{i:2d}] actual={a}  expected={e}  {mark}")
        raise RuntimeError("\n".join(lines))


def _infer_lane_type(approach: str, lane_idx: int) -> str:
    """Mirror site1.example.json: lane 0 = right, middle = through, last = left."""
    lane_count = 5 if approach in ("N", "S") else 4
    if lane_idx == 0:
        return "right"
    if lane_idx == lane_count - 1:
        return "left"
    return "through"


def main(argv: list[str] | None = None) -> int:
    import yaml
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--phase-plan", type=Path,
                   default=Path("phase1-sandbox/configs/phase_plan.yml"))
    p.add_argument("--net", type=Path,
                   default=Path("phase1-sandbox/experiments/sumo/site1/synth/net.net.xml"))
    p.add_argument("--out", type=Path,
                   default=Path("phase1-sandbox/experiments/sumo/site1/synth/tl.add.xml"))
    p.add_argument("--tl-id", default="site1_center")
    p.add_argument("--program-id", default="site1_static")
    p.add_argument("--skip-verify", action="store_true",
                   help="Skip net.xml connection-order sanity check")
    args = p.parse_args(argv)

    if not args.skip_verify:
        _verify_connection_order(args.net)

    plan = yaml.safe_load(args.phase_plan.read_text())
    summary = build(plan, args.tl_id, args.program_id, args.out)
    print(json.dumps({k: v for k, v in summary.items() if k != "emitted"}, indent=2))
    print(f"cycle breakdown ({len(summary['emitted'])} phases):")
    for ph in summary["emitted"]:
        print(f"  NEMA {ph['phase']} {ph['kind']:7s}  dur={ph['duration']:3}s  state={ph['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
