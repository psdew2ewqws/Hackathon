"""Wall-clock 2-phase signal simulator for Phase 1 §6.4.

Emits events matching the handbook schema:
    {timestamp, intersection_id, phase_number, signal_state}
with extras (phase_name, cycle_number, approaches_affected, duration_seconds)
for dashboard use.

Events are appended to an on-disk NDJSON and retained in an in-memory ring
buffer so the API can return recent events without touching the file.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterable

LOG = logging.getLogger(__name__)

# Fixed per-cycle event order for a 2-phase intersection (NS, then EW).
# durations pull from CurrentPlan so the sequence length is cycle_seconds.
# Each entry: (phase_number, phase_name, signal_state, approaches, duration_field)
_PHASE_EVENTS = (
    (1, "NS", "GREEN ON",  ("N", "S"), "NS_green"),
    (1, "NS", "YELLOW ON", ("N", "S"), "yellow"),
    (1, "NS", "RED ON",    ("N", "S"), "all_red"),
    (2, "EW", "GREEN ON",  ("E", "W"), "EW_green"),
    (2, "EW", "YELLOW ON", ("E", "W"), "yellow"),
    (2, "EW", "RED ON",    ("E", "W"), "all_red"),
)


@dataclass(frozen=True)
class CurrentPlan:
    NS_green: float = 35.0
    EW_green: float = 35.0
    yellow: float = 3.0
    all_red: float = 2.0

    @property
    def cycle_seconds(self) -> float:
        return self.NS_green + self.EW_green + 2 * (self.yellow + self.all_red)

    def duration(self, field_name: str) -> float:
        return float(getattr(self, field_name))


def _iter_cycle(plan: CurrentPlan) -> Iterable[tuple[int, str, str, tuple[str, ...], float]]:
    """Yield (phase_number, phase_name, signal_state, approaches, duration_seconds)."""
    for phase_num, phase_name, state, approaches, field_name in _PHASE_EVENTS:
        yield phase_num, phase_name, state, approaches, plan.duration(field_name)


def generate_day(
    plan: CurrentPlan,
    intersection_id: str,
    day_start: datetime,
    day_end: datetime,
) -> list[dict]:
    """Generate every phase-transition event between day_start and day_end."""
    events: list[dict] = []
    t = day_start
    cycle = 0
    while t < day_end:
        for phase_num, phase_name, state, approaches, dur in _iter_cycle(plan):
            events.append({
                "timestamp": t.isoformat(timespec="milliseconds"),
                "intersection_id": intersection_id,
                "cycle_number": cycle,
                "phase_number": phase_num,
                "phase_name": phase_name,
                "signal_state": state,
                "approaches_affected": list(approaches),
                "duration_seconds": dur,
            })
            t = t + timedelta(seconds=dur)
            if t >= day_end:
                break
        cycle += 1
    return events


@dataclass
class SignalSimState:
    current: dict | None = None
    buffer: deque = field(default_factory=lambda: deque(maxlen=200))
    running: bool = False


class SignalSimulator:
    """Runs a wall-clock signal cycle in a daemon thread."""

    def __init__(
        self,
        intersection_id: str,
        plan: CurrentPlan,
        ndjson_path: Path | None = None,
    ) -> None:
        self.intersection_id = intersection_id
        self.plan = plan
        self.ndjson_path = ndjson_path
        self.state = SignalSimState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._listeners.append(cb)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="signal_sim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        self.state.running = True
        fp = None
        if self.ndjson_path:
            self.ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            fp = self.ndjson_path.open("a", buffering=1)
        cycle = 0
        try:
            while not self._stop.is_set():
                for phase_num, phase_name, state, approaches, dur in _iter_cycle(self.plan):
                    if self._stop.is_set():
                        break
                    now = datetime.now(timezone.utc).astimezone()
                    event = {
                        "timestamp": now.isoformat(timespec="milliseconds"),
                        "intersection_id": self.intersection_id,
                        "cycle_number": cycle,
                        "phase_number": phase_num,
                        "phase_name": phase_name,
                        "signal_state": state,
                        "approaches_affected": list(approaches),
                        "duration_seconds": dur,
                    }
                    with self._lock:
                        self.state.current = event
                        self.state.buffer.append(event)
                    if fp:
                        fp.write(json.dumps(event) + "\n")
                    for cb in self._listeners:
                        try:
                            cb(event)
                        except Exception:
                            LOG.exception("signal listener failed")
                    # Sleep for the phase duration, but break early on stop.
                    deadline = time.monotonic() + dur
                    while not self._stop.is_set():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        time.sleep(min(0.25, remaining))
                cycle += 1
        finally:
            self.state.running = False
            if fp:
                fp.close()

    # Snapshot helpers ---------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.state.running,
                "intersection_id": self.intersection_id,
                "plan": {
                    "NS_green": self.plan.NS_green,
                    "EW_green": self.plan.EW_green,
                    "yellow": self.plan.yellow,
                    "all_red": self.plan.all_red,
                    "cycle_seconds": round(self.plan.cycle_seconds, 1),
                },
                "current": self.state.current,
            }

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            data = list(self.state.buffer)
        if limit > 0:
            data = data[-limit:]
        return data
