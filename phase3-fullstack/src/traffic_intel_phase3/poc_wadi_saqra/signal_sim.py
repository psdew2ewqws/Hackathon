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

# 2-phase cycle (legacy; retained for Webster recommender and backfill).
_PHASE_EVENTS = (
    (1, "NS", "GREEN ON",  ("N", "S"), "NS_green"),
    (1, "NS", "YELLOW ON", ("N", "S"), "yellow"),
    (1, "NS", "RED ON",    ("N", "S"), "all_red"),
    (2, "EW", "GREEN ON",  ("E", "W"), "EW_green"),
    (2, "EW", "YELLOW ON", ("E", "W"), "yellow"),
    (2, "EW", "RED ON",    ("E", "W"), "all_red"),
)

# 3-phase cycle (NS → E → W) — used when a VideoAnchor is configured. The
# real Wadi Saqra light opens E and W separately, not together.
_PHASE_EVENTS_3 = (
    (1, "NS", "GREEN ON",  ("N", "S"), "NS_green"),
    (1, "NS", "YELLOW ON", ("N", "S"), "yellow"),
    (1, "NS", "RED ON",    ("N", "S"), "all_red"),
    (2, "E",  "GREEN ON",  ("E",),     "E_green"),
    (2, "E",  "YELLOW ON", ("E",),     "yellow"),
    (2, "E",  "RED ON",    ("E",),     "all_red"),
    (3, "W",  "GREEN ON",  ("W",),     "W_green"),
    (3, "W",  "YELLOW ON", ("W",),     "yellow"),
    (3, "W",  "RED ON",    ("W",),     "all_red"),
)


@dataclass(frozen=True)
class CurrentPlan:
    NS_green: float = 35.0
    EW_green: float = 35.0   # kept for Webster recommender (2-phase)
    yellow: float = 3.0
    all_red: float = 2.0
    # 3-phase split — used only when a VideoAnchor is wired up. Defaults match
    # EW_green so legacy 2-phase callers see identical cycle_seconds.
    E_green: float = 35.0
    W_green: float = 35.0

    @property
    def cycle_seconds(self) -> float:
        # 2-phase cycle length, unchanged — Webster and UI that references this
        # property keep reading the legacy value.
        return self.NS_green + self.EW_green + 2 * (self.yellow + self.all_red)

    @property
    def cycle_seconds_3phase(self) -> float:
        return (
            self.NS_green + self.E_green + self.W_green
            + 3 * (self.yellow + self.all_red)
        )

    def duration(self, field_name: str) -> float:
        return float(getattr(self, field_name))


@dataclass(frozen=True)
class VideoAnchor:
    """Locks the simulated phase to the looping source video.

    ffmpeg is invoked with ``-re -stream_loop -1``, so the mp4's internal
    timeline repeats deterministically every ``duration_seconds``. Given one
    user-observed anchor ("at video_ts=23.0s the E light turned GREEN"), the
    phase at any wall-clock instant can be computed as:

        video_ts = (now - ffmpeg_start) % duration_seconds
        offset   = (video_ts - anchor.video_ts_seconds) % cycle_seconds_3phase

    and then walked through the fixed (NS, E, W) 3-phase sequence starting at
    the anchor's phase/state.
    """
    video_ts_seconds: float
    phase_name: str       # "NS", "E", or "W"
    signal_state: str     # "GREEN ON", "YELLOW ON", or "RED ON"
    duration_seconds: float
    ffmpeg_start_path: Path


def _iter_cycle(plan: CurrentPlan) -> Iterable[tuple[int, str, str, tuple[str, ...], float]]:
    """Yield 2-phase (phase_number, phase_name, signal_state, approaches, duration_seconds)."""
    for phase_num, phase_name, state, approaches, field_name in _PHASE_EVENTS:
        yield phase_num, phase_name, state, approaches, plan.duration(field_name)


def _iter_cycle_3(plan: CurrentPlan) -> Iterable[tuple[int, str, str, tuple[str, ...], float]]:
    """Yield 3-phase (phase_number, phase_name, signal_state, approaches, duration_seconds)."""
    for phase_num, phase_name, state, approaches, field_name in _PHASE_EVENTS_3:
        yield phase_num, phase_name, state, approaches, plan.duration(field_name)


