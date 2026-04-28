"""Video-anchored signal simulator (§6.4, Phase-2).

Verifies the 3-phase cycle (NS → E → W) derived from video_ts lines up
exactly with the user-supplied anchor and walks every boundary correctly.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def plan():
    from traffic_intel_phase3.poc_wadi_saqra.signal_sim import CurrentPlan
    return CurrentPlan(
        NS_green=35, EW_green=35, E_green=35, W_green=35,
        yellow=3, all_red=2,
    )


@pytest.fixture
def anchor():
    from traffic_intel_phase3.poc_wadi_saqra.signal_sim import VideoAnchor
    return VideoAnchor(
        video_ts_seconds=23.0,
        phase_name="E",
        signal_state="GREEN ON",
        duration_seconds=314.933,
        ffmpeg_start_path=Path("/tmp/nonexistent-ffstart.txt"),
    )


def test_cycle_length_is_120s(plan):
    assert plan.cycle_seconds_3phase == pytest.approx(120.0)


@pytest.mark.parametrize(
    "offset_in_cycle, expected",
    [
        (0.0,     ("E",  "GREEN ON")),
        (34.99,   ("E",  "GREEN ON")),
        (35.0,    ("E",  "YELLOW ON")),
        (37.99,   ("E",  "YELLOW ON")),
        (38.0,    ("E",  "RED ON")),
        (40.0,    ("W",  "GREEN ON")),
        (74.99,   ("W",  "GREEN ON")),
        (75.0,    ("W",  "YELLOW ON")),
        (78.0,    ("W",  "RED ON")),
        (80.0,    ("NS", "GREEN ON")),
        (114.99,  ("NS", "GREEN ON")),
        (115.0,   ("NS", "YELLOW ON")),
        (118.0,   ("NS", "RED ON")),
        (120.0,   ("E",  "GREEN ON")),   # wrap
        (240.0,   ("E",  "GREEN ON")),   # wrap x2
    ],
)
def test_phase_at_offset_walks_3phase_cycle(plan, anchor, offset_in_cycle, expected):
    from traffic_intel_phase3.poc_wadi_saqra.signal_sim import _phase_at_offset
    _phn, name, state, _appr, _dur, _elapsed = _phase_at_offset(plan, anchor, offset_in_cycle)
    assert (name, state) == expected


def test_unknown_anchor_raises(plan):
    """Guard against the silent NS-fallback bug we hit when phase_name was 'EW'."""
    from traffic_intel_phase3.poc_wadi_saqra.signal_sim import VideoAnchor, _phase_at_offset
    bad = VideoAnchor(
        video_ts_seconds=23.0,
        phase_name="EW",    # not present in 3-phase sequence
        signal_state="GREEN ON",
        duration_seconds=314.0,
        ffmpeg_start_path=Path("/tmp/x"),
    )
    with pytest.raises(ValueError):
        _phase_at_offset(plan, bad, 10.0)


def test_anchor_start_is_offset_zero(plan, anchor):
    """At offset=0 we are exactly at the start of the anchor phase."""
    from traffic_intel_phase3.poc_wadi_saqra.signal_sim import _phase_at_offset
    _, name, state, approaches, dur, elapsed = _phase_at_offset(plan, anchor, 0.0)
    assert name == "E"
    assert state == "GREEN ON"
    assert tuple(approaches) == ("E",)
    assert dur == pytest.approx(35.0)
    assert elapsed == pytest.approx(0.0)
