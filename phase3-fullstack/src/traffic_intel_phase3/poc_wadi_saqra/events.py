"""Phase 1 §6.6 event detection layer.

Emits structured events derived from the live tracker + signal simulator +
fusion output:

    * congestion_class_change  - fused class transition per approach
    * queue_spillback          - sustained in-zone overflow
    * abnormal_stopping        - tracks with ~0 motion during GREEN phases
    * wrong_way                - track moving opposite zone direction
    * stalled_vehicle          - track stationary for > stall_seconds
    * incident (composite)     - co-occurrence of the primitives above

Each event is:
    {
      "ts": ISO-8601 +03:00,
      "event_id": "evt_000123",
      "event_type": "...",
      "approach": "N" | "S" | "E" | "W" | null,
      "severity": "info" | "warning" | "critical",
      "confidence": 0.0-1.0,
      "payload": {...},       # type-specific
      "snapshot_hint": { "frame_ts": ..., "bin_start_ts": ... }
    }
"""
from __future__ import annotations

import json
import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

LOG = logging.getLogger(__name__)

# ---------- tuning (centralised so it's easy to inspect/override) ----------

SPILLBACK_QUEUE_THRESHOLD = 20        # cars
SPILLBACK_MIN_DURATION_S = 10.0
STOP_DISP_PX = 3.0                    # centroid displacement considered stationary
STOP_DURATION_S = 8.0                 # stopped for this long while green => abnormal
STALL_DURATION_S = 20.0               # stopped for this long in zone => stalled
WRONG_WAY_HISTORY = 15                # frames of history to infer direction
WRONG_WAY_DOT = -0.30                 # dot(actual, expected) below this => wrong-way
WRONG_WAY_MIN_SPEED_PX_PER_S = 8.0
CONGESTION_HYSTERESIS_S = 5.0         # only emit class change if sustained

_CLASS_RANK = {"free": 0, "light": 1, "moderate": 2, "heavy": 3, "jam": 4}
_DIRECTION_VEC = {
    "up":    (0.0, -1.0),
    "down":  (0.0,  1.0),
    "left":  (-1.0, 0.0),
    "right": ( 1.0, 0.0),
}


def _severity_from_class(cls: str) -> str:
    r = _CLASS_RANK.get(cls, 0)
    if r >= 4:
        return "critical"
    if r >= 3:
        return "warning"
    return "info"


# ---------- detector state ----------


@dataclass
class _CongestionState:
    last_label: str | None = None
    pending_label: str | None = None
    pending_since: float = 0.0


@dataclass
class _SpillbackState:
    above_since: float | None = None


@dataclass
class _TrackHistory:
    positions: deque = field(default_factory=lambda: deque(maxlen=WRONG_WAY_HISTORY))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=WRONG_WAY_HISTORY))
    stationary_since: float | None = None
    last_approach: str | None = None
    stalled_emitted: bool = False
    abnormal_emitted_for_phase_start: float | None = None
    wrong_way_emitted: bool = False


# ---------- engine ----------


