"""C8 — Synthetic detector counts generator.

Produces one parquet per day at ``--out-dir/counts_YYYY-MM-DD.parquet``.
Schema matches the plan §3.1:

    timestamp, intersection_id, detector_id, approach, lane, lane_type,
    vehicle_count, occupancy_pct, quality_flag

22 detectors × 96 15-min bins = 2,112 rows per day.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .profiles import DetectorSpec, ProfileConfig, detector_day_counts, occupancy_from_count

INTERSECTION_ID_DEFAULT = os.environ.get("INTERSECTION_ID", "SITE1")
BINS_PER_DAY = 96
SCHEMA = pa.schema([
    pa.field("timestamp",       pa.timestamp("ns", tz="UTC")),
    pa.field("intersection_id", pa.string()),
    pa.field("detector_id",     pa.string()),
    pa.field("approach",        pa.string()),
    pa.field("lane",            pa.int16()),
    pa.field("lane_type",       pa.string()),
    pa.field("vehicle_count",   pa.int32()),
    pa.field("occupancy_pct",   pa.float32()),
    pa.field("quality_flag",    pa.int8()),
])


def _bin_timestamps(day: date) -> list[pd.Timestamp]:
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [pd.Timestamp(base + timedelta(minutes=15 * i)) for i in range(BINS_PER_DAY)]


def build_day(
    day: date,
    cfg: ProfileConfig,
    intersection_id: str,
    rng: np.random.Generator,
) -> pd.DataFrame:
    is_weekend = day.weekday() >= 5
    timestamps = _bin_timestamps(day)

    rows: list[dict] = []
    for det in cfg.detectors:
        counts = detector_day_counts(cfg, det, is_weekend, rng)
        for bin_idx, ts in enumerate(timestamps):
            count = int(counts[bin_idx])
            rows.append({
                "timestamp": ts,
                "intersection_id": intersection_id,
                "detector_id": det.id,
                "approach": det.approach,
                "lane": det.lane,
                "lane_type": det.lane_type,
                "vehicle_count": count,
                "occupancy_pct": occupancy_from_count(count, det.lane_type),
                "quality_flag": 0,
            })
    return pd.DataFrame.from_records(rows)


def _seed_for_day(master_seed: int, day: date) -> int:
    # Stable per-day seed derived from master so each day is reproducible
    # but distinct. Cap to 32-bit for numpy compatibility.
    return (master_seed * 1_000_003 + day.toordinal()) & 0x7FFFFFFF


def generate(
    profiles_path: Path,
    out_dir: Path,
    days: int,
    start_date: date,
    intersection_id: str,
    seed: int,
) -> list[Path]:
    cfg = ProfileConfig.load(profiles_path)
    if len(cfg.detectors) != 22:
        print(
            f"[warn] profiles.yml defines {len(cfg.detectors)} detectors "
            f"(handbook §6.3 calls for 22)",
            file=sys.stderr,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        rng = np.random.default_rng(_seed_for_day(seed, day))
        df = build_day(day, cfg, intersection_id, rng)
        out_path = out_dir / f"counts_{day.isoformat()}.parquet"
        table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
        pq.write_table(table, out_path, compression="zstd")
        written.append(out_path)
        print(
            f"[counts] {day}  detectors={df['detector_id'].nunique()}  "
            f"rows={len(df)}  total={df['vehicle_count'].sum()}  →  {out_path.name}",
            file=sys.stderr,
        )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic detector counts parquet.")
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--start-date", type=str, default=None,
                        help="ISO date; defaults to (today - days)")
    parser.add_argument("--intersection-id", default=INTERSECTION_ID_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    start = (
        datetime.fromisoformat(args.start_date).date()
        if args.start_date
        else date.today() - timedelta(days=args.days)
    )
    written = generate(args.profiles, args.out_dir, args.days, start, args.intersection_id, args.seed)
    print(f"[done] {len(written)} day-parquet(s) written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
