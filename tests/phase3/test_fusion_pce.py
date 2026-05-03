"""Tests for the PCE-aware fuse() in poc_wadi_saqra.fusion.

Phase 1 of the production-readiness plan: fuse() now reads PCE-weighted
inputs (in_zone_pce, crossings_pce_in_bin, mix) from the upstream counter
snapshot and computes pressure in PCE-units instead of raw vehicles.
Backward compat: if PCE keys are missing, fall back to the raw counts so
old call sites keep working unchanged.
"""
from __future__ import annotations

import pytest

from traffic_intel_phase3.poc_wadi_saqra.fusion import (
    classify_pressure,
    fuse,
)


# ---- input shape ----

def _row(in_zone=0, crossings=0, in_zone_pce=None, pce_in_bin=None, mix=None):
    """Build the per-approach input dict that fuse() expects."""
    out = {"in_zone": in_zone, "crossings_in_bin": crossings}
    if in_zone_pce is not None:
        out["in_zone_pce"] = in_zone_pce
    if pce_in_bin is not None:
        out["crossings_pce_in_bin"] = pce_in_bin
    if mix is not None:
        out["mix"] = mix
    return out


# ---- new keys appear in fused output ----

class TestFusedShape:
    def test_pce_keys_present(self):
        fused = fuse(
            {"S": _row(in_zone=4, crossings=2, in_zone_pce=4.0, pce_in_bin=2.0, mix={"car": 4})},
            bin_seconds=15,
            gmaps_rows={},
        )
        row = fused["S"]
        assert "pce_demand_per_min" in row
        assert "in_zone_pce" in row
        assert "mix" in row
        assert row["mix"] == {"car": 4}


# ---- pressure formula now uses PCE units ----

class TestPressureUsesPce:
    def test_two_buses_outpressure_two_cars(self):
        cars = fuse(
            {"S": _row(in_zone=2, crossings=0, in_zone_pce=2.0, pce_in_bin=0.0, mix={"car": 2})},
            bin_seconds=15, gmaps_rows={},
        )["S"]
        buses = fuse(
            {"S": _row(in_zone=2, crossings=0, in_zone_pce=4.0, pce_in_bin=0.0, mix={"bus": 2})},
            bin_seconds=15, gmaps_rows={},
        )["S"]
        assert buses["pressure"] > cars["pressure"]
        # Expected: 0.5 * 2.0 = 1.0 for cars, 0.5 * 4.0 = 2.0 for buses.
        assert cars["pressure"] == pytest.approx(1.0)
        assert buses["pressure"] == pytest.approx(2.0)

    def test_pce_demand_uses_pce_crossings_not_raw(self):
        # 1 truck crossed in 15s = 1.5 PCE-veh / 0.25 min = 6.0 PCE/min
        row = fuse(
            {"S": _row(in_zone=0, crossings=1, in_zone_pce=0.0, pce_in_bin=1.5, mix={})},
            bin_seconds=15, gmaps_rows={},
        )["S"]
        assert row["pce_demand_per_min"] == pytest.approx(6.0)
        # And pressure equals the demand (queue contribution is 0).
        assert row["pressure"] == pytest.approx(6.0)


# ---- backward compatibility ----

class TestBackwardCompat:
    """Old call sites without PCE keys still produce sensible output."""

    def test_no_pce_keys_falls_back_to_raw(self):
        row = fuse(
            {"S": {"in_zone": 4, "crossings_in_bin": 2}},
            bin_seconds=15, gmaps_rows={},
        )["S"]
        # Pressure formula with all-PCE-1.0 fallback equals the legacy formula.
        # legacy: 2 * 60/15 + 0.5 * 4 * 1 = 8 + 2 = 10
        assert row["pressure"] == pytest.approx(10.0)
        # Both views are populated for downstream consumers.
        assert row["in_zone"] == 4
        assert row["in_zone_pce"] == pytest.approx(4.0)
        assert row["crossings_in_bin"] == 2


# ---- pressure classification thresholds unchanged ----

class TestThresholdsUnchanged:
    """The classify_pressure() thresholds keep their numeric values; the
    semantics shift from 'vehicles' to 'PCE-units' but the label boundary
    stays where it was so old dashboards don't suddenly flip color."""

    def test_low_pce_is_free(self):
        assert classify_pressure(1.5) == "free"

    def test_high_pce_is_jam(self):
        assert classify_pressure(20.0) == "jam"
