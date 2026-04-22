"""Thread-safe ingestion metrics surfaced via /api/ingest/metrics."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class SourceMetrics:
    source: str                    # "video" | "detector" | "signal" | "incident"
    started_at: float | None = None
    last_ok_ts: float | None = None
    last_error_ts: float | None = None
    last_error: str | None = None
    records_total: int = 0
    records_dropped: int = 0
    reconnect_count: int = 0

    def uptime_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, time.time() - self.started_at)


class IngestMetrics:
    """Aggregate metrics across all ingest sources. All methods are thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, SourceMetrics] = {}

    def _s(self, source: str) -> SourceMetrics:
        s = self._sources.get(source)
        if s is None:
            s = SourceMetrics(source=source, started_at=time.time())
            self._sources[source] = s
        return s

    def mark_started(self, source: str) -> None:
        with self._lock:
            s = self._s(source)
            if s.started_at is None:
                s.started_at = time.time()

    def mark_ok(self, source: str, n: int = 1) -> None:
        with self._lock:
            s = self._s(source)
            s.last_ok_ts = time.time()
            s.records_total += n

    def mark_drop(self, source: str, n: int = 1) -> None:
        with self._lock:
            self._s(source).records_dropped += n

    def mark_error(self, source: str, error: str) -> None:
        with self._lock:
            s = self._s(source)
            s.last_error_ts = time.time()
            s.last_error = error[:400]

    def mark_reconnect(self, source: str) -> None:
        with self._lock:
            self._s(source).reconnect_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            sources = {
                k: {
                    "source": v.source,
                    "uptime_s": round(v.uptime_s(), 1),
                    "last_ok_ts": v.last_ok_ts,
                    "last_error_ts": v.last_error_ts,
                    "last_error": v.last_error,
                    "records_total": v.records_total,
                    "records_dropped": v.records_dropped,
                    "reconnect_count": v.reconnect_count,
                    "ingest_rate_hz": (v.records_total / v.uptime_s()) if v.uptime_s() > 0 else None,
                }
                for k, v in self._sources.items()
            }
        return {"sources": sources}


_shared = IngestMetrics()


def shared() -> IngestMetrics:
    return _shared
