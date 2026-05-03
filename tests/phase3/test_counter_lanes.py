"""Tests for per-lane state tracking in ApproachCounter (Phase 1.5)."""
from __future__ import annotations

import numpy as np
import pytest

from traffic_intel_phase3.poc_wadi_saqra.counters import (
    ApproachCounter,
    LaneZone,
    Zone,
)


def _approach_zone(approach: str, x0: int, y0: int, x1: int, y1: int) -> Zone:
    poly = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32)
    return Zone(approach=approach, label=approach, polygon=poly,
                stop_line=None, direction_of_travel="down")


def _lane_zone(approach: str, lane_id: str, lane_idx: int, lane_type: str,
               x0: int, y0: int, x1: int, y1: int) -> LaneZone:
    poly = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32)
    centerline = np.array([
        [(x0 + x1) / 2, y0], [(x0 + x1) / 2, y1]
    ], dtype=float)
    return LaneZone(
        approach=approach,
        lane_id=lane_id,
        lane_idx=lane_idx,
        lane_type=lane_type,
        polygon=poly,
        centerline=centerline,
    )


class TestSnapshotShape:
    def test_lanes_section_empty_without_lane_zones(self):
        counter = ApproachCounter([_approach_zone("S", 0, 0, 100, 100)])
        snap = counter.snapshot()
        assert snap["S"].get("lanes") == {}

    def test_lanes_section_present_with_lane_zones(self):
        zones = [_approach_zone("S", 0, 0, 300, 100)]
        lanes = [
            _lane_zone("S", "S-1", 0, "right", 0, 0, 100, 100),
            _lane_zone("S", "S-2", 1, "through", 100, 0, 200, 100),
            _lane_zone("S", "S-3", 2, "left", 200, 0, 300, 100),
        ]
        counter = ApproachCounter(zones, lane_zones=lanes)
        snap = counter.snapshot()
        assert set(snap["S"]["lanes"].keys()) == {"S-1", "S-2", "S-3"}
        for lane_id, row in snap["S"]["lanes"].items():
            assert {"in_zone", "in_zone_pce", "crossings_total",
                    "crossings_pce_total", "mix", "lane_type", "lane_idx"} <= set(row.keys())


class TestPerLaneCounting:
    def test_one_car_in_S1_only(self):
        zones = [_approach_zone("S", 0, 0, 300, 100)]
        lanes = [
            _lane_zone("S", "S-1", 0, "right", 0, 0, 100, 100),
            _lane_zone("S", "S-2", 1, "through", 100, 0, 200, 100),
            _lane_zone("S", "S-3", 2, "left", 200, 0, 300, 100),
        ]
        counter = ApproachCounter(zones, lane_zones=lanes)
        # Place one car at x=50 (S-1) and one bus at x=150 (S-2)
        counter.update([1, 2], [(50.0, 50.0), (150.0, 50.0)],
                       class_names=["car", "bus"])
        snap = counter.snapshot()
        s1 = snap["S"]["lanes"]["S-1"]
        s2 = snap["S"]["lanes"]["S-2"]
        s3 = snap["S"]["lanes"]["S-3"]
        assert s1["in_zone"] == 1
        assert s1["in_zone_pce"] == pytest.approx(1.0)
        assert s1["mix"] == {"car": 1}
        assert s2["in_zone"] == 1
        assert s2["in_zone_pce"] == pytest.approx(2.0)
        assert s2["mix"] == {"bus": 1}
        assert s3["in_zone"] == 0
        # Approach-level totals still work (sum across all lanes).
        assert snap["S"]["in_zone"] == 2
        assert snap["S"]["in_zone_pce"] == pytest.approx(3.0)


class TestBackwardCompat:
    def test_no_lane_zones_works_unchanged(self):
        counter = ApproachCounter([_approach_zone("S", 0, 0, 100, 100)])
        counter.update([1], [(50.0, 50.0)], class_names=["car"])
        snap = counter.snapshot()
        assert snap["S"]["in_zone"] == 1
        assert snap["S"]["in_zone_pce"] == pytest.approx(1.0)
        assert snap["S"]["lanes"] == {}
