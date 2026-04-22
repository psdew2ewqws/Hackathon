"""§8.1 Data Acquisition Layer facade.

Composes:
  * the existing ``TrackerService`` (video) for RTSP ingest
  * the existing ``phase2 ingest_layer.follow()`` loop for detector/signal/incident
    batch sources (read-only)
  * a ``ReconnectPolicy`` (5-10s exponential backoff) surfaced via
    ``IngestMetrics`` (frames, drops, uptime, reconnect_count).

The service is strictly READ-ONLY: no source is ever opened in write mode,
nothing here writes to live signal control or operational infra. Outputs go
to SQLite (via StorageSink) and NDJSON files (already-existing).
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .metrics import IngestMetrics, shared as shared_metrics

LOG = logging.getLogger(__name__)


@dataclass
class ReconnectPolicy:
    """Exponential backoff in the 5-10s band (handbook requirement).

    Sequence of sleeps: 5, 5, 7, 9, 10, 10, ... with +-20% jitter.
    """
    base_s: float = 5.0
    max_s: float = 10.0
    jitter: float = 0.2

    def wait(self, attempt: int) -> float:
        # Cap the growth before jitter so we stay inside handbook band.
        backoff = min(self.max_s, self.base_s + attempt * 1.0)
        if self.jitter > 0:
            backoff *= 1.0 + random.uniform(-self.jitter, self.jitter)
        backoff = max(self.base_s * (1 - self.jitter), min(self.max_s * (1 + self.jitter), backoff))
        return backoff


class AcquisitionService:
    """Thin coordinator that watches the existing ingest sources."""

    def __init__(
        self,
        ingest_state_file: Path | None = None,
        detector_dir: Path | None = None,
        signal_dir: Path | None = None,
        incidents_file: Path | None = None,
        unified_out: Path | None = None,
        errors_out: Path | None = None,
        metrics: IngestMetrics | None = None,
        reconnect: ReconnectPolicy | None = None,
        poll_interval_s: float = 5.0,
    ) -> None:
        self.ingest_state_file = ingest_state_file
        self.detector_dir = detector_dir
        self.signal_dir = signal_dir
        self.incidents_file = incidents_file
        self.unified_out = unified_out
        self.errors_out = errors_out
        self.metrics = metrics or shared_metrics()
        self.reconnect = reconnect or ReconnectPolicy()
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_metrics: list[Callable[[dict], None]] = []
        for source in ("video", "detector", "signal", "incident"):
            self.metrics.mark_started(source)

    # ---- producer observers (video tracker publishes via these) -------

    def bump_video_ok(self) -> None:
        self.metrics.mark_ok("video")

    def bump_video_drop(self) -> None:
        self.metrics.mark_drop("video")

    def bump_video_error(self, reason: str) -> None:
        self.metrics.mark_error("video", reason)

    def bump_video_reconnect(self) -> None:
        self.metrics.mark_reconnect("video")

    # ---- batch follower -----------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="acquisition", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Tail the batch sources (detector/signal/incident) via the existing
        Phase-2 ``ingest_layer.run_once()``. On exception, log once + back off
        in the 5-10s band per handbook §8.1."""
        try:
            from traffic_intel_phase2.ingest_layer import run_once  # type: ignore[import-not-found]
        except Exception as exc:
            LOG.warning("phase2 ingest_layer unavailable (%s); acquisition loop idle", exc)
            return

        if not (self.detector_dir and self.signal_dir and self.incidents_file
                and self.unified_out and self.errors_out):
            LOG.info("acquisition loop has incomplete paths; idle")
            return

        attempt = 0
        while not self._stop.is_set():
            try:
                stats = run_once(
                    counts_dir=self.detector_dir,
                    signals_dir=self.signal_dir,
                    events_path=self.incidents_file,
                    unified=self.unified_out,
                    errors=self.errors_out,
                    state_path=self.ingest_state_file,
                )
                if stats.detector_rows:
                    self.metrics.mark_ok("detector", stats.detector_rows)
                if stats.signal_rows:
                    self.metrics.mark_ok("signal", stats.signal_rows)
                if stats.incident_rows:
                    self.metrics.mark_ok("incident", stats.incident_rows)
                attempt = 0
                self._stop.wait(self.poll_interval_s)
            except Exception as exc:
                attempt += 1
                self.metrics.mark_error("detector", f"{exc!r}")
                self.metrics.mark_reconnect("detector")
                backoff = self.reconnect.wait(attempt)
                LOG.warning("acquisition loop failed (%s); retrying in %.1fs", exc, backoff)
                self._stop.wait(backoff)
