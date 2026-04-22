"""Batched writer thread that funnels tracker/signal/event/error records into SQLite.

Producers call ``push(kind, row)`` (non-blocking queue put). The writer thread
drains up to ``batch_size`` rows or ``flush_s`` seconds and commits them in a
single transaction. NDJSON-side writes continue to happen in the producers,
so SQLite is an additive sink, not a replacement (yet).
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from .db import Db, get_db

LOG = logging.getLogger(__name__)


@dataclass
class _Record:
    kind: str
    row: dict[str, Any]


class StorageSink:
    def __init__(self, db: Db | None = None, flush_s: float = 1.0, batch_size: int = 200) -> None:
        self.db = db or get_db()
        self.flush_s = flush_s
        self.batch_size = batch_size
        self._q: queue.Queue[_Record] = queue.Queue(maxsize=5000)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="storage_sink", daemon=True)
        self._thread.start()

    def stop(self, drain: bool = True) -> None:
        if drain:
            deadline = time.time() + 3
            while not self._q.empty() and time.time() < deadline:
                time.sleep(0.05)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    # ---- producer API -------------------------------------------------

    def push(self, kind: str, row: dict[str, Any]) -> None:
        try:
            self._q.put_nowait(_Record(kind=kind, row=row))
        except queue.Full:
            LOG.warning("storage sink queue full; dropping %s", kind)

    # ---- writer loop --------------------------------------------------

    def _run(self) -> None:
        buffer: list[_Record] = []
        last_flush = time.monotonic()
        while not self._stop.is_set() or not self._q.empty():
            timeout = max(0.05, self.flush_s - (time.monotonic() - last_flush))
            try:
                rec = self._q.get(timeout=timeout)
                buffer.append(rec)
            except queue.Empty:
                pass
            should_flush = (
                len(buffer) >= self.batch_size
                or (buffer and (time.monotonic() - last_flush) >= self.flush_s)
            )
            if should_flush:
                self._flush(buffer)
                buffer.clear()
                last_flush = time.monotonic()
        if buffer:
            self._flush(buffer)

    def _flush(self, buffer: list[_Record]) -> None:
        try:
            with self.db.transaction() as conn:
                for rec in buffer:
                    try:
                        self._insert(conn, rec)
                    except Exception:
                        LOG.exception("failed to insert %s", rec.kind)
        except Exception:
            LOG.exception("storage transaction failed")

    # ---- per-kind mappers --------------------------------------------

    def _insert(self, conn, rec: _Record) -> None:
        k, r = rec.kind, rec.row
        if k == "detector_count":
            conn.execute(
                "INSERT INTO detector_counts(site_id, ts, detector_id, approach, lane, count, occupancy_pct, quality_flag)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["ts"], r.get("detector_id"),
                 r["approach"], r.get("lane"), int(r.get("count", 0)),
                 r.get("occupancy_pct"), int(r.get("quality_flag", 0))),
            )
        elif k == "signal_event":
            conn.execute(
                "INSERT INTO signal_events(site_id, ts, cycle_number, phase_number, phase_name, signal_state, duration_s)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["ts"], r.get("cycle_number"),
                 int(r["phase_number"]), r.get("phase_name"),
                 r["signal_state"], r.get("duration_s")),
            )
        elif k == "incident":
            payload = r.get("payload")
            if isinstance(payload, dict):
                payload = json.dumps(payload)
            conn.execute(
                "INSERT OR IGNORE INTO incidents(site_id, ts, event_id, event_type, approach, severity,"
                " confidence, payload, snapshot_uri, clip_uri)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["ts"], r["event_id"],
                 r["event_type"], r.get("approach"), r["severity"],
                 r.get("confidence"), payload, r.get("snapshot_uri"), r.get("clip_uri")),
            )
        elif k == "forecast":
            conn.execute(
                "INSERT INTO forecasts(site_id, made_at, target_ts, approach, horizon_min, demand_pred, model_version)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["made_at"], r["target_ts"],
                 r["approach"], int(r["horizon_min"]), float(r["demand_pred"]),
                 r.get("model_version")),
            )
        elif k == "recommendation":
            comp = r.get("component_json")
            if isinstance(comp, dict):
                comp = json.dumps(comp)
            conn.execute(
                "INSERT INTO recommendations(site_id, ts, mode, cycle_s, ns_green, ew_green, delay_est_s, component_json)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["ts"], r["mode"],
                 r.get("cycle_s"), r.get("ns_green"), r.get("ew_green"),
                 r.get("delay_est_s"), comp),
            )
        elif k == "ingest_error":
            rec_json = r.get("record")
            if isinstance(rec_json, dict):
                rec_json = json.dumps(rec_json)
            conn.execute(
                "INSERT INTO ingest_errors(site_id, ts, source, reason, record) VALUES(?,?,?,?,?)",
                (r.get("site_id"), r["ts"], r["source"], r["reason"], rec_json),
            )
        elif k == "system_metric":
            conn.execute(
                "INSERT INTO system_metrics(site_id, ts, module, fps, uptime_s, frames_dropped, latency_ms, mem_mb)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (r.get("site_id", "wadi_saqra"), r["ts"], r["module"],
                 r.get("fps"), r.get("uptime_s"), r.get("frames_dropped"),
                 r.get("latency_ms"), r.get("mem_mb")),
            )
        elif k == "audit":
            payload = r.get("payload")
            if isinstance(payload, dict):
                payload = json.dumps(payload)
            conn.execute(
                "INSERT INTO audit_log(user_id, username, role, action, resource, payload, ip)"
                " VALUES(?,?,?,?,?,?,?)",
                (r.get("user_id"), r.get("username"), r.get("role"),
                 r["action"], r["resource"], payload, r.get("ip")),
            )
        else:
            LOG.warning("unknown sink kind: %s", k)
