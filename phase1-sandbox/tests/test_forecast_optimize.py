"""Unit tests for forecast.optimize — Webster + HCM math.

Reference fixture: a simplified worked example in the spirit of HCM
Example 18-B (6th ed.). We use round-numbers that make the math easy to
verify by hand:

    Demand (veh/hr):  N=600, S=600, E=400, W=400
    Lanes per appr:   3 (all approaches, all through — matches our model)
    Saturation:       s = 1800 veh/hr/lane
    => y_NS = 600 / (1800 * 3) = 0.1111
       y_EW = 400 / (1800 * 3) = 0.0741
       Y    = 0.1852
       L    = 20 s
       C_opt = (1.5 * 20 + 5) / (1 - 0.1852) = 42.9 s
              → clamped to C_min = 60 s
"""

from __future__ import annotations

import math

import pytest

from traffic_intel_sandbox.forecast.optimize import (
    ApproachInput,
    C_MIN,
    C_MAX,
    DEFAULT_GREEN_S,
    LOST_TIME_TOTAL,
    MAX_GREEN,
    MIN_GREEN,
    S_PER_LANE,
    critical_y,
    evaluate,
    flow_ratio,
    hcm_uniform_delay,
    recommend,
    recommendation,
    signal_color,
    webster_cycle,
    webster_split,
)


# ─── Core Webster math ───────────────────────────────────────────────────
def test_flow_ratio_formula():
    # y = v / (s · n)
    assert flow_ratio(1800, 1) == pytest.approx(1.0)
    assert flow_ratio(900, 2) == pytest.approx(0.25)
    assert flow_ratio(0, 3) == 0.0
    assert flow_ratio(500, 0) == 0.0   # no lanes → 0


def test_webster_cycle_clamps_to_min_when_Y_tiny():
    # Y = 0.1852 → formula gives ~43 s → clamp up to 60 s (C_MIN)
    assert webster_cycle(0.1852) == C_MIN


def test_webster_cycle_clamps_to_max_when_oversaturated():
    # Y ≥ 1 → division-by-zero guard, clamp to C_MAX
    assert webster_cycle(1.0) == C_MAX
    assert webster_cycle(1.5) == C_MAX


def test_webster_cycle_matches_formula_in_mid_range():
    # Pick Y that yields a cycle squarely in [60, 120] so no clamping
    # Y = 0.75 → C = (1.5 × 20 + 5) / (1 − 0.75) = 140 → clamp to 120
    assert webster_cycle(0.75) == C_MAX
    # Y = 0.60 → C = 35 / 0.40 = 87.5 → rounds to 88
    assert webster_cycle(0.60) == pytest.approx(88, abs=1)
    # Y = 0.65 → C = 35 / 0.35 = 100
    assert webster_cycle(0.65) == pytest.approx(100, abs=1)


def test_critical_y_takes_max_of_opposing_approaches():
    # N/S and E/W each contribute max of their pair
    inputs = {
        "N": ApproachInput("N", 600, 3),   # y = 0.1111
        "S": ApproachInput("S", 300, 3),   # y = 0.0556 → masked
        "E": ApproachInput("E", 400, 3),   # y = 0.0741
        "W": ApproachInput("W", 900, 3),   # y = 0.1667 → wins EW
    }
    Y = critical_y(inputs)
    assert Y == pytest.approx(0.1111 + 0.1667, abs=1e-3)


def test_webster_split_respects_min_and_max_green():
    # Skewed demand: N very high, others near zero
    inputs = {
        "N": ApproachInput("N", 2000, 3),
        "S": ApproachInput("S", 2000, 3),
        "E": ApproachInput("E", 10,   3),
        "W": ApproachInput("W", 10,   3),
    }
    g = webster_split(inputs, cycle_s=100)
    for phase_num, green in g.items():
        assert MIN_GREEN <= green <= MAX_GREEN, \
            f"phase {phase_num} green {green} outside [{MIN_GREEN},{MAX_GREEN}]"


def test_webster_split_totals_equal_cycle_minus_lost_time():
    inputs = {
        "N": ApproachInput("N", 600, 3),
        "S": ApproachInput("S", 600, 3),
        "E": ApproachInput("E", 400, 3),
        "W": ApproachInput("W", 400, 3),
    }
    cycle = 100
    g = webster_split(inputs, cycle_s=cycle)
    assert sum(g.values()) == cycle - LOST_TIME_TOTAL


# ─── HCM delay ────────────────────────────────────────────────────────────
def test_hcm_delay_returns_zero_for_zero_green_or_cycle():
    assert hcm_uniform_delay(0, 10, 0.5) == 0.0
    assert hcm_uniform_delay(100, 0, 0.5) == 0.0


