"""Tests for the TrajectoryBuffer ring + closed-track NDJSON sink."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from traffic_intel_phase3.poc_wadi_saqra.trajectory_buffer import (
    TrajectoryBuffer,
)


def test_open_track_accumulates_centroids():
    buf = TrajectoryBuffer(max_age_s=600)
    buf.update(now=100.0, track_ids=[1], centroids=[(10.0, 20.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    buf.update(now=100.1, track_ids=[1], centroids=[(11.0, 21.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    open_tracks = buf.open_trajectories()
    assert 1 in open_tracks
    assert len(open_tracks[1]["centroids"]) == 2
    assert open_tracks[1]["approach"] == "S"
    assert open_tracks[1]["class_name"] == "car"


def test_track_closes_after_idle(tmp_path: Path):
    sink_path = tmp_path / "trajectories.ndjson"
    buf = TrajectoryBuffer(max_age_s=600, sink_path=sink_path,
                           close_after_idle_s=2.0)
    buf.update(now=100.0, track_ids=[1], centroids=[(10.0, 20.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    buf.update(now=100.5, track_ids=[1], centroids=[(11.0, 21.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    # Track 1 disappears for 3s — should close and write to sink
    buf.update(now=103.6, track_ids=[2], centroids=[(50.0, 50.0)],
               approach_map={2: "N"}, class_map={2: "bus"})
    closed = sink_path.read_text().strip().splitlines()
    assert len(closed) == 1
    rec = json.loads(closed[0])
    assert rec["tid"] == 1
    assert rec["approach"] == "S"
    assert rec["class_name"] == "car"
    assert len(rec["centroids"]) == 2


def test_recent_trajectories_window():
    buf = TrajectoryBuffer(max_age_s=10)
    buf.update(now=100.0, track_ids=[1], centroids=[(0.0, 0.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    buf.update(now=200.0, track_ids=[2], centroids=[(0.0, 0.0)],
               approach_map={2: "N"}, class_map={2: "car"})
    # First track should have aged out
    recent = buf.recent_closed_trajectories()
    # No closed tracks because both still alive at t=200; but the open
    # tracks dict should not include track 1 anymore (it was idle 100s).
    open_tracks = buf.open_trajectories()
    assert 2 in open_tracks
    assert 1 not in open_tracks
    _ = recent  # not used in this assertion


def test_recent_closed_trajectories_returns_only_recent(tmp_path: Path):
    sink_path = tmp_path / "trajectories.ndjson"
    buf = TrajectoryBuffer(max_age_s=600, sink_path=sink_path,
                           close_after_idle_s=1.0)
    # Old closed track
    buf.update(now=100.0, track_ids=[1], centroids=[(0.0, 0.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    buf.update(now=100.5, track_ids=[1], centroids=[(1.0, 1.0)],
               approach_map={1: "S"}, class_map={1: "car"})
    buf.update(now=200.0, track_ids=[2], centroids=[(0.0, 0.0)],
               approach_map={2: "N"}, class_map={2: "car"})  # closes 1
    # Recent closed track
    buf.update(now=200.5, track_ids=[2], centroids=[(1.0, 1.0)],
               approach_map={2: "N"}, class_map={2: "car"})
    buf.update(now=300.0, track_ids=[3], centroids=[(5.0, 5.0)],
               approach_map={3: "E"}, class_map={3: "car"})  # closes 2
    # Window from now=305 looking back 50s should only return tid 2
    recent = buf.recent_closed_trajectories(now=305.0, window_s=50.0)
    assert {r["tid"] for r in recent} == {2}
