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
    polygon: np.ndarray = None  # type: ignore  # original pixel polygon, shape (N,2)


@dataclass(frozen=True)
class NamedLine:
    approach: str
    line: sv.LineZone


@dataclass(frozen=True)
class NamedLaneLine:
    """One LineZone per lane segment — subdivides each approach's stop-line
    polyline into equal pieces, one per lane defined in site metadata."""
    approach:  str
    lane_id:   str            # e.g. "N-1", "E-3"
    lane_type: str            # 'right' | 'through' | 'left' | 'shared'
    lane_idx:  int            # 0-based index along the polyline
    line:      sv.LineZone


@dataclass(frozen=True)
class NamedLaneZone:
    """Per-lane rectangular sub-zone, sliced out of a queue_spillback polygon.
    Used for live in-frame heat-maps: current count inside the sub-polygon
    drives a colour (green→yellow→red) drawn on the annotated frame."""
    approach:  str
    lane_id:   str
    lane_type: str
    lane_idx:  int
    polygon:   np.ndarray       # shape (4, 2), int32
    zone:      sv.PolygonZone


def _polygon(points: list[list[float]]) -> np.ndarray:
    return np.array(points, dtype=np.int32)


def load_lane_zones(meta_path: Path) -> list[NamedLaneZone]:
    """Slice each ``queue_spillback_*`` polygon into ``n_lanes`` sub-rectangles
    by the axis perpendicular to traffic flow. N/S approaches split the bbox
    along x (lanes side-by-side horizontally); E/W approaches split along y.

    This intentionally uses the axis-aligned bounding box of each polygon
    rather than a true perspective-correct subdivision. It's good enough when
    ``queue_spillback_*`` is already a rectangle (our default), and it makes
    the math trivial. For camera-perspective-accurate lane strips, we'd need
    a homography (future work)."""
    with meta_path.open() as fh:
        meta = json.load(fh)
    approaches_by_name = {
        a["name"]: a for a in meta.get("approaches", [])
    }
    out: list[NamedLaneZone] = []
    for z in meta.get("monitoring_zones", []):
        if z.get("kind") != "queue_spillback":
            continue
        name = z.get("name", "")
        if not name.startswith("queue_spillback_"):
            continue
        approach = name.split("_")[-1]
        appr = approaches_by_name.get(approach)
        if not appr:
            continue
        lanes = appr.get("lanes", [])
        if not lanes:
            continue
        poly = np.array(z["polygon_px"], dtype=np.float32)
        x_min, y_min = poly[:, 0].min(), poly[:, 1].min()
        x_max, y_max = poly[:, 0].max(), poly[:, 1].max()
        # N/S approaches: horizontal road → lanes stacked along x
        # E/W approaches: vertical road → lanes stacked along y
        split_x = approach in ("N", "S")
        n = len(lanes)
        for i, lane in enumerate(lanes):
            t0, t1 = i / n, (i + 1) / n
            if split_x:
                a0 = x_min + t0 * (x_max - x_min)
                a1 = x_min + t1 * (x_max - x_min)
                sub = np.array([
                    [a0, y_min], [a1, y_min], [a1, y_max], [a0, y_max],
                ], dtype=np.int32)
            else:
                a0 = y_min + t0 * (y_max - y_min)
                a1 = y_min + t1 * (y_max - y_min)
                sub = np.array([
                    [x_min, a0], [x_max, a0], [x_max, a1], [x_min, a1],
                ], dtype=np.int32)
            out.append(NamedLaneZone(
                approach=approach,
                lane_id=lane["id"],
                lane_type=lane["type"],
                lane_idx=i,
                polygon=sub,
                zone=sv.PolygonZone(polygon=sub),
            ))
    return out


def load_lane_lines(meta_path: Path) -> list[NamedLaneLine]:
    """Return per-lane LineZone segments by subdividing each approach's
    stop-line polyline. Lanes come from ``meta["approaches"][].lanes`` — the
    polyline is divided into ``len(lanes)`` equal segments, one per lane."""
    with meta_path.open() as fh:
        meta = json.load(fh)
    lanes_by_approach = {
        a["name"]: a.get("lanes", []) for a in meta.get("approaches", [])
    }
    out: list[NamedLaneLine] = []
    for sl in meta.get("stop_lines", []):
        approach = sl["approach"]
        pts = sl["polyline_px"]
        p0, p1 = pts[0], pts[-1]
        lanes = lanes_by_approach.get(approach, [])
        if not lanes:
            continue
        n = len(lanes)
        for i, lane in enumerate(lanes):
            t0 = i / n
            t1 = (i + 1) / n
            sx = p0[0] + t0 * (p1[0] - p0[0])
            sy = p0[1] + t0 * (p1[1] - p0[1])
            ex = p0[0] + t1 * (p1[0] - p0[0])
            ey = p0[1] + t1 * (p1[1] - p0[1])
            out.append(NamedLaneLine(
                approach=approach,
                lane_id=lane["id"],
                lane_type=lane["type"],
                lane_idx=i,
                line=sv.LineZone(
                    start=sv.Point(float(sx), float(sy)),
                    end=sv.Point(float(ex), float(ey)),
                ),
            ))
    return out


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
            polygon=poly,
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
