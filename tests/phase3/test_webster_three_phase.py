"""3-phase Webster recommender (§7.5).

Verifies the HCM y-formula and the near-saturation guard (no negative
delay reductions ever surface).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def plan():
    return {"NS_green": 35, "E_green": 35, "W_green": 35, "yellow": 3, "all_red": 2}


def test_three_phase_emits_ns_e_w_keys(plan):
    from traffic_intel_phase3.poc_wadi_saqra.fusion import webster_three_phase
    fused = {
        "S": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "N": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "E": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "W": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
    }
    out = webster_three_phase(fused, current_plan=plan)
    assert out["mode"] == "three_phase"
    assert set(out["phases"].keys()) == {"NS", "E", "W"}


def test_idle_intersection_recommends_shorter_cycle(plan):
    """Idle traffic → Webster should suggest a shorter cycle than the 120s field plan."""
    from traffic_intel_phase3.poc_wadi_saqra.fusion import webster_three_phase
    fused = {
        "S": {"in_zone": 1, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "N": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "E": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
        "W": {"in_zone": 0, "crossings_in_bin": 0, "demand_per_min": 0.0},
    }
    out = webster_three_phase(fused, current_plan=plan)
    cmp = out["comparison"]
    assert cmp["recommended"]["cycle_seconds"] < cmp["current"]["cycle_seconds"]
    assert cmp["delay_reduction_pct"] is not None
    assert cmp["delay_reduction_pct"] > 0


def test_near_saturation_guard_never_returns_negative(plan):
    """Heavy demand on NS should either produce a gain or hit the guard — never a negative %."""
    from traffic_intel_phase3.poc_wadi_saqra.fusion import webster_three_phase
    fused = {
        "S": {"in_zone": 2, "crossings_in_bin": 8, "demand_per_min": 32.0},
        "N": {"in_zone": 1, "crossings_in_bin": 4, "demand_per_min": 16.0},
        "E": {"in_zone": 0, "crossings_in_bin": 2, "demand_per_min": 8.0},
        "W": {"in_zone": 0, "crossings_in_bin": 3, "demand_per_min": 12.0},
    }
    out = webster_three_phase(fused, current_plan=plan)
    cmp = out["comparison"]
    # Either positive improvement, or near_saturation branch returning the
    # field plan with 0.0 % delta.
    assert cmp["delay_reduction_pct"] is not None
    assert cmp["delay_reduction_pct"] >= 0.0


def test_flow_ratio_total_bounded(plan):
    """Y (flow_ratio_total) is the sum of the three phase y-values, each ≤ 0.95."""
    from traffic_intel_phase3.poc_wadi_saqra.fusion import webster_three_phase
    fused = {
        "S": {"in_zone": 10, "crossings_in_bin": 20, "demand_per_min": 80.0},
        "N": {"in_zone": 10, "crossings_in_bin": 20, "demand_per_min": 80.0},
        "E": {"in_zone": 10, "crossings_in_bin": 20, "demand_per_min": 80.0},
        "W": {"in_zone": 10, "crossings_in_bin": 20, "demand_per_min": 80.0},
    }
    out = webster_three_phase(fused, current_plan=plan)
    assert out["flow_ratio_total"] <= 3 * 0.95 + 1e-6
    for ph in ("NS", "E", "W"):
        assert out["phases"][ph]["flow_ratio"] <= 0.95 + 1e-6
        assert out["phases"][ph]["flow_ratio"] >= 0.02 - 1e-6
