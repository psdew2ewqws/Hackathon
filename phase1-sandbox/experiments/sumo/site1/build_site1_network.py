"""Emit a clean 4-way .net.xml that matches site1.example.json exactly.

Why hand-authored vs. OSM:
    Phase 2 detection writes events keyed to N/S/E/W approaches defined in
    site1.example.json. Real Wadi Saqra OSM junctions are skewed T-junctions
    and multi-node clusters — their geometry does not cleanly map to that
    cardinal schema. This script generates a synthetic 4-way whose lane
    counts, lane types, and approach bearings match site1.json 1:1, so the
    SUMO demand calibration from phase2.ndjson is semantically faithful.

Outputs:
    site1/synth/nodes.nod.xml    — 5 nodes (center + 4 approach endpoints)
    site1/synth/edges.edg.xml    — 8 directed edges (4 in + 4 out)
    site1/synth/connections.con.xml — allowed turn movements per lane
    site1/synth/net.net.xml      — assembled network (invokes netconvert)
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

APPROACH_LEN_M = 300.0          # length of each approach edge
LANE_WIDTH_DEFAULT = 3.5         # SUMO default
SPEED_LIMIT_MS = 13.9            # ~50 km/h urban arterial
PRIORITY_MAJOR = 3
PRIORITY_MINOR = 2
MAJOR_APPROACHES = {"N", "S"}


def _bearing_xy(bearing_deg: float, length_m: float) -> tuple[float, float]:
    """Convert a compass bearing + length into (dx, dy) in SUMO's xy frame
    where +y is north, +x is east."""
    theta = math.radians(bearing_deg)
    return length_m * math.sin(theta), length_m * math.cos(theta)


def _lane_type_to_index(lane_type: str) -> int:
    """Map site1.json lane_type onto SUMO lane index. Lane 0 = rightmost."""
    order = {"right": 0, "through": 1, "left": 2, "shared": 0}
    return order.get(lane_type, 1)


def build(site_meta: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Nodes: center + 4 endpoints ──────────────────────────────────────
    nodes_root = ET.Element("nodes")
    ET.SubElement(nodes_root, "node", id="site1_center", x="0", y="0",
                  type="traffic_light")

    endpoint_coords: dict[str, tuple[float, float]] = {}
    for appr in site_meta["approaches"]:
        name = appr["name"]
        bearing_in = appr["direction_bearing_deg"]  # compass bearing of approach
        # Endpoint is where vehicles come FROM (opposite of the approach flow)
        # approach N = traffic coming FROM north → endpoint is north (bearing 0)
        # approach S = traffic coming FROM south → endpoint is south (bearing 180)
        dx, dy = _bearing_xy(bearing_in, APPROACH_LEN_M)
        endpoint_coords[name] = (dx, dy)
        ET.SubElement(nodes_root, "node",
                      id=f"site1_{name}_end",
                      x=f"{dx:.1f}", y=f"{dy:.1f}",
                      type="priority")

    nodes_path = out_dir / "nodes.nod.xml"
    ET.ElementTree(nodes_root).write(nodes_path, encoding="utf-8",
                                     xml_declaration=True)

    # ── 2. Edges: one inbound + one outbound per approach ───────────────────
    edges_root = ET.Element("edges")
    edge_registry: list[dict] = []

    for appr in site_meta["approaches"]:
        name = appr["name"]
        n_lanes = len(appr["lanes"])
        priority = (PRIORITY_MAJOR if name in MAJOR_APPROACHES
                    else PRIORITY_MINOR)

        # Inbound: endpoint → center
        ET.SubElement(edges_root, "edge",
                      id=f"in_{name}",
                      attrib={
                          "from": f"site1_{name}_end",
                          "to": "site1_center",
                          "numLanes": str(n_lanes),
                          "speed": f"{SPEED_LIMIT_MS:.1f}",
                          "priority": str(priority),
                      })
        edge_registry.append({"id": f"in_{name}", "approach": name,
                              "direction": "in", "num_lanes": n_lanes})

        # Outbound: center → endpoint (3 lanes, we don't need lane-type fidelity
        # on outbound since phase2 only observes inbound crossings)
        ET.SubElement(edges_root, "edge",
                      id=f"out_{name}",
                      attrib={
                          "from": "site1_center",
                          "to": f"site1_{name}_end",
                          "numLanes": "3",
                          "speed": f"{SPEED_LIMIT_MS:.1f}",
                          "priority": str(priority),
                      })
        edge_registry.append({"id": f"out_{name}", "approach": name,
                              "direction": "out", "num_lanes": 3})

    edges_path = out_dir / "edges.edg.xml"
    ET.ElementTree(edges_root).write(edges_path, encoding="utf-8",
                                     xml_declaration=True)

    # ── 3. Connections: right → right-out, through → opposite-out, left → left-out
    # Lane indexing in SUMO: lane 0 is rightmost (furthest from centerline).
    # site1.json lists lanes 1..N where 1 is rightmost; we preserve that order
    # so SUMO lane i-1 == site1.json lane i.
    conns_root = ET.Element("connections")
    right_of = {"N": "W", "S": "E", "E": "N", "W": "S"}
    opposite_of = {"N": "S", "S": "N", "E": "W", "W": "E"}
    left_of = {"N": "E", "S": "W", "E": "S", "W": "N"}

    for appr in site_meta["approaches"]:
        name = appr["name"]
        for idx, lane in enumerate(appr["lanes"]):
            lt = lane["type"]
            if lt == "right":
                target = right_of[name]
            elif lt == "left":
                target = left_of[name]
            elif lt == "shared":
                target = opposite_of[name]
            else:  # through
                target = opposite_of[name]
            # Outbound lane: pick a lane index that exists on out_<target>
            # Right/left turn → outer lane (0), through → middle (1)
            to_lane = 0 if lt in ("right", "left") else 1
            ET.SubElement(conns_root, "connection",
                          attrib={
                              "from": f"in_{name}",
                              "to": f"out_{target}",
                              "fromLane": str(idx),
                              "toLane": str(to_lane),
                          })

    conns_path = out_dir / "connections.con.xml"
    ET.ElementTree(conns_root).write(conns_path, encoding="utf-8",
                                     xml_declaration=True)

    # ── 4. Assemble via netconvert ───────────────────────────────────────────
    net_path = out_dir / "net.net.xml"
    cmd = [
        "netconvert",
        "--node-files", str(nodes_path),
        "--edge-files", str(edges_path),
        "--connection-files", str(conns_path),
        "--output-file", str(net_path),
        "--tls.default-type", "static",
        "--no-turnarounds",
        "--junctions.corner-detail", "5",
    ]
    print(f"[build_net] {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)

    summary = {
        "nodes": str(nodes_path),
        "edges": str(edges_path),
        "connections": str(conns_path),
        "net": str(net_path),
        "num_approaches": len(site_meta["approaches"]),
        "num_edges": len(edge_registry),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--site-meta", type=Path,
                   default=Path("phase1-sandbox/src/traffic_intel_sandbox/"
                                "metadata/site1.example.json"))
    p.add_argument("--out-dir", type=Path,
                   default=Path("phase1-sandbox/experiments/sumo/site1/synth"))
    args = p.parse_args(argv)

    meta = json.loads(args.site_meta.read_text())
    summary = build(meta, args.out_dir)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
