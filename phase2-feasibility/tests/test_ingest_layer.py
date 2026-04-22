"""Smoke tests for the unified ingest service (Phase 2 §7.2).

Covers:
  * validator wiring (schema violations land in errors.ndjson, valid records
    land in unified.ndjson)
  * incremental cursor across runs (second pass with no new data is a no-op)
  * all three source kinds (detector parquet, signal NDJSON, incident NDJSON)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_ndjson(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _write_counts_parquet(path: Path, rows: list[dict]) -> None:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path)


def test_ingest_layer_drains_all_three_sources(tmp_path: Path) -> None:
    from traffic_intel_phase2.ingest_layer import run_once

    counts_dir = tmp_path / "detector_counts"
    signals_dir = tmp_path / "signal_logs"
    events_path = tmp_path / "events" / "phase2.ndjson"
    unified = tmp_path / "ingest_unified.ndjson"
    errors = tmp_path / "ingest_errors.ndjson"
    state = tmp_path / "state.json"

    _write_counts_parquet(counts_dir / "counts_2026-04-20.parquet", [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "detector_id": "DET-N-1-1", "approach": "N", "lane": 1,
         "lane_type": "through", "vehicle_count": 5, "occupancy_pct": 0.5,
         "quality_flag": 0},
        {"timestamp": "2026-04-20T00:15:00Z", "intersection_id": "SITE1",
         "detector_id": "DET-N-1-1", "approach": "N", "lane": 1,
         "lane_type": "through", "vehicle_count": 6, "occupancy_pct": 0.6,
         "quality_flag": 0},
    ])

    _write_ndjson(signals_dir / "signal_2026-04-20.ndjson", [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "phase": 2, "state": "GREEN_ON"},
        {"timestamp": "2026-04-20T00:00:25Z", "intersection_id": "SITE1",
         "phase": 2, "state": "YELLOW_ON"},
    ])

    _write_ndjson(events_path, [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "event_type": "zone_occupancy", "name": "queue_spillback_N",
         "kind": "queue_spillback", "count": 3, "prev": 0, "frame": 42},
        # Deliberate bad record — missing required fields
        {"timestamp": "2026-04-20T00:00:01Z", "intersection_id": "SITE1",
         "event_type": "zone_occupancy"},
    ])

    stats = run_once(counts_dir, signals_dir, events_path, unified, errors, state)
    assert stats.detector_rows == 2
    assert stats.signal_rows == 2
    assert stats.incident_rows == 1
    assert stats.errors == 1

    # Unified file has 5 records, one per valid input
    lines = unified.read_text().splitlines()
    assert len(lines) == 5
    sources = {json.loads(ln)["source"] for ln in lines}
    assert sources == {"detector", "signal", "incident"}

    # Error file has the single invalid record
    err_lines = errors.read_text().splitlines()
    assert len(err_lines) == 1
    err_rec = json.loads(err_lines[0])
    assert err_rec["source"] == "incident"
    assert "errors" in err_rec


def test_cursor_advances_so_second_pass_is_a_noop(tmp_path: Path) -> None:
    """Running twice without adding new data yields 0 rows on pass 2."""
    from traffic_intel_phase2.ingest_layer import run_once

    counts_dir = tmp_path / "detector_counts"
    signals_dir = tmp_path / "signal_logs"
    events_path = tmp_path / "events" / "phase2.ndjson"
    unified = tmp_path / "u.ndjson"
    errors = tmp_path / "e.ndjson"
    state = tmp_path / "state.json"

    _write_counts_parquet(counts_dir / "counts_2026-04-20.parquet", [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "detector_id": "DET-N-1-1", "approach": "N", "lane": 1,
         "lane_type": "through", "vehicle_count": 5, "occupancy_pct": 0.5,
         "quality_flag": 0},
    ])
    _write_ndjson(signals_dir / "signal_2026-04-20.ndjson", [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "phase": 2, "state": "GREEN_ON"},
    ])
    _write_ndjson(events_path, [
        {"timestamp": "2026-04-20T00:00:00Z", "intersection_id": "SITE1",
         "event_type": "run_start"},
    ])

    s1 = run_once(counts_dir, signals_dir, events_path, unified, errors, state)
    assert s1.detector_rows + s1.signal_rows + s1.incident_rows == 3

    s2 = run_once(counts_dir, signals_dir, events_path, unified, errors, state)
    assert s2.detector_rows == 0
    assert s2.signal_rows == 0
    assert s2.incident_rows == 0
    assert s2.errors == 0
