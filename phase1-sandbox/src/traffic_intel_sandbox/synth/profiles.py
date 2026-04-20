"""C7 — Traffic demand profile shapes.

Given a YAML spec, returns per-minute expected arrival rates for one detector,
which the counts generator integrates into 15-minute bins.

Profiles combine three independent sources of structure:

    1. *Base diurnal shape* — a mixture of Gaussians for AM / midday / PM peaks.
    2. *Day-of-week multiplier* — weekday vs weekend scaling.
    3. *Per-detector offset* — baseline volume per detector (e.g. a major-approach
       through-lane gets 5× a minor-approach left-turn lane).

Randomness is controlled by a seed passed from the caller; same seed → same
parquet, which is essential for the reproducibility claim in methodology.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

MIN_PER_DAY = 24 * 60


@dataclass(frozen=True)
class PeakSpec:
    name: str
    center_min: int    # minutes after midnight
    width_min: float   # gaussian sigma
    amplitude: float   # peak rate (veh/min at center)


@dataclass(frozen=True)
class DetectorSpec:
    id: str
    approach: str        # N/S/E/W
    lane: int            # 1-based
    lane_type: str       # through / left / right / shared / bus / bike
    base_multiplier: float  # scales all peaks + background


@dataclass(frozen=True)
class ProfileConfig:
    baseline_rate: float       # off-peak background (veh/min)
    peaks: tuple[PeakSpec, ...]
    weekday_multiplier: float
    weekend_multiplier: float
    noise_pct: float           # gaussian noise as % of rate (0.1 = 10%)
    detectors: tuple[DetectorSpec, ...]

    @staticmethod
    def load(path: Path) -> "ProfileConfig":
        with path.open() as fh:
            raw = yaml.safe_load(fh)
        peaks = tuple(PeakSpec(**p) for p in raw["peaks"])
        detectors = tuple(DetectorSpec(**d) for d in raw["detectors"])
        return ProfileConfig(
            baseline_rate=float(raw["baseline_rate"]),
            peaks=peaks,
            weekday_multiplier=float(raw["weekday_multiplier"]),
            weekend_multiplier=float(raw["weekend_multiplier"]),
            noise_pct=float(raw["noise_pct"]),
            detectors=detectors,
        )


def _diurnal_rate(cfg: ProfileConfig, minute: int) -> float:
    """Expected arrival rate (veh/min) at a given minute of day, pre-noise."""
    r = cfg.baseline_rate
    for p in cfg.peaks:
        r += p.amplitude * math.exp(-0.5 * ((minute - p.center_min) / p.width_min) ** 2)
    return r


def per_minute_rates(cfg: ProfileConfig, is_weekend: bool) -> np.ndarray:
    """Return a length-1440 array of expected veh/min rates for one day."""
    multiplier = cfg.weekend_multiplier if is_weekend else cfg.weekday_multiplier
    return np.array(
        [_diurnal_rate(cfg, m) * multiplier for m in range(MIN_PER_DAY)],
        dtype=np.float64,
    )


def detector_day_counts(
    cfg: ProfileConfig,
    detector: DetectorSpec,
    is_weekend: bool,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate 96 (15-min) counts for one detector on one day.

    Uses a Poisson draw per minute and gaussian noise on top, summed into 15-min
    bins. Output is integer vehicle count; occupancy_pct is derived downstream.
    """
    rates = per_minute_rates(cfg, is_weekend) * detector.base_multiplier
    noise = rng.normal(loc=1.0, scale=cfg.noise_pct, size=rates.shape).clip(min=0.1)
    rates = rates * noise
    per_min = rng.poisson(rates).astype(np.int64)
    # 1440 minutes → 96 × 15-min bins
    return per_min.reshape(96, 15).sum(axis=1).astype(np.int32)


def occupancy_from_count(count: int, lane_type: str) -> float:
    """Heuristic % occupancy for a 15-min bin given a vehicle count.

    Occupancy = fraction of time a detector is 'on'. At saturated flow we assume
    ~30% occupancy over the 15-minute window. This is intentionally simple —
    synthetic data is not expected to be physically accurate, just plausible.
    """
    saturation_count = {"through": 450, "shared": 400, "left": 250, "right": 300,
                        "bus": 120, "bike": 120}.get(lane_type, 350)
    return float(min(30.0 * count / max(saturation_count, 1), 95.0))
