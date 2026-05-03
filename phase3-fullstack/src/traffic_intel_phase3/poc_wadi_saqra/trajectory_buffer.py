"""In-process ring buffer of vehicle trajectories + NDJSON sink.

Hooks into the live tracker via the existing ``_on_frame`` callback list
in tracker.py. Open trajectories accumulate centroids until the track
goes idle for ``close_after_idle_s`` seconds, at which point the closed
trajectory is appended to ``data/trajectories.ndjson`` and dropped from
memory.

The lane-induction algorithm (lanes.induce_lanes_from_trajectories)
consumes both the live in-memory open tracks and the recent NDJSON-
persisted closed tracks. Persistence lets us re-induce on a longer
horizon than fits in RAM and gives us replay material for the bench
harness in Phase 4.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class _OpenTrack:
    tid: int
    approach: str | None
    class_name: str | None
    ts: list[float] = field(default_factory=list)
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    last_seen: float = 0.0


class TrajectoryBuffer:
    """Per-process ring buffer of open + recently-closed vehicle trajectories.

    Thread-safe (single internal lock; updates and reads are short).
    """

    def __init__(
        self,
        max_age_s: float = 600.0,
        sink_path: Path | None = None,
        close_after_idle_s: float = 2.0,
    ) -> None:
        self._max_age_s = max_age_s
        self._sink_path = Path(sink_path) if sink_path else None
        self._close_after_idle_s = close_after_idle_s
        self._open: dict[int, _OpenTrack] = {}
        self._closed: list[dict] = []   # closed-trajectory records, newest last
        self._lock = threading.Lock()
        if self._sink_path:
            self._sink_path.parent.mkdir(parents=True, exist_ok=True)

    # ---------------- write ----------------

    def update(
        self,
        now: float,
        track_ids: list[int],
        centroids: list[tuple[float, float]],
        approach_map: dict[int, str | None] | None = None,
        class_map: dict[int, str | None] | None = None,
    ) -> None:
        approach_map = approach_map or {}
        class_map = class_map or {}
        with self._lock:
            live = set(int(t) for t in track_ids)
            for tid, (x, y) in zip(track_ids, centroids):
                tid = int(tid)
                ot = self._open.get(tid)
                if ot is None:
                    ot = _OpenTrack(
                        tid=tid,
                        approach=approach_map.get(tid),
                        class_name=class_map.get(tid),
                    )
                    self._open[tid] = ot
                # Refresh the (potentially-late-bound) approach/class.
                if ot.approach is None and approach_map.get(tid):
                    ot.approach = approach_map.get(tid)
                if ot.class_name is None and class_map.get(tid):
                    ot.class_name = class_map.get(tid)
                ot.ts.append(now)
                ot.xs.append(float(x))
                ot.ys.append(float(y))
                ot.last_seen = now

            # Close any tid that's been idle past the threshold.
            for tid in list(self._open.keys()):
                ot = self._open[tid]
                if tid in live:
                    continue
                if now - ot.last_seen >= self._close_after_idle_s:
                    self._close_track_locked(ot, closed_at=now)

            # Drop oldest closed trajectories beyond the in-memory window
            # (NDJSON keeps them on disk).
            cutoff = now - self._max_age_s
            self._closed = [r for r in self._closed if r["closed_at"] >= cutoff]

    def _close_track_locked(self, ot: _OpenTrack, *, closed_at: float) -> None:
        if len(ot.ts) >= 2:
            rec = {
                "tid": ot.tid,
                "approach": ot.approach,
                "class_name": ot.class_name,
                "opened_at": ot.ts[0],
                "last_seen_at": ot.last_seen,
                "closed_at": closed_at,
                "centroids": [[x, y] for x, y in zip(ot.xs, ot.ys)],
            }
            self._closed.append(rec)
            if self._sink_path:
                with self._sink_path.open("a") as fp:
                    fp.write(json.dumps(rec) + "\n")
        self._open.pop(ot.tid, None)

    # ---------------- read ----------------

    def open_trajectories(self) -> dict[int, dict]:
        """Snapshot of currently-live open tracks (centroids as ndarray)."""
        with self._lock:
            return {
                tid: {
                    "tid": ot.tid,
                    "approach": ot.approach,
                    "class_name": ot.class_name,
                    "centroids": np.column_stack([ot.xs, ot.ys])
                    if ot.xs else np.zeros((0, 2)),
                }
                for tid, ot in self._open.items()
            }

    def recent_closed_trajectories(
        self, now: float | None = None, window_s: float | None = None
    ) -> list[dict]:
        """Return closed-track records inside ``window_s`` of ``now``.

        ``now`` defaults to the most recent close; ``window_s`` defaults
        to ``max_age_s``. Each returned record is a deep-enough copy that
        callers can mutate without affecting the buffer.
        """
        with self._lock:
            if not self._closed:
                return []
            if now is None:
                now = self._closed[-1]["closed_at"]
            if window_s is None:
                window_s = self._max_age_s
            cutoff = now - window_s
            return [
                {**r, "centroids": np.array(r["centroids"], dtype=float)}
                for r in self._closed
                if r["closed_at"] >= cutoff
            ]

    def all_trajectories_for_induction(self, *, max_from_disk: int = 800) -> list[dict]:
        """Concatenated open + closed (in-memory + on-disk) trajectories in
        the format ``induce_lanes_from_trajectories`` expects.

        Reads the tail of ``trajectories.ndjson`` so that the first
        calibration after a process restart gets historical context
        instead of waiting for the in-memory ring to refill.
        """
        out: list[dict] = []
        seen_tids: set[int] = set()
        # In-memory recent closed.
        for r in self.recent_closed_trajectories():
            seen_tids.add(int(r["tid"]))
            out.append({
                "tid": r["tid"],
                "approach": r["approach"],
                "class_name": r["class_name"],
                "centroids": r["centroids"],
            })
        # In-memory open.
        for tid, ot in self.open_trajectories().items():
            if len(ot["centroids"]) >= 3 and int(tid) not in seen_tids:
                seen_tids.add(int(tid))
                out.append(ot)
        # On-disk tail. Reads up to max_from_disk last records and skips
        # tids we already have in memory (avoid duplicates).
        if self._sink_path and self._sink_path.exists():
            try:
                lines = self._sink_path.read_text().splitlines()[-max_from_disk:]
                for line in lines:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    tid = int(rec.get("tid", -1))
                    if tid in seen_tids:
                        continue
                    seen_tids.add(tid)
                    cents = np.array(rec.get("centroids") or [], dtype=float)
                    if len(cents) < 3:
                        continue
                    out.append({
                        "tid": tid,
                        "approach": rec.get("approach"),
                        "class_name": rec.get("class_name"),
                        "centroids": cents,
                    })
            except Exception:
                pass
        return out
