"""Tests for trajectory-driven lane induction.

Phase 1.5 of the production-readiness plan. Lane geometry is *induced*
from the per-vehicle trajectories that ByteTrack already produces, not
from painted-paint detection — dashcam-trained ML lane detectors are a
poor fit for our oblique stationary-camera view (per the GitHub
research). The clustering algorithm:

  1. Bucket trajectories by which approach polygon they entered from.
  2. Within each approach, compute pairwise discrete Fréchet distance
     between arc-length-resampled trajectories.
  3. Cluster with DBSCAN (precomputed metric).
  4. Per cluster, compute medial-line centerline + ±lane_width/2 polygon.
  5. Infer lane_type from exit angle relative to entry angle.
"""
from __future__ import annotations

import numpy as np
import pytest

from traffic_intel_phase3.poc_wadi_saqra.lanes import (
    LaneSpec,
    discrete_frechet,
    induce_lanes_from_trajectories,
    infer_lane_type,
    resample_trajectory,
)


# ---- discrete Fréchet distance ----

class TestDiscreteFrechet:
    def test_identical_paths(self):
        a = np.array([[0, 0], [1, 0], [2, 0]], dtype=float)
        assert discrete_frechet(a, a) == pytest.approx(0.0)

    def test_translated_paths(self):
        a = np.array([[0, 0], [1, 0], [2, 0]], dtype=float)
        b = a + np.array([0.0, 5.0])
        assert discrete_frechet(a, b) == pytest.approx(5.0)

    def test_orthogonal_paths(self):
        a = np.array([[0, 0], [1, 0], [2, 0]], dtype=float)
        b = np.array([[0, 0], [0, 1], [0, 2]], dtype=float)
        # Worst pair is the two end points: (2,0)<->(0,2) ⇒ distance ≈ 2.83
        assert discrete_frechet(a, b) == pytest.approx(2 * np.sqrt(2), abs=0.01)


# ---- arc-length resample ----

class TestResample:
    def test_returns_n_points(self):
        track = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], dtype=float)
        out = resample_trajectory(track, n=5)
        assert out.shape == (5, 2)

    def test_endpoints_preserved(self):
        track = np.array([[0, 0], [10, 5], [30, 10]], dtype=float)
        out = resample_trajectory(track, n=8)
        assert out[0] == pytest.approx(track[0])
        assert out[-1] == pytest.approx(track[-1])


# ---- lane-type inference ----

class TestInferLaneType:
    def test_through_lane_small_angle(self):
        # Straight north→south: entry direction (0,1), exit (0,1) ⇒ angle ≈ 0
        track = np.array([[100, 0], [100, 50], [100, 100]], dtype=float)
        assert infer_lane_type(track) == "through"

    def test_south_to_east_is_left_turn(self):
        # Driver enters going south on screen (+y), exits going east (+x).
        # In real-world terms south→east is a LEFT turn from the driver's POV.
        track = np.array([
            [100, 0], [100, 30], [100, 60],     # straight south
            [110, 80], [140, 90], [180, 95],    # curving east (driver turning left)
        ], dtype=float)
        assert infer_lane_type(track) == "left"

    def test_south_to_west_is_right_turn(self):
        # Driver enters going south (+y), exits going west (-x).
        # south→west is a RIGHT turn from the driver's POV.
        track = np.array([
            [100, 0], [100, 30], [100, 60],
            [90, 80], [60, 90], [20, 95],
        ], dtype=float)
        assert infer_lane_type(track) == "right"


# ---- end-to-end induction ----

def _square_zone(approach: str, x0: int, y0: int, x1: int, y1: int):
    """Build a simple square approach polygon."""
    from traffic_intel_phase3.poc_wadi_saqra.counters import Zone
    poly = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.int32)
    return Zone(approach=approach, label=approach, polygon=poly,
                stop_line=None, direction_of_travel="down")


def _line_track(start, end, n=20, jitter=2.0, rng=None):
    """A noisy straight-line trajectory."""
    rng = rng or np.random.default_rng(0)
    t = np.linspace(0, 1, n)[:, None]
    base = (1 - t) * np.array(start) + t * np.array(end)
    noise = rng.normal(0, jitter, size=base.shape)
    return base + noise


class TestInduceLanes:
    def test_three_distinct_lanes_clusters_to_three(self):
        # Approach S sits at top-half of the synthetic frame; tracks enter
        # from y<200 and head down to y>400. Three distinct lateral
        # corridors at x=200, x=280, x=360 → should cluster to 3 lanes.
        rng = np.random.default_rng(42)
        zone = _square_zone("S", 100, 0, 500, 500)
        tracks = []
        for x_center in (200, 280, 360):
            for _ in range(15):
                tracks.append({
                    "tid": len(tracks),
                    "approach": "S",
                    "centroids": _line_track(
                        (x_center, 50), (x_center, 450), n=20, rng=rng
                    ),
                })
        result = induce_lanes_from_trajectories(
            tracks, [zone], min_samples=5
        )
        lanes_S = result.get("S", [])
        assert len(lanes_S) == 3, f"Expected 3 lane clusters, got {len(lanes_S)}"
        # All three should be classified "through" (no significant turn)
        assert all(L.lane_type == "through" for L in lanes_S)
        # lane_idx assigned in order
        assert sorted(L.lane_idx for L in lanes_S) == [0, 1, 2]

    def test_through_and_turn_lanes_separate(self):
        # Two clusters in approach S: one straight through, one curving
        # off to the west (right turn from a south-bound driver's POV).
        rng = np.random.default_rng(7)
        zone = _square_zone("S", 0, 0, 500, 500)
        tracks = []
        for _ in range(15):
            tracks.append({
                "tid": len(tracks),
                "approach": "S",
                "centroids": _line_track((250, 50), (250, 450), n=20, rng=rng),
            })
        for _ in range(15):
            # Driver enters at (250, 50) going south, curves to exit at
            # (50, 250) going west → right turn (south→west).
            t = np.linspace(0, 1, 20)[:, None]
            base = np.column_stack([
                250 - 200 * t.flatten() ** 2,
                50 + 200 * t.flatten(),
            ])
            tracks.append({
                "tid": len(tracks),
                "approach": "S",
                "centroids": base + rng.normal(0, 2, size=base.shape),
            })
        result = induce_lanes_from_trajectories(tracks, [zone], min_samples=5)
        lanes_S = result.get("S", [])
        assert len(lanes_S) == 2
        types = sorted(L.lane_type for L in lanes_S)
        assert types == ["right", "through"]

    def test_lanespec_polygon_shape(self):
        rng = np.random.default_rng(0)
        zone = _square_zone("S", 0, 0, 500, 500)
        tracks = [{
            "tid": i,
            "approach": "S",
            "centroids": _line_track((250, 50), (250, 450), n=20, rng=rng),
        } for i in range(10)]
        result = induce_lanes_from_trajectories(tracks, [zone], min_samples=5)
        lanes_S = result["S"]
        assert len(lanes_S) >= 1
        ls = lanes_S[0]
        assert isinstance(ls, LaneSpec)
        # Polygon must be closed (first==last not required, but at least 4 pts)
        assert ls.polygon.shape[0] >= 4
        assert ls.polygon.shape[1] == 2
        assert ls.centerline.shape[1] == 2
        assert ls.lane_id.startswith("S-")
