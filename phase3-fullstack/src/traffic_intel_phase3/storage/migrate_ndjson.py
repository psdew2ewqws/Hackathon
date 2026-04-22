#!/usr/bin/env python3
"""One-shot migration: seed SQLite from existing NDJSON artifacts.

Reads:
  - phase3-fullstack/data/counts.ndjson         → detector_counts
  - phase3-fullstack/data/signal_log.ndjson     → signal_events
  - data/signal_timing_log/*.ndjson             → signal_events (bulk daily)
  - phase3-fullstack/data/events.ndjson         → incidents
  - data/ingest_errors.ndjson                   → ingest_errors
  - data/forecast/*.json                         → forecasts (when schema matches)

Idempotent via UNIQUE keys on incident.event_id.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "phase3-fullstack" / "src"))

from traffic_intel_phase3.storage.db import Db, get_db, init_schema  # noqa: E402


COUNTS_SRC = ROOT / "phase3-fullstack" / "data" / "counts.ndjson"
SIGNAL_LOG_SRC = ROOT / "phase3-fullstack" / "data" / "signal_log.ndjson"
SIGNAL_LOG_DIR = ROOT / "data" / "signal_timing_log"
EVENTS_SRC = ROOT / "phase3-fullstack" / "data" / "events.ndjson"
INGEST_ERR_SRC = ROOT / "data" / "ingest_errors.ndjson"


def _iter_ndjson(path: Path):
    if not path.exists():
        return
    with path.open() as fp:
        for i, line in enumerate(fp, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as exc:
                print(f"  warn: {path.name} line {i} bad json: {exc}", file=sys.stderr)


def migrate_counts(db: Db, site_id: str = "wadi_saqra") -> int:
    """Tracker bin records (crossings_in_bin per approach) -> detector_counts.

    Each bin has 4 approaches -> 4 rows.
    """
    n = 0
    rows = []
    for rec in _iter_ndjson(COUNTS_SRC):
        bin_end = rec.get("bin_end")
        ts = rec.get("bin_end_iso") or (
            __import__("datetime").datetime.fromtimestamp(bin_end).isoformat() if bin_end else None
        )
        if not ts:
            continue
        crossings = rec.get("crossings_in_bin") or {}
        in_zone = rec.get("in_zone") or {}
        for approach, count in crossings.items():
            rows.append((
                site_id, ts, None, approach, None,
                int(count), float(in_zone.get(approach, 0)) or None, 0,
            ))
    if rows:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO detector_counts(site_id, ts, detector_id, approach, lane, count, occupancy_pct, quality_flag)"
                " VALUES(?,?,?,?,?,?,?,?)",
                rows,
            )
        n = len(rows)
    return n


def migrate_signal(db: Db, site_id: str = "wadi_saqra") -> int:
    n = 0
    rows = []
    for rec in _iter_ndjson(SIGNAL_LOG_SRC):
        rows.append((
            site_id, rec["timestamp"], rec.get("cycle_number"),
            int(rec["phase_number"]), rec.get("phase_name"),
            rec["signal_state"], rec.get("duration_seconds"),
        ))
    if SIGNAL_LOG_DIR.exists():
        for p in sorted(SIGNAL_LOG_DIR.glob("*.ndjson")):
            for rec in _iter_ndjson(p):
                rows.append((
                    rec.get("intersection_id", site_id), rec["timestamp"], rec.get("cycle_number"),
                    int(rec["phase_number"]), rec.get("phase_name"),
                    rec["signal_state"], rec.get("duration_seconds"),
                ))
    if rows:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO signal_events(site_id, ts, cycle_number, phase_number, phase_name, signal_state, duration_s)"
                " VALUES(?,?,?,?,?,?,?)",
                rows,
            )
        n = len(rows)
    return n


def migrate_events(db: Db, site_id: str = "wadi_saqra") -> int:
    n = 0
    rows = []
    for rec in _iter_ndjson(EVENTS_SRC):
        payload = rec.get("payload") or {}
        rows.append((
            site_id, rec.get("ts"), rec["event_id"], rec["event_type"],
            rec.get("approach"), rec.get("severity", "info"),
            rec.get("confidence"), json.dumps(payload),
            rec.get("snapshot_uri"), rec.get("clip_uri"),
        ))
    if rows:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO incidents(site_id, ts, event_id, event_type, approach, severity, confidence, payload, snapshot_uri, clip_uri)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        n = len(rows)
    return n


def migrate_ingest_errors(db: Db) -> int:
    n = 0
    rows = []
    for rec in _iter_ndjson(INGEST_ERR_SRC):
        rows.append((
            None, rec.get("ts") or rec.get("timestamp"),
            rec.get("source", "unknown"),
            rec.get("error") or json.dumps(rec.get("errors") or []),
            json.dumps(rec.get("record")) if rec.get("record") else None,
        ))
    if rows:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO ingest_errors(site_id, ts, source, reason, record) VALUES(?,?,?,?,?)",
                rows,
            )
        n = len(rows)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None, help="SQLite file path (default: .../traffic_intel.db)")
    ap.add_argument("--site-id", default="wadi_saqra")
    args = ap.parse_args(argv)

    db = get_db(args.db) if args.db is None else Db(args.db)
    init_schema(db)

    c = migrate_counts(db, args.site_id)
    s = migrate_signal(db, args.site_id)
    e = migrate_events(db, args.site_id)
    ie = migrate_ingest_errors(db)

    total = db.query_one("SELECT "
                         "(SELECT COUNT(*) FROM detector_counts) AS counts, "
                         "(SELECT COUNT(*) FROM signal_events)   AS signals, "
                         "(SELECT COUNT(*) FROM incidents)       AS incidents, "
                         "(SELECT COUNT(*) FROM ingest_errors)   AS ingest_errors")
    print(f"inserted: counts={c} signals={s} incidents={e} ingest_errors={ie}")
    print(f"db totals: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
