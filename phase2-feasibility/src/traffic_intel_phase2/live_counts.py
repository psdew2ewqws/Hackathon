"""Turn live phase2.ndjson crossings into real detector_counts parquet.

Aggregates ``lane_crossing`` events (falling back to ``stop_line_crossing``
when lane-level data isn't present) into the 15-min per-detector schema
that ``data/detector_counts/counts_*.parquet`` expects. The dashboard's
Historical Performance panel already reads this directory, so running
this script transforms the parametric synth curve into actual YOLO-counted
vehicles for the dates where the detector has been alive.

Default behaviour is **safe**: it only writes files for dates that don't
already have a parquet in ``data/detector_counts/``, so the 30 days of
synth baseline stays intact. Use ``--overwrite`` to replace synth with
live for dates that overlap.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVENTS = REPO_ROOT / "data" / "events" / "phase2.ndjson"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "detector_counts"

BIN_MIN = 15
# A 15-min bin is roughly saturated at 40 vehicles/lane in a busy urban
# setting — we use this to turn count → occupancy_pct for schema parity.
SATURATION_VEH_PER_BIN = 40.0


@dataclass(frozen=True)
class BinKey:
    bin_start_iso: str
    approach: str
    lane_id: str
    lane_type: str
    lane_idx: int

    def detector_id(self) -> str:
        # lane_id="E-2", lane_idx=1 → DET-E-2-1 (single detector per lane)
        return f"DET-{self.approach}-{self.lane_idx + 1}-1"

    def lane(self) -> int:
        return self.lane_idx + 1


def _bin_start(ts_iso: str) -> datetime:
    ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    ts = ts.astimezone(timezone.utc)
    floor_min = (ts.minute // BIN_MIN) * BIN_MIN
    return ts.replace(minute=floor_min, second=0, microsecond=0)


def _has_lane_crossings(events_path: Path) -> bool:
    """One-pass check whether the ndjson contains any lane_crossing events.
    If yes, we skip stop_line_crossing entirely (double-counts the same
    vehicles at a coarser granularity)."""
    with events_path.open() as fh:
        for raw in fh:
            if '"lane_crossing"' in raw:
                return True
    return False


def _iter_useful_events(events_path: Path, use_lane_only: bool):
    """Yield (event_dict, bin_start_dt) for positive-delta crossings.

    When ``use_lane_only`` is True we ignore ``stop_line_crossing`` (the
    phase2 pipeline fires *both* lane + stop-line crossings for the same
    vehicle, so summing both double-counts). When False we fall back to
    stop_line_crossings — useful for older event logs predating the
    lane_crossing feature."""
    accept = {"lane_crossing"} if use_lane_only else {"lane_crossing",
                                                      "stop_line_crossing"}
    with events_path.open() as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if e.get("event_type") not in accept:
                continue
            delta = int(e.get("delta", 0) or 0)
            if delta <= 0:
                continue
            ts = e.get("timestamp")
            if not ts:
                continue
            try:
                yield e, _bin_start(ts)
            except ValueError:
                continue


def aggregate(events_path: Path = DEFAULT_EVENTS,
              out_dir: Path = DEFAULT_OUT_DIR,
              overwrite: bool = False) -> dict:
    """Aggregate events into one parquet per date. Returns a per-date summary."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not events_path.exists():
        return {"available": False, "message": f"no events file at {events_path}"}

    use_lane_only = _has_lane_crossings(events_path)

    # (date, BinKey) → vehicle_count
    buckets: dict[str, dict[BinKey, int]] = defaultdict(lambda: defaultdict(int))

    for e, bin_start in _iter_useful_events(events_path, use_lane_only):
        approach = e.get("approach")
        if not approach:
            continue
        date_iso = bin_start.date().isoformat()

        if e["event_type"] == "lane_crossing":
            key = BinKey(
                bin_start_iso=bin_start.isoformat(),
                approach=approach,
                lane_id=e.get("lane_id") or f"{approach}-1",
                lane_type=e.get("lane_type") or "through",
                lane_idx=int(e.get("lane_idx", 0) or 0),
            )
        else:  # stop_line_crossing — only reached when lane_crossing absent
            key = BinKey(
                bin_start_iso=bin_start.isoformat(),
                approach=approach,
                lane_id=f"{approach}-1",
                lane_type="through",
                lane_idx=0,
            )
        buckets[date_iso][key] += int(e.get("delta", 1) or 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    for date_iso, per_bin in sorted(buckets.items()):
        out_path = out_dir / f"counts_{date_iso}.parquet"
        existed = out_path.exists()
        if existed and not overwrite:
            summary[date_iso] = {"rows": 0, "skipped": True,
                                 "reason": "exists; pass --overwrite to replace"}
            continue

        rows = []
        for key, count in per_bin.items():
            rows.append({
                "timestamp":       key.bin_start_iso,
                "intersection_id": "SITE1",
                "detector_id":     key.detector_id(),
                "approach":        key.approach,
                "lane":            key.lane(),
                "lane_type":       key.lane_type,
                "vehicle_count":   int(count),
                "occupancy_pct":   float(min(100.0, 100.0 * count / SATURATION_VEH_PER_BIN)),
                "quality_flag":    0,
            })
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        # Stable order for reproducibility + downstream speed
        df = df.sort_values(["detector_id", "timestamp"]).reset_index(drop=True)
        # Pin dtypes to match synth schema exactly
        df = df.astype({
            "intersection_id": "string",
            "detector_id":     "string",
            "approach":        "string",
            "lane":             "int16",
            "lane_type":       "string",
            "vehicle_count":    "int32",
            "occupancy_pct":    "float32",
            "quality_flag":     "int8",
        })
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out_path)
        summary[date_iso] = {"rows": len(df), "path": str(out_path.relative_to(REPO_ROOT)),
                             "replaced_synth": existed}

    return {"available": True, "dates": summary}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS,
                   help="Phase 2 live event log")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                   help="Where to write counts_YYYY-MM-DD.parquet")
    p.add_argument("--overwrite", action="store_true",
                   help="Replace any existing (synth or prior live) parquet for "
                        "dates that have live events")
    args = p.parse_args(argv)

    result = aggregate(args.events, args.out_dir, args.overwrite)
    print(json.dumps(result, indent=2))
    return 0 if result.get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
