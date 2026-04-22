"""Reads an RTSP stream, runs YOLO + ByteTrack, maintains per-approach counts.

Designed to run as a thread inside the FastAPI process. Publishes:
  - a rolling snapshot dict (latest counts, fps, frame timestamp)
  - the last annotated JPEG (for MJPEG preview)
  - a file-tail-friendly NDJSON log of 15-second bins
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..acquisition.metrics import shared as _shared_ingest_metrics
from .counters import ApproachCounter, Zone, load_zones

LOG = logging.getLogger(__name__)

VEHICLE_CLASSES = (2, 3, 5, 7)  # COCO: car, motorcycle, bus, truck
APPROACH_BGR = {
    "S": (102, 255, 136),   # RGB #66ff88 green
    "N": (122, 122, 255),   # RGB #ff7a7a red
    "E": (60, 165, 245),    # RGB #f5a53c orange
    "W": (203, 172, 74),    # RGB #4aaccb blue
}


@dataclass
class TrackerConfig:
    rtsp_url: str
    model_path: Path
    zones_path: Path
    ingest_fps: float = 10.0
    bin_seconds: int = 15
    counts_ndjson: Path | None = None
    tracker_yaml: str = "bytetrack.yaml"
    imgsz: int = 960


@dataclass
class TrackerState:
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    crossings_in_current_bin: dict[str, int] = field(default_factory=dict)
    fps: float = 0.0
    frame_ts: float = 0.0
    bin_start_ts: float = 0.0
    bin_seconds: int = 15
    last_jpeg: bytes | None = None
    running: bool = False
    last_error: str | None = None


class TrackerService:
    def __init__(self, cfg: TrackerConfig) -> None:
        self.cfg = cfg
        self.state = TrackerState(bin_seconds=cfg.bin_seconds)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._on_bin: list[Callable[[dict], None]] = []
        self._on_frame: list[Callable[[float, list[int], list[tuple[float, float]], dict[int, str | None], dict[str, str]], None]] = []

    def on_bin(self, cb: Callable[[dict], None]) -> None:
        self._on_bin.append(cb)

    def on_frame(
        self,
        cb: Callable[[float, list[int], list[tuple[float, float]], dict[int, str | None], dict[str, str]], None],
    ) -> None:
        self._on_frame.append(cb)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ---------------- internal -----------------

    def _run(self) -> None:
        from ultralytics import YOLO  # lazy so import cost is deferred

        try:
            zones: list[Zone] = load_zones(self.cfg.zones_path)
        except Exception as exc:
            self.state.last_error = f"zones: {exc}"
            LOG.exception("failed to load zones")
            return

        counter = ApproachCounter(zones)
        model = YOLO(str(self.cfg.model_path))

        metrics = _shared_ingest_metrics()
        metrics.mark_started("video")
        cap = cv2.VideoCapture(self.cfg.rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            self.state.last_error = f"cannot open rtsp: {self.cfg.rtsp_url}"
            metrics.mark_error("video", self.state.last_error)
            LOG.error(self.state.last_error)
            return

        self.state.running = True
        ingest_period = 1.0 / max(self.cfg.ingest_fps, 1.0)
        last_ingest = 0.0
        fps_window: deque[float] = deque(maxlen=30)
        bin_start = time.time()
        self.state.bin_start_ts = bin_start
        ndjson_fp = None
        if self.cfg.counts_ndjson:
            self.cfg.counts_ndjson.parent.mkdir(parents=True, exist_ok=True)
            ndjson_fp = self.cfg.counts_ndjson.open("a", buffering=1)

        per_approach_crossings_prev = {z.approach: 0 for z in zones}

        try:
            while not self._stop.is_set():
                ok = cap.grab()
                if not ok:
                    metrics.mark_drop("video")
                    metrics.mark_reconnect("video")
                    metrics.mark_error("video", "rtsp grab failed")
                    # Handbook §8.1: reconnect within 5-10 s.
                    cap.release()
                    # Brief pause before reopen; the RTSP server usually comes
                    # back in <1s after a push-side restart.
                    time.sleep(5.0)
                    cap = cv2.VideoCapture(self.cfg.rtsp_url, cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    continue
                now = time.time()
                if (now - last_ingest) < ingest_period:
                    continue
                last_ingest = now

                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    metrics.mark_drop("video")
                    continue
                metrics.mark_ok("video")

                t0 = time.time()
                results = model.track(
                    frame,
                    persist=True,
                    tracker=self.cfg.tracker_yaml,
                    classes=list(VEHICLE_CLASSES),
                    imgsz=self.cfg.imgsz,
                    conf=0.35,
                    verbose=False,
                )
                res = results[0]
                boxes = res.boxes
                track_ids: list[int] = []
                centroids: list[tuple[float, float]] = []
                if boxes is not None and boxes.id is not None:
                    ids_arr = boxes.id.cpu().numpy().astype(int)
                    xyxy = boxes.xyxy.cpu().numpy()
                    for i, tid in enumerate(ids_arr):
                        x1, y1, x2, y2 = xyxy[i]
                        cx = (x1 + x2) * 0.5
                        cy = (y1 + y2) * 0.5
                        track_ids.append(int(tid))
                        centroids.append((cx, cy))

                counter.update(track_ids, centroids)
                snap = counter.snapshot()
                with self._lock:
                    self.state.counts = snap
                    self.state.frame_ts = now
                    fps_window.append(now)
                    if len(fps_window) >= 2:
                        self.state.fps = (len(fps_window) - 1) / max(fps_window[-1] - fps_window[0], 1e-3)
                    self.state.last_jpeg = self._annotate_jpeg(frame, res, zones, snap)

                if self._on_frame:
                    approach_map = counter.approach_map()
                    direction_map = counter.direction_map()
                    for cb in self._on_frame:
                        try:
                            cb(now, track_ids, centroids, approach_map, direction_map)
                        except Exception:
                            LOG.exception("on_frame callback failed")

                # 15-second bin emit
                if now - bin_start >= self.cfg.bin_seconds:
                    bin_counts = {
                        a: snap[a]["crossings_total"] - per_approach_crossings_prev.get(a, 0)
                        for a in snap
                    }
                    per_approach_crossings_prev = {a: snap[a]["crossings_total"] for a in snap}
                    bin_record = {
                        "bin_start": bin_start,
                        "bin_end": now,
                        "seconds": self.cfg.bin_seconds,
                        "in_zone": {a: snap[a]["in_zone"] for a in snap},
                        "crossings_in_bin": bin_counts,
                        "crossings_total": {a: snap[a]["crossings_total"] for a in snap},
                        "fps": round(self.state.fps, 2),
                    }
                    with self._lock:
                        self.state.crossings_in_current_bin = bin_counts
                        self.state.bin_start_ts = now
                    bin_start = now
                    if ndjson_fp:
                        ndjson_fp.write(json.dumps(bin_record) + "\n")
                    for cb in self._on_bin:
                        try:
                            cb(bin_record)
                        except Exception:
                            LOG.exception("on_bin callback failed")

                _ = t0  # timing reserved for future profiling
        finally:
            self.state.running = False
            cap.release()
            if ndjson_fp:
                ndjson_fp.close()

    # ---------------- annotation -----------------

    def _annotate_jpeg(
        self, frame: np.ndarray, res, zones: list[Zone], snap: dict[str, dict[str, int]]
    ) -> bytes:
        img = frame.copy()

        # zones (translucent polygons + labels)
        overlay = img.copy()
        for z in zones:
            color = APPROACH_BGR.get(z.approach, (200, 200, 200))
            cv2.fillPoly(overlay, [z.polygon], color)
            cv2.polylines(img, [z.polygon], True, color, 2)
            if z.stop_line:
                cv2.line(img, z.stop_line[0], z.stop_line[1], (0, 255, 255), 3)
        img = cv2.addWeighted(overlay, 0.20, img, 0.80, 0)

        # boxes + IDs
        boxes = res.boxes
        if boxes is not None and boxes.id is not None:
            ids_arr = boxes.id.cpu().numpy().astype(int)
            xyxy = boxes.xyxy.cpu().numpy().astype(int)
            for i, tid in enumerate(ids_arr):
                x1, y1, x2, y2 = xyxy[i]
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(img, f"#{tid}", (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)

        # HUD: per-approach counters
        pad = 10
        for i, (a, v) in enumerate(snap.items()):
            color = APPROACH_BGR.get(a, (200, 200, 200))
            txt = f"{a}: in={v['in_zone']}  cross={v['crossings_total']}"
            y = 30 + i * 30
            cv2.rectangle(img, (pad, y - 22), (pad + 360, y + 6), (0, 0, 0), -1)
            cv2.putText(img, txt, (pad + 6, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else b""