class EventEngine:
    def __init__(self, ndjson_path: Path | None = None, buffer_size: int = 500,
                 snapshot_dir: Path | None = None,
                 snapshot_provider: Callable[[], bytes | None] | None = None) -> None:
        self.ndjson_path = ndjson_path
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=buffer_size)
        self._listeners: list[Callable[[dict], None]] = []
        self._event_counter = 0
        self._congestion_state: dict[str, _CongestionState] = defaultdict(_CongestionState)
        self._spillback_state: dict[str, _SpillbackState] = defaultdict(_SpillbackState)
        self._tracks: dict[int, _TrackHistory] = {}
        self._fp = None
        self._snapshot_dir = snapshot_dir
        self._snapshot_provider = snapshot_provider
        if ndjson_path:
            ndjson_path.parent.mkdir(parents=True, exist_ok=True)
            # Seed the counter from the existing NDJSON so new events never
            # clash with historical event_ids (the incidents table INSERT OR
            # IGNORE would silently drop collisions).
            if ndjson_path.exists():
                try:
                    with ndjson_path.open("rb") as fh:
                        # read last ~1MB to find the max evt_NNNNNN id
                        fh.seek(0, 2)
                        size = fh.tell()
                        fh.seek(max(0, size - 1_048_576))
                        tail = fh.read().decode(errors="ignore")
                    import re
                    ids = [int(m) for m in re.findall(r"evt_(\d{6,})", tail)]
                    if ids:
                        self._event_counter = max(ids)
                except Exception:
                    LOG.exception("could not seed event counter from %s", ndjson_path)
            self._fp = ndjson_path.open("a", buffering=1)
        if snapshot_dir:
            snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ---- plumbing -------------------------------------------------------

    def on_event(self, cb: Callable[[dict], None]) -> None:
        self._listeners.append(cb)

    def recent(self, limit: int = 50, event_type: str | None = None) -> list[dict]:
        with self._lock:
            data = list(self._buffer)
        if event_type:
            data = [e for e in data if e.get("event_type") == event_type]
        return data[-limit:] if limit > 0 else data

    def close(self) -> None:
        if self._fp:
            self._fp.close()
            self._fp = None

    def _emit(self, event_type: str, approach: str | None, severity: str,
              confidence: float, payload: dict, snapshot: dict | None = None,
              snapshot_jpeg: bytes | None = None) -> dict:
        with self._lock:
            self._event_counter += 1
            idx = self._event_counter
        now = datetime.now(timezone.utc).astimezone()
        event_id = f"evt_{idx:06d}"
        if snapshot_jpeg is None and self._snapshot_provider is not None:
            try:
                snapshot_jpeg = self._snapshot_provider()
            except Exception:
                LOG.exception("snapshot_provider failed")
        snapshot_uri = None
        if snapshot_jpeg and self._snapshot_dir:
            try:
                self._snapshot_dir.mkdir(parents=True, exist_ok=True)
                p = self._snapshot_dir / f"{event_id}.jpg"
                p.write_bytes(snapshot_jpeg)
                snapshot_uri = f"/event_media/{p.name}"
            except Exception:
                LOG.exception("failed to write event snapshot")
        record = {
            "ts": now.isoformat(timespec="milliseconds"),
            "event_id": event_id,
            "event_type": event_type,
            "approach": approach,
            "severity": severity,
            "confidence": round(confidence, 3),
            "payload": payload,
            "snapshot_hint": snapshot or {},
            "snapshot_uri": snapshot_uri,
        }
        with self._lock:
            self._buffer.append(record)
        if self._fp:
            try:
                self._fp.write(json.dumps(record) + "\n")
            except Exception:
                LOG.exception("failed to persist event")
        for cb in self._listeners:
            try:
                cb(record)
            except Exception:
                LOG.exception("event listener failed")
        return record

    # ---- bin-level detectors (called once per 15s tracker bin) ---------

    def on_bin(self, bin_record: dict, fused: dict[str, dict] | None = None) -> None:
        """``bin_record`` is the dict emitted by TrackerService; ``fused`` is
        the latest /api/fusion ``fused`` dict (per-approach state + class)."""
        bin_end = float(bin_record.get("bin_end", 0.0))
        in_zone = bin_record.get("in_zone", {}) or {}

        # Congestion class-change detection (requires fused classes).
        if fused:
            for approach, state in fused.items():
                cls = state.get("label")
                if not cls:
                    continue
                cs = self._congestion_state[approach]
                if cs.last_label is None:
                    cs.last_label = cls
                    continue
                if cls == cs.last_label:
                    cs.pending_label = None
                    continue
                # New class — require hysteresis before emitting.
                if cs.pending_label != cls:
                    cs.pending_label = cls
                    cs.pending_since = bin_end
                    continue
                if (bin_end - cs.pending_since) >= CONGESTION_HYSTERESIS_S:
                    direction = ("up" if _CLASS_RANK.get(cls, 0) > _CLASS_RANK.get(cs.last_label, 0)
                                 else "down")
                    self._emit(
                        "congestion_class_change",
                        approach=approach,
                        severity=_severity_from_class(cls),
                        confidence=0.85,
                        payload={
                            "from": cs.last_label,
                            "to": cls,
                            "direction": direction,
                            "pressure": state.get("pressure"),
                            "gmaps_label": state.get("gmaps_label"),
                        },
                        snapshot={"bin_end_ts": bin_end},
                    )
                    cs.last_label = cls
                    cs.pending_label = None

        # Queue spillback detection.
        for approach, count in in_zone.items():
            sb = self._spillback_state[approach]
            if count >= SPILLBACK_QUEUE_THRESHOLD:
                if sb.above_since is None:
                    sb.above_since = bin_end
                elif (bin_end - sb.above_since) >= SPILLBACK_MIN_DURATION_S:
                    # Fire once per spillback streak; reset when queue falls.
                    self._emit(
                        "queue_spillback",
                        approach=approach,
                        severity="critical",
                        confidence=0.9,
                        payload={
                            "queue_count": int(count),
                            "threshold": SPILLBACK_QUEUE_THRESHOLD,
                            "duration_s": round(bin_end - sb.above_since, 1),
                        },
                        snapshot={"bin_end_ts": bin_end},
                    )
                    # Mute by pushing above_since forward so we only re-fire after a gap.
                    sb.above_since = bin_end + 30.0
            else:
                sb.above_since = None

    # ---- per-frame detectors ------------------------------------------

    def on_track_frame(
        self,
        ts: float,
        track_ids: list[int],
        centroids: list[tuple[float, float]],
        approach_for_track: dict[int, str | None],
        approach_directions: dict[str, str],
        signal_phase_name: str | None,
        signal_state: str | None,
    ) -> None:
        """Called every tracker frame tick. ``approach_for_track`` maps each
        live track_id to its currently-containing approach (or None).
        ``approach_directions`` is {approach_letter: direction_of_travel}."""
        live_ids = set(track_ids)
        # purge tracks that vanished
        for tid in list(self._tracks.keys()):
            if tid not in live_ids:
                self._tracks.pop(tid, None)

        for tid, xy in zip(track_ids, centroids):
            th = self._tracks.setdefault(tid, _TrackHistory())
            th.positions.append(xy)
            th.timestamps.append(ts)
            appr = approach_for_track.get(tid)
            th.last_approach = appr

            # Stationary heuristic: how long has this track moved < STOP_DISP_PX?
            disp = None
            if len(th.positions) >= 2:
                dx = th.positions[-1][0] - th.positions[0][0]
                dy = th.positions[-1][1] - th.positions[0][1]
                disp = math.hypot(dx, dy)
            if disp is not None and disp < STOP_DISP_PX:
                if th.stationary_since is None:
                    th.stationary_since = th.timestamps[0]
            else:
                th.stationary_since = None
                th.stalled_emitted = False
                th.abnormal_emitted_for_phase_start = None

            stationary_for = (ts - th.stationary_since) if th.stationary_since else 0.0

            # --- abnormal_stopping: stopped during the approach's GREEN phase ---
            if appr and signal_state == "GREEN ON" and signal_phase_name:
                approach_phase = ("NS" if appr in ("N", "S") else "EW")
                if approach_phase == signal_phase_name and stationary_for >= STOP_DURATION_S:
                    # Fire once per GREEN phase start.
                    if th.abnormal_emitted_for_phase_start != th.stationary_since:
                        self._emit(
                            "abnormal_stopping",
                            approach=appr,
                            severity="warning",
                            confidence=0.7,
                            payload={
                                "track_id": int(tid),
                                "stationary_seconds": round(stationary_for, 1),
                                "signal_phase": signal_phase_name,
                                "signal_state": signal_state,
                            },
                            snapshot={"frame_ts": ts},
                        )
                        th.abnormal_emitted_for_phase_start = th.stationary_since

            # --- stalled_vehicle: stopped in zone for very long time ---
            if appr and stationary_for >= STALL_DURATION_S and not th.stalled_emitted:
                self._emit(
                    "stalled_vehicle",
                    approach=appr,
                    severity="warning",
                    confidence=0.8,
                    payload={
                        "track_id": int(tid),
                        "stationary_seconds": round(stationary_for, 1),
                    },
                    snapshot={"frame_ts": ts},
                )
                th.stalled_emitted = True

            # --- wrong_way: track velocity opposite expected zone direction ---
            if appr and not th.wrong_way_emitted and len(th.positions) >= WRONG_WAY_HISTORY:
                dt = th.timestamps[-1] - th.timestamps[0]
                if dt > 0:
                    dx = th.positions[-1][0] - th.positions[0][0]
                    dy = th.positions[-1][1] - th.positions[0][1]
                    speed = math.hypot(dx, dy) / dt
                    if speed >= WRONG_WAY_MIN_SPEED_PX_PER_S:
                        mag = math.hypot(dx, dy) or 1.0
                        vx, vy = dx / mag, dy / mag
                        expected = _DIRECTION_VEC.get(approach_directions.get(appr, ""), (0.0, 0.0))
                        dot = vx * expected[0] + vy * expected[1]
                        if dot <= WRONG_WAY_DOT:
                            self._emit(
                                "wrong_way",
                                approach=appr,
                                severity="critical",
                                confidence=min(0.95, max(0.6, -dot)),
                                payload={
                                    "track_id": int(tid),
                                    "dot_vs_expected": round(dot, 3),
                                    "speed_px_per_s": round(speed, 2),
                                    "expected_direction": approach_directions.get(appr),
                                },
                                snapshot={"frame_ts": ts},
                            )
                            th.wrong_way_emitted = True

    # ---- composite incident classifier --------------------------------

    def classify_recent_incidents(self, window_s: float = 30.0) -> list[dict]:
        """Scan the most recent events and promote co-occurring signals into
        ``incident`` events. Returns the newly-emitted incidents."""
        with self._lock:
            data = list(self._buffer)
        if not data:
            return []
        # Work off last ``window_s`` seconds.
        latest_ts = datetime.fromisoformat(data[-1]["ts"]).timestamp()
        recent = [e for e in data
                  if (latest_ts - datetime.fromisoformat(e["ts"]).timestamp()) <= window_s]
        by_approach: dict[str, list[dict]] = defaultdict(list)
        for e in recent:
            ap = e.get("approach")
            if ap:
                by_approach[ap].append(e)

        promoted: list[dict] = []
        for ap, events in by_approach.items():
            types = {e["event_type"] for e in events}
            # Rule: wrong_way or (spillback + stalled/stopped) => incident
            if "wrong_way" in types:
                promoted.append(self._emit(
                    "incident",
                    approach=ap,
                    severity="critical",
                    confidence=0.9,
                    payload={"cause": "wrong_way", "component_event_types": sorted(types)},
                ))
            elif "queue_spillback" in types and (
                "stalled_vehicle" in types or "abnormal_stopping" in types
            ):
                promoted.append(self._emit(
                    "incident",
                    approach=ap,
                    severity="warning",
                    confidence=0.75,
                    payload={"cause": "spillback_with_stopping",
                             "component_event_types": sorted(types)},
                ))
        return promoted
