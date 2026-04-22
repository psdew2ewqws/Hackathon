"""Build the feature matrix for ML forecasting.

Per-row features (one row per (detector, time-bin)):
    * lag_1   — count at t-15min  (1 bin back)
    * lag_2   — count at t-30min  (2 bins back)
    * lag_4   — count at t-1h     (4 bins back)
    * lag_96  — count at t-24h    (96 bins back, same time yesterday)
    * lag_672 — count at t-7d     (672 bins back, same time last week)
    * hour_sin / hour_cos          — cyclical hour-of-day
    * dow_sin  / dow_cos           — cyclical day-of-week (0=Mon … 6=Sun)
    * is_weekend                   — derived weekend flag
    * green_active_frac            — fraction of last bin where the
      approach's main phase was GREEN_ON (driven by signal log)

Targets (one column each):
    * y_15min — count at t (the row itself, i.e. predicting "now" given lags)
    * y_30min — count at t+1 bin
    * y_60min — count at t+3 bins

This shape lets us train a single model whose `predict()` for time T returns
predictions for T (now), T+15, T+30, T+60 all at once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


BIN_MIN = 15  # synth.detector_counts uses 15-min bins
BINS_PER_HOUR = 60 // BIN_MIN
BINS_PER_DAY = 24 * BINS_PER_HOUR
LAGS = [1, 2, 4, BINS_PER_DAY, BINS_PER_DAY * 7]  # 15min, 30min, 1h, 1d, 7d
HORIZONS_BINS = [0, 1, 2, 4]  # +0 (now), +15, +30, +60 min


@dataclass(frozen=True)
class FeatureBuild:
    train_X: pd.DataFrame
    train_y: pd.DataFrame   # multi-output: y_15min, y_30min, y_60min, y_now
    detector_index: pd.Series  # one row per training row → detector id (kept aligned)
    timestamps: pd.DatetimeIndex


def _read_counts(counts_dir: Path) -> pd.DataFrame:
    """Concatenate every counts_*.parquet into a single sorted dataframe."""
    files = sorted(counts_dir.glob("counts_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no counts_*.parquet under {counts_dir}")
    frames = []
    for f in files:
        df = pq.read_table(f).to_pandas()
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values(["detector_id", "timestamp"]).reset_index(drop=True)
    return out


def _read_signal_active(signal_dir: Path,
                         start: pd.Timestamp,
                         end: pd.Timestamp) -> pd.DataFrame:
    """Build a per-15-min mask of which NEMA phase was active most of the bin.

    Returns a tidy frame: index = bin start ts, columns = phase numbers
    {2, 4, 6, 8}, value = fraction of bin that phase was GREEN_ON.

    Vectorised: for each GREEN window (g0, g1) we locate the 1-2 bins it
    overlaps via searchsorted instead of scanning every bin.
    """
    files = sorted(signal_dir.glob("signal_*.ndjson"))
    if not files:
        return pd.DataFrame()
    rows: list[dict] = []
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append({"timestamp": ev["timestamp"],
                         "phase": ev["phase"],
                         "state": ev["state"]})
    if not rows:
        return pd.DataFrame()
    sig = pd.DataFrame(rows)
    sig["timestamp"] = pd.to_datetime(sig["timestamp"], utc=True)
    sig = sig.sort_values("timestamp").reset_index(drop=True)

    bin_starts = pd.date_range(start.floor("15min"),
                                end.ceil("15min"),
                                freq="15min", tz="UTC")[:-1]
    n_bins = len(bin_starts)
    bin_seconds = 15 * 60
    bin_ns = bin_starts.astype("int64").to_numpy()
    bin_step_ns = np.int64(15 * 60 * 1_000_000_000)
    out = {ph: np.zeros(n_bins, dtype=np.float64) for ph in (2, 4, 6, 8)}

    green_start: dict[int, pd.Timestamp | None] = {2: None, 4: None, 6: None, 8: None}
    for ev in sig.itertuples(index=False):
        ph = int(ev.phase)
        if ph not in green_start:
            continue
        if ev.state == "GREEN_ON":
            green_start[ph] = ev.timestamp
        elif ev.state in ("YELLOW_ON", "RED_ON") and green_start[ph] is not None:
            g0 = np.int64(green_start[ph].value)
            g1 = np.int64(ev.timestamp.value)
            green_start[ph] = None
            # First + last bin the green window touches
            i0 = int(np.searchsorted(bin_ns, g0, side="right")) - 1
            i1 = int(np.searchsorted(bin_ns, g1, side="right")) - 1
            i0 = max(i0, 0)
            i1 = min(i1, n_bins - 1)
            for i in range(i0, i1 + 1):
                b0 = bin_ns[i]
                b1 = b0 + bin_step_ns
                overlap_ns = min(g1, b1) - max(g0, b0)
                if overlap_ns > 0:
                    out[ph][i] += overlap_ns / 1_000_000_000
    return pd.DataFrame(
        {f"green_frac_phase_{ph}": np.clip(arr / bin_seconds, 0.0, 1.0).astype(np.float32)
         for ph, arr in out.items()},
        index=bin_starts,
    )


def build_features(counts_dir: Path = Path("data/detector_counts"),
                   signal_dir: Path = Path("data/signal_logs"),
                   ) -> FeatureBuild:
    """Assemble the full training matrix. Drops the first ``max(LAGS)`` rows
    per detector (no lags available)."""
    df = _read_counts(counts_dir)
    if df.empty:
        raise RuntimeError("no detector counts found")

    # Per-detector lag features
    df = df.sort_values(["detector_id", "timestamp"]).reset_index(drop=True)
    grp = df.groupby("detector_id", group_keys=False)
    for k in LAGS:
        df[f"lag_{k}"] = grp["vehicle_count"].shift(k)
    # Future targets per horizon
    for h in HORIZONS_BINS:
        col = "y_now" if h == 0 else f"y_{h*BIN_MIN}min"
        df[col] = grp["vehicle_count"].shift(-h) if h > 0 else df["vehicle_count"]

    # Calendar features
    df["hour"]  = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
    df["dow"]   = df["timestamp"].dt.dayofweek
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * df["dow"] / 7)
    df["is_weekend"] = (df["dow"] >= 5).astype(np.int8)

    # Approach → main phase mapping (matches forecast/optimize.py)
    appr_to_phase = {"N": 2, "S": 2, "E": 4, "W": 4}
    df["main_phase"] = df["approach"].map(appr_to_phase).astype("Int16")

    # Signal active fractions per bin
    sig = _read_signal_active(signal_dir,
                              df["timestamp"].min(),
                              df["timestamp"].max())
    if not sig.empty:
        sig = sig.reset_index().rename(columns={"index": "timestamp"})
        df = df.merge(sig, on="timestamp", how="left")
        # Per-row "green_active_frac" = fraction of bin where the row's main_phase was green
        df["green_active_frac"] = 0.0
        for ph in (2, 4, 6, 8):
            col = f"green_frac_phase_{ph}"
            mask = df["main_phase"] == ph
            df.loc[mask, "green_active_frac"] = df.loc[mask, col].fillna(0.0)
    else:
        df["green_active_frac"] = 0.0

    # Drop rows missing any lag or future target
    feat_cols = [f"lag_{k}" for k in LAGS]
    target_cols = ["y_now"] + [f"y_{h*BIN_MIN}min" for h in HORIZONS_BINS if h > 0]
    df_clean = df.dropna(subset=feat_cols + target_cols).reset_index(drop=True)

    # Detector identity → integer code (LightGBM categorical)
    df_clean["detector_code"] = df_clean["detector_id"].astype("category").cat.codes

    feature_cols = (
        feat_cols
        + ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend",
           "green_active_frac", "detector_code"]
    )
    return FeatureBuild(
        train_X=df_clean[feature_cols].copy(),
        train_y=df_clean[target_cols].copy(),
        detector_index=df_clean["detector_id"].copy(),
        timestamps=pd.DatetimeIndex(df_clean["timestamp"]),
    )


def feature_columns() -> list[str]:
    """Used by predict.py to assemble a single-row feature vector at inference."""
    return [f"lag_{k}" for k in LAGS] + [
        "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend",
        "green_active_frac", "detector_code",
    ]


def target_columns() -> list[str]:
    return ["y_now"] + [f"y_{h*BIN_MIN}min" for h in HORIZONS_BINS if h > 0]
