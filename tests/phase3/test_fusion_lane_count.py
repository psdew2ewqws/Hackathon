"""Tests for measured-lane-count threading into Webster (Phase 1.5)."""
from __future__ import annotations

from traffic_intel_phase3.poc_wadi_saqra.fusion import (
    webster_three_phase,
    webster_two_phase,
)


def _row(in_zone, in_zone_pce, crossings_in_bin, pce_in_bin):
    return {
        "in_zone": in_zone,
        "in_zone_pce": in_zone_pce,
        "crossings_in_bin": crossings_in_bin,
        "crossings_pce_in_bin": pce_in_bin,
    }


def _busy_fused():
    """All four approaches loaded — guarantees Y > 0 so the formula is exercised."""
    return {
        "S": _row(in_zone=4, in_zone_pce=4.0, crossings_in_bin=2, pce_in_bin=2.0),
        "N": _row(in_zone=4, in_zone_pce=4.0, crossings_in_bin=2, pce_in_bin=2.0),
        "E": _row(in_zone=4, in_zone_pce=4.0, crossings_in_bin=2, pce_in_bin=2.0),
        "W": _row(in_zone=4, in_zone_pce=4.0, crossings_in_bin=2, pce_in_bin=2.0),
    }


class TestLaneCountsTwoPhase:
    def test_more_lanes_lowers_cycle(self):
        from traffic_intel_phase3.poc_wadi_saqra.fusion import fuse
        # Apply fuse so demand_per_min populates (Webster reads it)
        fused = fuse(_busy_fused(), bin_seconds=15, gmaps_rows={})
        rec_one = webster_two_phase(fused, lane_count=1)
        rec_three = webster_two_phase(fused, lane_count=3)
        # More lanes ⇒ higher capacity ⇒ lower flow ratio ⇒ shorter cycle
        # (or at least not longer).
        assert rec_three["cycle_seconds"] <= rec_one["cycle_seconds"]

    def test_per_approach_lane_counts_changes_phase_split(self):
        from traffic_intel_phase3.poc_wadi_saqra.fusion import fuse
        fused = fuse(_busy_fused(), bin_seconds=15, gmaps_rows={})
        rec_uniform = webster_two_phase(fused, lane_count=2)
        # Tell Webster NS has 4 lanes per arm but EW only has 1 — the
        # NS phase y goes down, the EW phase y goes up, and the cycle
        # adapts. The phases section must reflect different flow ratios
        # vs. the uniform case.
        rec_per_approach = webster_two_phase(
            fused, lane_counts={"N": 4, "S": 4, "E": 1, "W": 1}, lane_count=2,
        )
        u_ns = rec_uniform["phases"]["NS"]["flow_ratio"]
        u_ew = rec_uniform["phases"]["EW"]["flow_ratio"]
        p_ns = rec_per_approach["phases"]["NS"]["flow_ratio"]
        p_ew = rec_per_approach["phases"]["EW"]["flow_ratio"]
        assert p_ns < u_ns, "NS y should drop when NS has more lanes"
        assert p_ew > u_ew, "EW y should rise when EW has fewer lanes"


class TestLaneCountsThreePhase:
    def test_per_approach_threading_through(self):
        from traffic_intel_phase3.poc_wadi_saqra.fusion import fuse
        fused = fuse(_busy_fused(), bin_seconds=15, gmaps_rows={})
        rec_default = webster_three_phase(fused, lane_count=2)
        # Boosting E to 6 lanes drops y_E sharply; rec must reflect the
        # change at the per-phase flow_ratio level.
        rec_more_e = webster_three_phase(
            fused, lane_counts={"N": 2, "S": 2, "E": 6, "W": 2}, lane_count=2,
        )
        e_default = rec_default["phases"]["E"]["flow_ratio"]
        e_more = rec_more_e["phases"]["E"]["flow_ratio"]
        assert e_more < e_default, "E flow ratio must drop when E gets more lanes"


class TestBackwardCompat:
    def test_lane_counts_omitted_uses_legacy_int(self):
        from traffic_intel_phase3.poc_wadi_saqra.fusion import fuse
        fused = fuse(_busy_fused(), bin_seconds=15, gmaps_rows={})
        # Should not raise; should produce the same result as before.
        rec = webster_two_phase(fused, lane_count=2)
        assert rec["cycle_seconds"] > 0
        assert "phases" in rec
