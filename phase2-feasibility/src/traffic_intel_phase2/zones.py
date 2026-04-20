"""Zone / line-crossing helpers driven by Phase 1 intersection metadata.

Reads ``data/metadata/site1.json`` (or the shipped example) and exposes:

    • ``load_zones(meta_path)``       → list[sv.PolygonZone]    (monitoring zones)
    • ``load_stop_lines(meta_path)``  → list[sv.LineZone]       (count crossings)

Zones reuse the pixel polygons that are already part of the Phase 1 metadata
schema, so the same coordinates that define a queue_spillback zone in Phase 1
drive the vehicle counter in Phase 2 — no duplicate geometry to maintain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supervision as sv


@dataclass(frozen=True)
class NamedZone:
    name: str
    kind: str                  # 'queue_spillback' | 'approach_area' | ...
    zone: sv.PolygonZone


@dataclass(frozen=True)
class NamedLine:
    approach: str
    line: sv.LineZone


def _polygon(points: list[list[float]]) -> np.ndarray:
    return np.array(points, dtype=np.int32)


def load_zones(meta_path: Path) -> list[NamedZone]:
    with meta_path.open() as fh:
        meta = json.load(fh)
    out: list[NamedZone] = []
    for z in meta.get("monitoring_zones", []):
        poly = _polygon(z["polygon_px"])
        out.append(NamedZone(
            name=z["name"],
            kind=z["kind"],
            zone=sv.PolygonZone(polygon=poly),
        ))
    return out


def load_stop_lines(meta_path: Path) -> list[NamedLine]:
    with meta_path.open() as fh:
        meta = json.load(fh)
    out: list[NamedLine] = []
    for sl in meta.get("stop_lines", []):
        pts = sl["polyline_px"]
        # Use first and last polyline point as the counting line endpoints.
        p0, p1 = pts[0], pts[-1]
        out.append(NamedLine(
            approach=sl["approach"],
            line=sv.LineZone(
                start=sv.Point(float(p0[0]), float(p0[1])),
                end=sv.Point(float(p1[0]), float(p1[1])),
            ),
        ))
    return out