def test_hcm_delay_is_monotone_in_x():
    # Holding cycle + green fixed, delay should increase with X
    C, g = 100.0, 30.0
    delays = [hcm_uniform_delay(C, g, x) for x in (0.2, 0.5, 0.8, 0.95)]
    assert all(a < b for a, b in zip(delays, delays[1:])), \
        f"delay not monotone in X: {delays}"


def test_hcm_delay_grows_near_saturation():
    # At X = 0.99, delay should be meaningfully larger than at X = 0.5
    # (uniform delay alone is mild near sat'n — the full HCM has a d2 overflow
    # term we deliberately skip for POC; growth here is ~20%, not 2×).
    C, g = 100.0, 30.0
    d_low = hcm_uniform_delay(C, g, 0.5)
    d_hi  = hcm_uniform_delay(C, g, 0.99)
    assert d_hi > d_low


def test_hcm_delay_bounded_on_oversaturation():
    # The formula clamps X_eff to min(1, X), so oversaturated demand does
    # not blow up — it returns a finite, capacity-constrained value.
    d = hcm_uniform_delay(100, 50, 3.0)
    assert 0 < d < 9999.0


# ─── Signal colour bands ─────────────────────────────────────────────────
def test_signal_color_bands():
    assert signal_color(0.5) == "green"
    assert signal_color(0.84) == "green"
    assert signal_color(0.85) == "yellow"
    assert signal_color(0.99) == "yellow"
    assert signal_color(1.00) == "red"
    assert signal_color(1.5) == "red"


# ─── §8.3 recommendation rules ───────────────────────────────────────────
def test_recommendation_extend_on_high_x():
    r = recommendation(x=0.95, green_s=20, cycle_s=100, cycle_saturated=False)
    assert "Extend green" in r


def test_recommendation_reduce_on_low_x():
    r = recommendation(x=0.3, green_s=40, cycle_s=100, cycle_saturated=False)
    assert "Reduce green" in r


def test_recommendation_cycle_when_saturated_and_x_exceeds_1():
    r = recommendation(x=1.2, green_s=25, cycle_s=100, cycle_saturated=True)
    assert "cycle" in r.lower()


def test_recommendation_within_range_says_no_change():
    r = recommendation(x=0.7, green_s=30, cycle_s=100, cycle_saturated=False)
    assert "no change" in r.lower()


# ─── End-to-end evaluate / recommend ─────────────────────────────────────
def test_evaluate_produces_one_row_per_approach_phase_mapping():
    inputs = {
        "N": ApproachInput("N", 600, 3),
        "S": ApproachInput("S", 600, 3),
        "E": ApproachInput("E", 400, 3),
        "W": ApproachInput("W", 400, 3),
    }
    res = evaluate(inputs, DEFAULT_GREEN_S)
    # 4 approaches × 2 phases each (through + left) = 8 rows
    assert len(res.rows) == 8
    # Every approach should appear in the rows
    approaches = {r.approach for r in res.rows}
    assert approaches == {"N", "S", "E", "W"}


def test_recommend_returns_valid_cycle_and_split():
    inputs = {
        "N": ApproachInput("N", 800, 3),
        "S": ApproachInput("S", 800, 3),
        "E": ApproachInput("E", 500, 3),
        "W": ApproachInput("W", 500, 3),
    }
    cycle, split = recommend(inputs)
    assert C_MIN <= cycle <= C_MAX
    assert sum(split.values()) + LOST_TIME_TOTAL == cycle
    for ph in (2, 4, 6, 8):
        assert ph in split
        assert MIN_GREEN <= split[ph] <= MAX_GREEN


def test_recommend_delay_not_worse_than_naive_plan():
    """A Webster-optimized split should not produce higher weighted delay
    than an arbitrary wildly-unbalanced split for typical demand."""
    inputs = {
        "N": ApproachInput("N", 900, 3),
        "S": ApproachInput("S", 900, 3),
        "E": ApproachInput("E", 300, 3),
        "W": ApproachInput("W", 300, 3),
    }
    # Arbitrary bad split: all phases equal
    bad_split = {2: 20, 4: 20, 6: 20, 8: 20}
    bad = evaluate(inputs, bad_split)
    # Webster split
    cycle, good_split = recommend(inputs)
    good = evaluate(inputs, good_split, cycle_s=cycle)
    assert good.summary["weighted_avg_delay_s"] <= bad.summary["weighted_avg_delay_s"] + 0.5, \
        f"Webster delay {good.summary['weighted_avg_delay_s']}s > bad {bad.summary['weighted_avg_delay_s']}s"
