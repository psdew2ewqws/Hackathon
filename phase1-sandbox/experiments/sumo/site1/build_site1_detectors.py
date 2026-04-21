"""Emit SUMO induction-loop additionals mirroring profiles.yml DET-* IDs.

One <inductionLoop> per detector in profiles.yml, placed at ~50 m upstream of
the stop line on the matching (approach, lane) pair. The induction-loop id
matches the DET-* id exactly so Phase 2 / downstream consumers see the same
namespace whether counts come from the analytic generator or real SUMO.

profiles.yml detectors look like:
    - {id: DET-N-1-1, approach: N, lane: 1, lane_type: right, base_multiplier: 0.6}

SUMO lane indexing: lane 0 == rightmost. site1.json lane 1 == rightmost.
So SUMO lane index = profiles.yml lane - 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml


LOOP_POSITION_FROM_END_M = 50.0   # loop 50 m upstream of the stop line


def build(profiles: dict, out_path: Path, freq_s: float = 60.0) -> dict:
    root = ET.Element("additional")
    loop_positions: dict[str, tuple[str, int, float]] = {}

    # Detectors on the same (approach, lane) pair need distinct positions so
    # SUMO doesn't reject them. Stagger by 5 m upstream per extra detector.
    per_lane_count: dict[tuple[str, int], int] = {}
    for det in profiles["detectors"]:
        appr = det["approach"]
        lane_sumo = int(det["lane"]) - 1
        edge_id = f"in_{appr}"
        lane_id = f"{edge_id}_{lane_sumo}"

        slot = per_lane_count.get((appr, lane_sumo), 0)
        pos_from_end = LOOP_POSITION_FROM_END_M + 5.0 * slot
        per_lane_count[(appr, lane_sumo)] = slot + 1

        ET.SubElement(root, "inductionLoop",
                      id=det["id"],
                      lane=lane_id,
                      pos=str(-pos_from_end),  # negative = from end of lane
                      freq=str(int(freq_s)),
                      file="NUL")  # we read via TraCI, no per-loop file needed
        loop_positions[det["id"]] = (appr, lane_sumo, pos_from_end)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(out_path, encoding="utf-8",
                               xml_declaration=True)
    return {"out": str(out_path),
            "num_loops": len(loop_positions),
            "freq_s": freq_s}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--profiles", type=Path,
                   default=Path("phase1-sandbox/configs/profiles.yml"))
    p.add_argument("--out", type=Path,
                   default=Path("phase1-sandbox/experiments/sumo/site1/synth/"
                                "detectors.add.xml"))
    p.add_argument("--freq-s", type=float, default=60.0)
    args = p.parse_args(argv)
    profiles = yaml.safe_load(args.profiles.read_text())
    summary = build(profiles, args.out, args.freq_s)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