def _read_ffmpeg_start(path: Path) -> float | None:
    """Read the float wall-clock timestamp written by ``run_rtsp.sh``.

    Returns None if the file is missing or malformed — the caller should back
    off and retry; this happens briefly if the simulator races the RTSP push
    at startup.
    """
    try:
        text = path.read_text().strip()
    except (OSError, FileNotFoundError):
        return None
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _phase_at_offset(
    plan: CurrentPlan,
    anchor: VideoAnchor,
    offset_in_cycle: float,
) -> tuple[int, str, str, tuple[str, ...], float, float]:
    """Given an offset within the 3-phase cycle (anchor at offset=0), return
    (phase_num, phase_name, state, approaches, phase_duration, elapsed_in_phase).
    """
    # Build the sequence rotated so the anchor entry is first.
    sequence = list(_iter_cycle_3(plan))
    anchor_idx = next(
        (
            i
            for i, (_, name, state, *_rest) in enumerate(sequence)
            if name == anchor.phase_name and state == anchor.signal_state
        ),
        -1,
    )
    if anchor_idx < 0:
        raise ValueError(
            f"VideoAnchor phase/state not in 3-phase sequence: "
            f"phase_name={anchor.phase_name!r} signal_state={anchor.signal_state!r}. "
            f"Valid combinations: NS/E/W × GREEN ON/YELLOW ON/RED ON."
        )
    rotated = sequence[anchor_idx:] + sequence[:anchor_idx]
    t = offset_in_cycle % plan.cycle_seconds_3phase
    for phase_num, phase_name, state, approaches, dur in rotated:
        if t < dur:
            return phase_num, phase_name, state, approaches, dur, t
        t -= dur
    # Floating-point tail — snap to last entry.
    phase_num, phase_name, state, approaches, dur = rotated[-1]
    return phase_num, phase_name, state, approaches, dur, dur


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
        video_anchor: VideoAnchor | None = None,
    ) -> None:
        self.intersection_id = intersection_id
        self.plan = plan
        self.ndjson_path = ndjson_path
        self.video_anchor = video_anchor
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
        try:
            if self.video_anchor is not None:
                self._run_video_anchored(fp)
            else:
                self._run_free(fp)
        finally:
            self.state.running = False
            if fp:
                fp.close()

    def _run_free(self, fp) -> None:
        """Legacy 2-phase free-run (wall-clock ticker)."""
        cycle = 0
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
                self._publish(event, fp)
                deadline = time.monotonic() + dur
                while not self._stop.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.25, remaining))
            cycle += 1

    def _run_video_anchored(self, fp) -> None:
        """3-phase (NS → E → W) driven off the looping source video.

        Each tick, we compute the current video_ts from ``now - ffmpeg_start``
        mod ``video_duration``, derive the phase from the anchor offset, and
        emit a transition event whenever the phase or state changes. The
        event's timestamp is back-dated to the actual phase start so the
        dashboard's progress bar and "X.Xs remaining" display are accurate.
        """
        anchor = self.video_anchor
        assert anchor is not None
        last_key: tuple[str, str] | None = None
        last_cycle: int | None = None
        while not self._stop.is_set():
            ffstart = _read_ffmpeg_start(anchor.ffmpeg_start_path)
            if ffstart is None:
                time.sleep(0.25)
                continue
            now_mono_utc = time.time()
            video_ts = (now_mono_utc - ffstart) % anchor.duration_seconds
            cycle_len = self.plan.cycle_seconds_3phase
            # Elapsed cycles since the anchor aligns us for cycle_number — the
            # anchor frames offset=0 as the start of anchor phase, so
            # cycle_number counts how many full 3-phase cycles have elapsed
            # since ffmpeg kickoff referenced from that anchor.
            elapsed_from_anchor = now_mono_utc - (ffstart + anchor.video_ts_seconds)
            cycle_number = int(elapsed_from_anchor // cycle_len) if elapsed_from_anchor >= 0 else 0
            offset = (video_ts - anchor.video_ts_seconds) % cycle_len
            phase_num, phase_name, state, approaches, dur, elapsed_in_phase = \
                _phase_at_offset(self.plan, anchor, offset)
            key = (phase_name, state)
            if key != last_key or cycle_number != last_cycle:
                # Back-date the timestamp to the phase boundary so the UI's
                # remaining-seconds math is correct even if we caught the
                # phase mid-way through.
                phase_start_dt = datetime.fromtimestamp(
                    now_mono_utc - elapsed_in_phase, tz=timezone.utc
                ).astimezone()
                event = {
                    "timestamp": phase_start_dt.isoformat(timespec="milliseconds"),
                    "intersection_id": self.intersection_id,
                    "cycle_number": cycle_number,
                    "phase_number": phase_num,
                    "phase_name": phase_name,
                    "signal_state": state,
                    "approaches_affected": list(approaches),
                    "duration_seconds": dur,
                    "source": "video_anchored",
                    "video_ts_seconds": round(video_ts, 3),
                }
                self._publish(event, fp)
                last_key = key
                last_cycle = cycle_number
            # Tick fast enough that phase transitions are caught within ~100ms.
            time.sleep(0.1)

    def _publish(self, event: dict, fp) -> None:
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

    # Snapshot helpers ---------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            three_phase = self.video_anchor is not None
            plan = {
                "NS_green": self.plan.NS_green,
                "EW_green": self.plan.EW_green,
                "yellow": self.plan.yellow,
                "all_red": self.plan.all_red,
                "cycle_seconds": round(
                    self.plan.cycle_seconds_3phase if three_phase else self.plan.cycle_seconds,
                    1,
                ),
                "mode": "three_phase" if three_phase else "two_phase",
            }
            if three_phase:
                plan["E_green"] = self.plan.E_green
                plan["W_green"] = self.plan.W_green
            return {
                "running": self.state.running,
                "intersection_id": self.intersection_id,
                "plan": plan,
                "current": self.state.current,
            }

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            data = list(self.state.buffer)
        if limit > 0:
            data = data[-limit:]
        return data
