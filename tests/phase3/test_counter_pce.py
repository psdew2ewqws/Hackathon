"""Tests for PCE-aware counting in ApproachCounter.

Phase 1 of the production-readiness plan. Counts must be class-aware:
each vehicle contributes its HCM 6th-edition Passenger Car Equivalent
(car=1.0, motorcycle=0.4, bus=2.0, truck=1.5) to in_zone_pce and
crossings_pce_total. Backward compat: callers that omit class_names get
the old all-cars-equally behavior so existing tests still pass.
"""
from __future__ import annotations

import numpy as np
import pytest

from traffic_intel_phase3.poc_wadi_saqra.counters import (
    ApproachCounter,
    Zone,
    pce_for,
)


def _square_zone(approach: str, x0: int, y0: int, x1: int, y1: int) -> Zone:
    poly = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32)
    # Stop line along the bottom edge of the zone, vehicles travel "up"
    return Zone(
        approach=approach,
        label=approach,
        polygon=poly,
        stop_line=((x0, y1), (x1, y1)),
        direction_of_travel="up",
    )


# ---- pce_for() ----

class TestPceFor:
    def test_known_classes(self):
        assert pce_for("car") == 1.0
        assert pce_for("motorcycle") == 0.4
        assert pce_for("bus") == 2.0
        assert pce_for("truck") == 1.5

    def test_case_insensitive(self):
        assert pce_for("CAR") == 1.0
        assert pce_for("Bus") == 2.0

    def test_unknown_falls_back_to_car(self):
        assert pce_for("unicorn") == 1.0
        assert pce_for("") == 1.0

    def test_none_falls_back_to_car(self):
        assert pce_for(None) == 1.0


# ---- snapshot() new fields ----

class TestSnapshotShape:
    def test_snapshot_includes_pce_and_mix_keys(self):
        counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])
        snap = counter.snapshot()
        assert set(snap["S"].keys()) >= {
            "in_zone", "crossings_total",
            "in_zone_pce", "crossings_pce_total", "mix",
        }
        # Empty counter starts at zero
        assert snap["S"]["in_zone"] == 0
        assert snap["S"]["in_zone_pce"] == 0.0
        assert snap["S"]["crossings_pce_total"] == 0.0
        assert snap["S"]["mix"] == {}


# ---- update() with class_names ----

class TestPceAccumulation:
    def setup_method(self):
        self.counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])

    def test_one_car_in_zone(self):
        self.counter.update([1], [(50.0, 50.0)], class_names=["car"])
        snap = self.counter.snapshot()
        assert snap["S"]["in_zone"] == 1
        assert snap["S"]["in_zone_pce"] == pytest.approx(1.0)
        assert snap["S"]["mix"] == {"car": 1}

    def test_one_bus_weighs_more_than_one_car(self):
        self.counter.update([1], [(50.0, 50.0)], class_names=["bus"])
        snap = self.counter.snapshot()
        assert snap["S"]["in_zone"] == 1
        assert snap["S"]["in_zone_pce"] == pytest.approx(2.0)
        assert snap["S"]["mix"] == {"bus": 1}

    def test_mixed_classes_sum_correctly(self):
        # 2 cars + 1 truck + 1 motorcycle = 1.0 + 1.0 + 1.5 + 0.4 = 3.9 PCE
        self.counter.update(
            [1, 2, 3, 4],
            [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0), (40.0, 40.0)],
            class_names=["car", "car", "truck", "motorcycle"],
        )
        snap = self.counter.snapshot()
        assert snap["S"]["in_zone"] == 4
        assert snap["S"]["in_zone_pce"] == pytest.approx(3.9)
        assert snap["S"]["mix"] == {"car": 2, "truck": 1, "motorcycle": 1}

    def test_in_zone_pce_resets_when_vehicles_leave(self):
        self.counter.update([1, 2], [(10.0, 10.0), (20.0, 20.0)], class_names=["bus", "car"])
        # Same tids next frame, but moved outside the zone
        self.counter.update([1, 2], [(500.0, 500.0), (600.0, 600.0)], class_names=["bus", "car"])
        snap = self.counter.snapshot()
        assert snap["S"]["in_zone"] == 0
        assert snap["S"]["in_zone_pce"] == 0.0
        assert snap["S"]["mix"] == {}


# ---- crossings + PCE ----

class TestCrossingsPce:
    def setup_method(self):
        # Zone at top half of frame; stop line at the bottom edge of the
        # polygon. Vehicles travel "up" (decreasing y), so a track moving
        # from y=110 (below) to y=90 (inside) crosses the stop line going up.
        self.counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])

    def _move_through(self, tid: int, cls: str) -> None:
        # Two-frame motion that crosses the stop line at y=100 going up.
        self.counter.update([tid], [(50.0, 110.0)], class_names=[cls])
        self.counter.update([tid], [(50.0, 90.0)], class_names=[cls])

    def test_one_car_crossing_adds_1_pce(self):
        self._move_through(1, "car")
        snap = self.counter.snapshot()
        assert snap["S"]["crossings_total"] == 1
        assert snap["S"]["crossings_pce_total"] == pytest.approx(1.0)

    def test_one_bus_crossing_adds_2_pce(self):
        self._move_through(1, "bus")
        snap = self.counter.snapshot()
        assert snap["S"]["crossings_total"] == 1
        assert snap["S"]["crossings_pce_total"] == pytest.approx(2.0)

    def test_three_mixed_crossings_sum(self):
        self._move_through(1, "car")        # 1.0
        self._move_through(2, "truck")      # 1.5
        self._move_through(3, "motorcycle") # 0.4
        snap = self.counter.snapshot()
        assert snap["S"]["crossings_total"] == 3
        assert snap["S"]["crossings_pce_total"] == pytest.approx(2.9)


# ---- backward compatibility ----

class TestBackwardCompat:
    """Existing call sites that pass only (track_ids, centroids) must still work."""

    def test_update_without_class_names_treats_all_as_cars(self):
        counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])
        counter.update([1, 2], [(10.0, 10.0), (20.0, 20.0)])
        snap = counter.snapshot()
        assert snap["S"]["in_zone"] == 2
        assert snap["S"]["in_zone_pce"] == pytest.approx(2.0)  # both default to PCE=1.0
        assert snap["S"]["mix"] == {"car": 2}


# ---- reset behavior ----

class TestResetClearsPceState:
    def test_reset_all_clears_pce_and_mix(self):
        counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])
        counter.update([1, 2], [(10.0, 10.0), (20.0, 20.0)], class_names=["bus", "truck"])
        counter.reset_all()
        snap = counter.snapshot()
        assert snap["S"]["in_zone_pce"] == 0.0
        assert snap["S"]["crossings_pce_total"] == 0.0
        assert snap["S"]["mix"] == {}

    def test_reset_crossings_clears_crossings_pce(self):
        counter = ApproachCounter([_square_zone("S", 0, 0, 100, 100)])
        counter.update([1], [(50.0, 110.0)], class_names=["bus"])
        counter.update([1], [(50.0, 90.0)], class_names=["bus"])
        snap = counter.snapshot()
        assert snap["S"]["crossings_pce_total"] == pytest.approx(2.0)
        counter.reset_crossings()
        snap = counter.snapshot()
        assert snap["S"]["crossings_pce_total"] == 0.0
