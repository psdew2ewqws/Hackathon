"""Inference for the LightGBM forecast model (production path).

Loads `models/forecast_lgb.json` (multi-output bundle), assembles the latest
feature row per detector by reading the most-recent rows from
`data/detector_counts/*.parquet`, and returns predicted vehicle counts at
+0/+15/+30/+60 min for every detector.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .features import (
    BIN_MIN,
    BINS_PER_DAY,
    LAGS,
    feature_columns,
    target_columns,
)


def _load_lgb(bundle_path: Path):
    import lightgbm as lgb
    raw = json.loads(bundle_path.read_text())
    feat_cols = json.loads(raw["feature_cols"])
    models = {col: lgb.Booster(model_str=raw[col])
              for col in target_columns()}
    return feat_cols, models


def _read_history(counts_dir: Path) -> pd.DataFrame:
    """Read all detector counts and return as one sorted dataframe."""
    files = sorted(counts_dir.glob("counts_*.parquet"))
    frames = [pq.read_table(f).to_pandas() for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values(["detector_id", "timestamp"]).reset_index(drop=True)


def _build_inference_row(df: pd.DataFrame, target_ts: pd.Timestamp,
                          detector_codes: dict[str, int]) -> pd.DataFrame:
    """For each detector, build one inference row representing the state
    at ``target_ts``. Lag features come from the prior bins of that detector;
    calendar features come from target_ts itself."""
    rows = []
    for det_id, group in df.groupby("detector_id"):
        # Find the row whose timestamp equals target_ts (or the closest prior)
        prior = group[group["timestamp"] <= target_ts]
        if prior.empty:
            continue
        prior = prior.tail(max(LAGS) + 1)
        # last-row's count = lag_1's input (the bin before target_ts)
        # We treat target_ts as "now"; lag_k is k bins before now
        counts = prior["vehicle_count"].to_numpy()
        if len(counts) < max(LAGS) + 1:
            # Not enough history; fall back to median
            med = float(np.median(counts)) if len(counts) else 0.0
            counts = np.full(max(LAGS) + 1, med, dtype=np.float32)
        row = {f"lag_{k}": float(counts[-k - 1]) for k in LAGS}
        h = target_ts.hour + target_ts.minute / 60
        d = target_ts.dayofweek
        row.update({
            "hour_sin":         float(np.sin(2 * np.pi * h / 24)),
            "hour_cos":         float(np.cos(2 * np.pi * h / 24)),
            "dow_sin":          float(np.sin(2 * np.pi * d / 7)),
            "dow_cos":          float(np.cos(2 * np.pi * d / 7)),
            "is_weekend":       int(d >= 5),
            "green_active_frac": 0.5,    # neutral default at inference
            "detector_code":    detector_codes.get(det_id, 0),
            "_detector_id":     det_id,
            "_approach":        prior.iloc[-1]["approach"],
        })
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def predict_at(target_ts: pd.Timestamp,
               counts_dir: Path = Path("data/detector_counts"),
               lgb_bundle: Path = Path("models/forecast_lgb.json"),
               ) -> dict:
    """Return {detector_id: {y_now, y_15min, y_30min, y_60min, approach}}
    for every detector with enough history at target_ts."""
    if not lgb_bundle.exists():
        return {"available": False,
                "message": f"model file {lgb_bundle} not found — run make forecast-ml-train"}
    feat_cols, models = _load_lgb(lgb_bundle)
    df = _read_history(counts_dir)
    detector_codes = {d: i for i, d in enumerate(sorted(df["detector_id"].unique()))}
    inf = _build_inference_row(df, target_ts, detector_codes)
    if inf.empty:
        return {"available": False,
                "message": "no detector history available"}

    X = inf[feat_cols]
    out: dict[str, dict] = {}
    pred_by_col = {col: m.predict(X) for col, m in models.items()}
    for i, row in inf.iterrows():
        det = row["_detector_id"]
        out[det] = {
            "approach": row["_approach"],
            **{col: float(max(0.0, pred_by_col[col][i])) for col in models},
        }

    # Per-approach aggregate (sum of detectors on each approach)
    per_appr: dict = {}
    for det, vals in out.items():
        a = vals["approach"]
        bucket = per_appr.setdefault(a, {col: 0.0 for col in models})
        for col in models:
            bucket[col] += vals[col]
    for a in per_appr:
        for col in per_appr[a]:
            per_appr[a][col] = round(per_appr[a][col], 1)

    return {
        "available":     True,
        "target_ts":     target_ts.isoformat(),
        "horizons_min":  [0, 15, 30, 60],
        "per_detector":  out,
        "per_approach":  per_appr,
        "model_path":    str(lgb_bundle),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ts", default=None,
                   help="ISO8601 target timestamp (UTC). Default: latest bin in data")
    p.add_argument("--counts-dir", type=Path, default=Path("data/detector_counts"))
    p.add_argument("--lgb-bundle", type=Path, default=Path("models/forecast_lgb.json"))
    p.add_argument("--out", type=Path, default=None,
                   help="Write JSON to file (else print to stdout)")
    args = p.parse_args(argv)

    if args.ts is None:
        df = _read_history(args.counts_dir)
        target_ts = df["timestamp"].max()
    else:
        target_ts = pd.Timestamp(args.ts).tz_convert("UTC") \
            if pd.Timestamp(args.ts).tzinfo \
            else pd.Timestamp(args.ts).tz_localize("UTC")

    result = predict_at(target_ts, args.counts_dir, args.lgb_bundle)
    payload = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload)
        print(f"[predict] wrote {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
