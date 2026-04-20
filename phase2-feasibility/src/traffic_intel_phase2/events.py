"""Event writer — append-only ndjson event log for detect/track runs.

Mirrors the Phase 1 signal-log event shape so Phase 3 can consume both streams
identically. Lines are flushed on every write so a `tail -f` works in real time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _iso_ms(ts: datetime | None = None) -> str:
    t = ts or datetime.now(timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class EventLog:
    """Line-buffered ndjson writer for detection/tracking/zone events."""

    def __init__(self, path: Path, intersection_id: str = "SITE1") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", buffering=1)  # line-buffered
        self._intersection_id = intersection_id
        self.path = path

    def emit(self, event_type: str, **payload: Any) -> None:
        record = {
            "timestamp": _iso_ms(),
            "intersection_id": self._intersection_id,
            "event_type": event_type,
            **payload,
        }
        self._fh.write(json.dumps(record, default=str) + "\n")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
