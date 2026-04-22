"""Zone membership + stop-line crossing for tracked vehicle centroids."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import json
import numpy as np


@dataclass
class Zone:
    approach: str
    label: str
    polygon: np.ndarray            # (N,2) int32
    stop_line: tuple[tuple[int, int], tuple[int, int]] | None
    direction_of_travel: str       # "up" | "down" | "left" | "right"


@dataclass
class ApproachState:
    approach: str
    current_ids: set[int] = field(default_factory=set)
    crossed_ids: set[int] = field(default_factory=set)
    crossings_total: int = 0


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
    """Maintains per-approach presence + stop-line crossing counts across frames."""

    def __init__(self, zones: Iterable[Zone]) -> None:
        self.zones = list(zones)
        self.state: dict[str, ApproachState] = {z.approach: ApproachState(z.approach) for z in self.zones}
        self._last_xy: dict[int, tuple[float, float]] = {}
        self._track_approach: dict[int, str | None] = {}

    def reset_crossings(self) -> None:
        for s in self.state.values():
            s.crossed_ids.clear()
            s.crossings_total = 0

    def update(self, track_ids: list[int], centroids: list[tuple[float, float]]) -> None:
        # Wipe per-frame presence sets (they describe *this* frame only).
        for s in self.state.values():
            s.current_ids.clear()

        live_ids = set(int(t) for t in track_ids)
        for tid, xy in zip(track_ids, centroids):
            prev = self._last_xy.get(tid)
            first_approach: str | None = None
            for zone in self.zones:
                if point_in_polygon(xy, zone.polygon):
                    if first_approach is None:
                        first_approach = zone.approach
                    self.state[zone.approach].current_ids.add(tid)
                if zone.stop_line is not None and tid not in self.state[zone.approach].crossed_ids:
                    if crossed_in_direction(prev, xy, zone.stop_line, zone.direction_of_travel):
                        self.state[zone.approach].crossed_ids.add(tid)
                        self.state[zone.approach].crossings_total += 1
            self._last_xy[tid] = xy
            self._track_approach[tid] = first_approach
        # Forget approach for tracks that vanished this frame.
        for tid in list(self._track_approach.keys()):
            if tid not in live_ids:
                self._track_approach.pop(tid, None)

    def approach_map(self) -> dict[int, str | None]:
        return dict(self._track_approach)

    def direction_map(self) -> dict[str, str]:
        return {z.approach: z.direction_of_travel for z in self.zones}

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            a: {
                "in_zone": len(s.current_ids),
                "crossings_total": s.crossings_total,
            }
            for a, s in self.state.items()
        }
