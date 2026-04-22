"""Verify the Phase 3 SQLite schema + storage sink round-trips."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


EXPECTED_TABLES = {
    "sites", "users", "detector_counts", "signal_events", "incidents",
    "forecasts", "recommendations", "audit_log", "ingest_errors",
    "system_metrics",
    # SQLite creates this automatically for AUTOINCREMENT columns.
    "sqlite_sequence",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def test_all_tables_present(phase3_db):
    rows = phase3_db.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r["name"] for r in rows}
    # Every business table we care about must exist.
    for expected in EXPECTED_TABLES - {"sqlite_sequence"}:
        assert expected in names, f"missing table: {expected}"


def test_foreign_keys_enabled(phase3_db):
    (row,) = phase3_db.query_all("PRAGMA foreign_keys")
    assert row["foreign_keys"] == 1


def test_sites_bootstrap_row(phase3_db):
    row = phase3_db.query_one(
        "SELECT site_id, name FROM sites WHERE site_id='wadi_saqra'"
    )
    assert row is not None
    assert row["name"].startswith("Wadi")


def test_sink_round_trip_every_kind(phase3_db):
    try:
        from traffic_intel_phase3.storage.sinks import StorageSink
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"sinks unavailable: {exc}")

    sink = StorageSink(db=phase3_db, flush_s=0.05, batch_size=8)
    sink.start()

    ts = _now_iso()
    sink.push("detector_count", {
        "site_id": "wadi_saqra", "ts": ts, "approach": "N", "count": 3,
        "occupancy_pct": 0.12, "quality_flag": 0,
    })
    sink.push("signal_event", {
        "site_id": "wadi_saqra", "ts": ts, "cycle_number": 1,
        "phase_number": 1, "phase_name": "NS",
        "signal_state": "GREEN ON", "duration_s": 35.0,
    })
    sink.push("incident", {
        "site_id": "wadi_saqra", "ts": ts,
        "event_id": "evt_test_0001", "event_type": "queue_spillback",
        "approach": "E", "severity": "critical", "confidence": 0.9,
        "payload": {"queue_count": 24, "threshold": 20},
    })
    sink.push("forecast", {
        "site_id": "wadi_saqra", "made_at": ts, "target_ts": ts,
        "approach": "S", "horizon_min": 15, "demand_pred": 12.4,
        "model_version": "lgb-v0.1",
    })
    sink.push("recommendation", {
        "site_id": "wadi_saqra", "ts": ts, "mode": "two_phase",
        "cycle_s": 80.0, "ns_green": 42.0, "ew_green": 32.0,
        "delay_est_s": 18.5, "component_json": {"Y": 0.73},
    })
    sink.push("ingest_error", {
        "ts": ts, "source": "rtsp", "reason": "timeout",
        "record": {"url": "rtsp://fake"},
    })
    sink.push("system_metric", {
        "site_id": "wadi_saqra", "ts": ts, "module": "tracker",
        "fps": 9.8, "uptime_s": 42.0, "frames_dropped": 0,
        "latency_ms": 38.1, "mem_mb": 512.0,
    })
    sink.push("audit", {
        "username": "admin", "role": "admin",
        "action": "login", "resource": "/api/auth/login",
        "payload": {"ok": True}, "ip": "127.0.0.1",
    })

    sink.stop(drain=True)

    def count(sql: str) -> int:
        return phase3_db.query_one(sql)["n"]

    assert count("SELECT COUNT(*) n FROM detector_counts  WHERE approach='N'")   >= 1
    assert count("SELECT COUNT(*) n FROM signal_events    WHERE phase_name='NS'") >= 1
    assert count("SELECT COUNT(*) n FROM incidents        WHERE event_id='evt_test_0001'") == 1
    assert count("SELECT COUNT(*) n FROM forecasts        WHERE horizon_min=15") >= 1
    assert count("SELECT COUNT(*) n FROM recommendations  WHERE mode='two_phase'") >= 1
    assert count("SELECT COUNT(*) n FROM ingest_errors    WHERE source='rtsp'")  >= 1
    assert count("SELECT COUNT(*) n FROM system_metrics   WHERE module='tracker'") >= 1
    assert count("SELECT COUNT(*) n FROM audit_log        WHERE action='login'") >= 1

    # JSON payload survived the serialisation round-trip.
    inc = phase3_db.query_one(
        "SELECT payload FROM incidents WHERE event_id='evt_test_0001'"
    )
    parsed = json.loads(inc["payload"])
    assert parsed["queue_count"] == 24
