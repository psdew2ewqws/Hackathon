"""Join persisted forecasts with actual detector counts → forecast_score.

Phase 2 of the production-readiness plan. The runtime persists every
prediction to ``forecasts(target_ts, approach, horizon_min, demand_pred)``;
this script walks those rows, finds the ``detector_counts`` bin whose
``ts`` is nearest to the prediction's ``target_ts``, and writes the
(pred, actual, abs_err) triple into ``forecast_score``.

Idempotent (UNIQUE on (site_id, target_ts, approach, horizon_min, made_at)
+ INSERT OR REPLACE), so re-running fills in newly-arrived actuals.

Usage:
    python phase3-fullstack/scripts/backfill_forecast_score.py [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "phase3-fullstack" / "data" / "traffic_intel.db"

# Tolerance: a 15-second bin can be matched to a forecast whose target_ts
# is within ±20s of the bin's center. Wider than the bin width so a
# forecast made for the bin boundary still finds its actual.
TOLERANCE_S = 20.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    if not args.db.exists():
        print(f"db not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT site_id, made_at, target_ts, approach, horizon_min, demand_pred
        FROM forecasts
        ORDER BY target_ts
        """
    )
    forecasts = cur.fetchall()
    if not forecasts:
        print("no forecasts to score yet")
        return 0

    written = 0
    skipped = 0
    for row in forecasts:
        # Find the detector_count whose ts is closest to target_ts within tolerance.
        cur.execute(
            """
            SELECT ts, count
            FROM detector_counts
            WHERE site_id = ? AND approach = ?
              AND ABS(strftime('%s', ts) - strftime('%s', ?)) <= ?
            ORDER BY ABS(strftime('%s', ts) - strftime('%s', ?))
            LIMIT 1
            """,
            (row["site_id"], row["approach"], row["target_ts"], TOLERANCE_S, row["target_ts"]),
        )
        match = cur.fetchone()
        if match is None:
            skipped += 1
            continue
        actual = float(match["count"])
        pred = float(row["demand_pred"])
        abs_err = abs(pred - actual)
        cur.execute(
            """
            INSERT OR REPLACE INTO forecast_score
              (site_id, target_ts, approach, horizon_min, demand_pred, demand_actual, abs_err, made_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["site_id"], row["target_ts"], row["approach"], row["horizon_min"],
             pred, actual, abs_err, row["made_at"]),
        )
        written += 1

    conn.commit()
    conn.close()
    print(f"forecast_score updated: {written} rows written, {skipped} forecasts unmatched (no actual yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
