"""Unit tests for the traffic profile shape module."""

from __future__ import annotations

import numpy as np
import pytest

from traffic_intel_sandbox.synth.profiles import (
    ProfileConfig,
    detector_day_counts,
    per_minute_rates,
)


def test_profiles_load(profiles_yml):
    cfg = ProfileConfig.load(profiles_yml)
    assert cfg.baseline_rate > 0
    assert len(cfg.peaks) >= 1
    assert len(cfg.detectors) == 22, "handbook §6.3 calls for 22 detectors"


def test_rates_length_and_nonneg(profiles_yml):
    cfg = ProfileConfig.load(profiles_yml)
    rates = per_minute_rates(cfg, is_weekend=False)
    assert rates.shape == (1440,)
    assert (rates >= 0).all()


def test_weekend_below_weekday(profiles_yml):
    cfg = ProfileConfig.load(profiles_yml)
    wk = per_minute_rates(cfg, is_weekend=False).sum()
    we = per_minute_rates(cfg, is_weekend=True).sum()
    assert we < wk


@pytest.mark.parametrize("seed", [0, 7, 123])
def test_counts_deterministic(profiles_yml, seed):
    cfg = ProfileConfig.load(profiles_yml)
    det = cfg.detectors[0]
    a = detector_day_counts(cfg, det, is_weekend=False, rng=np.random.default_rng(seed))
    b = detector_day_counts(cfg, det, is_weekend=False, rng=np.random.default_rng(seed))
    assert np.array_equal(a, b)
    assert a.shape == (96,)
    assert (a >= 0).all()
