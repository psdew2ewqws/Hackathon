"""Zone membership + stop-line crossing for tracked vehicle centroids."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import json
import numpy as np


# HCM 6th-edition Passenger Car Equivalents (urban arterial). Each tracked
# vehicle's count contribution is scaled by its PCE so a bus weighs more
# than a motorcycle in pressure / queue / crossing aggregates. Unknown
# class names fall back to 1.0 (treated as a passenger car).
PCE_TABLE: dict[str, float] = {
    "car": 1.0,
    "motorcycle": 0.4,
    "bicycle": 0.4,
    "bus": 2.0,
    "truck": 1.5,
}


def pce_for(class_name: str | None) -> float:
    """Return the PCE weight for a class name (case-insensitive, safe on None)."""
    if not class_name:
        return 1.0
    return PCE_TABLE.get(class_name.lower(), 1.0)


@dataclass
class Zone:
    approach: str
    label: str
    polygon: np.ndarray            # (N,2) int32 — REFERENCE-frame coords
    stop_line: tuple[tuple[int, int], tuple[int, int]] | None
    direction_of_travel: str       # "up" | "down" | "left" | "right"
    # Runtime polygon — set per-frame by the tracker after the camera
    # homography is applied so the polygon stays glued to road features
    # even when the camera drifts. When None, point-in-polygon falls back
    # to the static `polygon` field. Populated only by the live tracker.
    runtime_polygon: np.ndarray | None = None
    runtime_stop_line: tuple[tuple[int, int], tuple[int, int]] | None = None


@dataclass
class ApproachState:
    approach: str
    current_ids: set[int] = field(default_factory=set)
    crossed_ids: set[int] = field(default_factory=set)
    crossings_total: int = 0
    # Class-aware aggregates (filled when ApproachCounter.update is called
    # with class_names; otherwise behave as if everything were a car).
    current_pce: float = 0.0
    crossings_pce_total: float = 0.0
    mix: dict[str, int] = field(default_factory=dict)


@dataclass
class LaneZone:
    """One induced/configured lane sub-polygon within an approach (Phase 1.5).

    Created either by the trajectory induction algorithm
    (`lanes.induce_lanes_from_trajectories`) or by the operator via the
    calibration UI. Persisted under each approach's `lanes:` array in
    wadi_saqra_zones.json.

    `polygon` and `centerline` are stored in REFERENCE-frame pixel coords.
    The live tracker sets `runtime_polygon` / `runtime_centerline` per
    frame after applying the camera-motion homography so the lane stays
    glued to road features as the camera drifts.
    """
    approach: str
    lane_id: str
    lane_idx: int
    lane_type: str             # 'left' | 'through' | 'right' | 'shared'
    polygon: np.ndarray        # (M, 2) int32, REFERENCE-frame
    centerline: np.ndarray     # (N, 2) float, REFERENCE-frame
    runtime_polygon: np.ndarray | None = None
    runtime_centerline: np.ndarray | None = None


@dataclass
class LaneState:
    """Per-lane analog of ApproachState (Phase 1.5)."""
    lane_id: str
    lane_idx: int
    lane_type: str
    current_ids: set[int] = field(default_factory=set)
    current_pce: float = 0.0
    crossings_total: int = 0
    crossings_pce_total: float = 0.0
    mix: dict[str, int] = field(default_factory=dict)


def load_zones(path: Path) -> list[Zone]:
    data = json.loads(Path(path).read_text())
    out: list[Zone] = []
    for z in data["zones"]:
        sl = z.get("stop_line")
        out.append(Zone(
            approach=z["approach"],
            label=z.get("label", z["approach"]),
            polygon=np.array(z["polygon"], dtype=np.int32),
            stop_line=(tuple(sl[0]), tuple(sl[1])) if sl else None,
            direction_of_travel=z.get("direction_of_travel", "up"),
        ))
    return out


def load_lane_zones(path: Path) -> list[LaneZone]:
    """Read per-approach lane sub-polygons from the zones config.

    Phase 1.5 schema additive: each top-level zone may carry an optional
    ``lanes: [{lane_id, lane_idx, lane_type, polygon, centerline}, ...]``.
    Returns an empty list when no zones declare lanes — callers should treat
    that as "operate at approach granularity only" (legacy behavior).
    """
    data = json.loads(Path(path).read_text())
    out: list[LaneZone] = []
    for z in data.get("zones", []):
        approach = z["approach"]
        for ln in (z.get("lanes") or []):
            poly = np.array(ln["polygon"], dtype=np.int32)
            centerline = np.array(ln.get("centerline") or [], dtype=float)
            if centerline.ndim != 2 or centerline.shape[1] != 2:
                centerline = np.zeros((0, 2), dtype=float)
            out.append(LaneZone(
                approach=approach,
                lane_id=ln["lane_id"],
                lane_idx=int(ln.get("lane_idx", 0)),
                lane_type=ln.get("lane_type", "shared"),
                polygon=poly,
                centerline=centerline,
            ))
    return out


def point_in_polygon(point: tuple[float, float], polygon: np.ndarray) -> bool:
    x, y = point
    pts = polygon
    n = len(pts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]; xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _ccw(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(p1, p2, q1, q2) -> bool:
    """Do segment p1p2 and q1q2 intersect (strictly, ignoring collinear)."""
    d1 = _ccw(q1, q2, p1)
    d2 = _ccw(q1, q2, p2)
    d3 = _ccw(p1, p2, q1)
    d4 = _ccw(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def crossed_in_direction(prev_xy, curr_xy, stop_line, direction: str) -> bool:
    """True iff a track segment crosses the stop line going in the expected direction."""
    if prev_xy is None or stop_line is None:
        return False
    if not segments_cross(prev_xy, curr_xy, stop_line[0], stop_line[1]):
        return False
    dx = curr_xy[0] - prev_xy[0]
    dy = curr_xy[1] - prev_xy[1]
    if direction == "up":    return dy < 0
    if direction == "down":  return dy > 0
    if direction == "left":  return dx < 0
    if direction == "right": return dx > 0
    return True


class ApproachCounter:
    """Maintains per-approach presence + stop-line crossing counts across frames.

    PCE-aware: when ``update`` is called with a ``class_names`` list, each
    vehicle contributes its HCM Passenger Car Equivalent to ``in_zone_pce``
    and ``crossings_pce_total`` aggregates, plus a ``mix`` dict of
    per-class counts currently in zone. Callers that omit ``class_names``
    get the legacy behavior (every vehicle counts as one car).
    """

    def __init__(
        self,
        zones: Iterable[Zone],
        lane_zones: Iterable[LaneZone] | None = None,
    ) -> None:
        self.zones = list(zones)
        self.state: dict[str, ApproachState] = {z.approach: ApproachState(z.approach) for z in self.zones}
        # Per-approach LaneZone list + per-(approach,lane_id) LaneState.
        self.lane_zones: dict[str, list[LaneZone]] = {z.approach: [] for z in self.zones}
        self.lane_state: dict[str, dict[str, LaneState]] = {z.approach: {} for z in self.zones}
        for lz in (lane_zones or []):
            self.lane_zones.setdefault(lz.approach, []).append(lz)
            self.lane_state.setdefault(lz.approach, {})[lz.lane_id] = LaneState(
                lane_id=lz.lane_id, lane_idx=lz.lane_idx, lane_type=lz.lane_type,
            )
        self._last_xy: dict[int, tuple[float, float]] = {}
        self._track_approach: dict[int, str | None] = {}
        self._track_class: dict[int, str] = {}
        self._track_pce: dict[int, float] = {}
        self._track_lane: dict[int, str] = {}  # tid -> "{approach}:{lane_id}"

    def reset_crossings(self) -> None:
        for s in self.state.values():
            s.crossed_ids.clear()
            s.crossings_total = 0
            s.crossings_pce_total = 0.0
        for lanes in self.lane_state.values():
            for ls in lanes.values():
                ls.crossings_total = 0
                ls.crossings_pce_total = 0.0

    def reset_all(self) -> None:
        """Wipe both crossing accumulators and per-track memory.

        Called when the upstream tracker is reset (e.g. detector swap), so
        new track IDs from a fresh ByteTrack don't collide with stale
        positions from the previous detector and trigger phantom crossings.
        """
        self.reset_crossings()
        for s in self.state.values():
            s.current_ids.clear()
            s.current_pce = 0.0
            s.mix.clear()
        for lanes in self.lane_state.values():
            for ls in lanes.values():
                ls.current_ids.clear()
                ls.current_pce = 0.0
                ls.mix.clear()
        self._last_xy.clear()
        self._track_approach.clear()
        self._track_class.clear()
        self._track_pce.clear()
        self._track_lane.clear()

    def update(
        self,
        track_ids: list[int],
        centroids: list[tuple[float, float]],
        class_names: list[str] | None = None,
    ) -> None:
        # Wipe per-frame presence sets — they describe *this* frame only.
        for s in self.state.values():
            s.current_ids.clear()
            s.current_pce = 0.0
            s.mix = {}
        for lanes in self.lane_state.values():
            for ls in lanes.values():
                ls.current_ids.clear()
                ls.current_pce = 0.0
                ls.mix = {}

        if class_names is None:
            class_names = ["car"] * len(track_ids)

        live_ids = set(int(t) for t in track_ids)
        for tid, xy, cls_raw in zip(track_ids, centroids, class_names):
            cls = (cls_raw or "car").lower()
            pce = pce_for(cls)
            self._track_class[tid] = cls
            self._track_pce[tid] = pce

            prev = self._last_xy.get(tid)
            first_approach: str | None = None
            for zone in self.zones:
                # Use the per-frame warped polygon when the live tracker
                # has set one (homography-tracked); otherwise fall back to
                # the static reference polygon (tests, headless mode).
                zpoly = zone.runtime_polygon if zone.runtime_polygon is not None else zone.polygon
                if point_in_polygon(xy, zpoly):
                    if first_approach is None:
                        first_approach = zone.approach
                    s = self.state[zone.approach]
                    s.current_ids.add(tid)
                    s.current_pce += pce
                    s.mix[cls] = s.mix.get(cls, 0) + 1
                    # Per-lane: which lane (if any) within this approach
                    # contains the centroid?
                    for lz in self.lane_zones.get(zone.approach, []):
                        lpoly = lz.runtime_polygon if lz.runtime_polygon is not None else lz.polygon
                        if point_in_polygon(xy, lpoly):
                            ls = self.lane_state[zone.approach][lz.lane_id]
                            ls.current_ids.add(tid)
                            ls.current_pce += pce
                            ls.mix[cls] = ls.mix.get(cls, 0) + 1
                            self._track_lane[tid] = f"{zone.approach}:{lz.lane_id}"
                            break
                stop_line = zone.runtime_stop_line if zone.runtime_stop_line is not None else zone.stop_line
                if stop_line is not None and tid not in self.state[zone.approach].crossed_ids:
                    if crossed_in_direction(prev, xy, stop_line, zone.direction_of_travel):
                        s = self.state[zone.approach]
                        s.crossed_ids.add(tid)
                        s.crossings_total += 1
                        s.crossings_pce_total += pce
                        # Attribute the crossing to whichever lane the
                        # vehicle was last seen in (best-effort: the
                        # most-recent _track_lane mapping).
                        last_lane = self._track_lane.get(tid)
                        if last_lane and last_lane.startswith(f"{zone.approach}:"):
                            lane_id = last_lane.split(":", 1)[1]
                            ls = self.lane_state[zone.approach].get(lane_id)
                            if ls is not None:
                                ls.crossings_total += 1
                                ls.crossings_pce_total += pce
            self._last_xy[tid] = xy
            self._track_approach[tid] = first_approach
        # Forget approach for tracks that vanished this frame.
        for tid in list(self._track_approach.keys()):
            if tid not in live_ids:
                self._track_approach.pop(tid, None)
                self._track_class.pop(tid, None)
                self._track_pce.pop(tid, None)
                self._track_lane.pop(tid, None)

    def approach_map(self) -> dict[int, str | None]:
        return dict(self._track_approach)

    def direction_map(self) -> dict[str, str]:
        return {z.approach: z.direction_of_travel for z in self.zones}

    def snapshot(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for a, s in self.state.items():
            lanes_dump: dict[str, dict] = {}
            for lane_id, ls in self.lane_state.get(a, {}).items():
                lanes_dump[lane_id] = {
                    "lane_id": ls.lane_id,
                    "lane_idx": ls.lane_idx,
                    "lane_type": ls.lane_type,
                    "in_zone": len(ls.current_ids),
                    "in_zone_pce": round(ls.current_pce, 2),
                    "crossings_total": ls.crossings_total,
                    "crossings_pce_total": round(ls.crossings_pce_total, 2),
                    "mix": dict(ls.mix),
                }
            out[a] = {
                "in_zone": len(s.current_ids),
                "crossings_total": s.crossings_total,
                "in_zone_pce": round(s.current_pce, 2),
                "crossings_pce_total": round(s.crossings_pce_total, 2),
                "mix": dict(s.mix),
                "lanes": lanes_dump,
            }
        return out
