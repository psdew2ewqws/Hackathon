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
from .counters import ApproachCounter, Zone, load_lane_zones, load_zones

LOG = logging.getLogger(__name__)

# Vehicle-class filtering now lives inside each DetectorBackend (because
# YOLO uses 80-class COCO indexing and RF-DETR uses 91-class). We keep this
# constant only for backward-compat reads from external code.
VEHICLE_CLASSES = (2, 3, 5, 7)
APPROACH_BGR = {
    "S": (102, 255, 136),   # RGB #66ff88 green
    "N": (122, 122, 255),   # RGB #ff7a7a red
    "E": (60, 165, 245),    # RGB #f5a53c orange
    "W": (203, 172, 74),    # RGB #4aaccb blue
}

# Per-class palette (BGR). Each common COCO vehicle / actor gets a distinct
# hue so the toggle comparison is also a class-coverage comparison at a
# glance. The dict is consulted by the lowercased class name; anything
# unknown falls back to FALLBACK_CLASS_BGR.
CLASS_BGR = {
    "car":         ( 80, 220, 100),   # bright green
    "truck":       (255, 140,  80),   # bright blue
    "bus":         (110,  90, 240),   # warm pink/red
    "motorcycle":  ( 60, 200, 240),   # amber
    "bicycle":     (220, 200,  90),   # cyan
    "person":      ( 80, 130, 240),   # orange (matches the rfdetr promo)
    "traffic light": (200, 200, 200),
    "stop sign":   ( 30,  30, 220),
}
FALLBACK_CLASS_BGR = (200, 200, 200)


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
    counts: dict[str, dict] = field(default_factory=dict)
    crossings_in_current_bin: dict[str, int] = field(default_factory=dict)
    # PCE-weighted analog of crossings_in_current_bin (Phase 1 of
    # production-readiness plan). Populated from snapshot diffs when the
    # 15-second bin closes.
    crossings_pce_in_current_bin: dict[str, float] = field(default_factory=dict)
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
        # Populated when the worker thread initializes the detector — used
        # to render the backend tag in the HUD overlay so operators can
        # see at a glance which detector is producing the boxes.
        self._backend_label: str = "?"
        # Hot-swap state: only one detector lives in VRAM at a time. The
        # worker swaps it (free → load) when _pending_backend changes.
        # _available_backends advertises what can be requested even before
        # the worker has loaded each one.
        self._backends: dict = {}
        self._byte_trackers: dict = {}
        self._available_backends: list[str] = ["ultralytics", "rfdetr"]
        self._active_backend: str = ""
        # Trajectory buffer (Phase 1.5): accumulates per-tid centroid paths
        # so the lane-induction algorithm can cluster them. Populated via
        # the existing _on_frame callback registered in start().
        self.trajectory_buffer = None  # type: ignore[assignment]
        # Counter is created inside _run(); the server reads it to expose
        # measured lane counts to Webster, lane state via /api/lanes/state, etc.
        self.counter = None  # type: ignore[assignment]
        self._pending_backend: str | None = None
        self._backend_lock = threading.Lock()

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

    def list_backends(self) -> dict:
        with self._backend_lock:
            return self._snapshot_backend_state_locked()

    def set_backend(self, name: str) -> dict:
        with self._backend_lock:
            if name not in self._available_backends:
                raise ValueError(
                    f"unknown backend {name!r}; available: {self._available_backends}"
                )
            if name == self._active_backend:
                return self._snapshot_backend_state_locked()
            self._pending_backend = name
            LOG.info("backend switch requested: %s -> %s", self._active_backend, name)
            return self._snapshot_backend_state_locked()

    def _snapshot_backend_state_locked(self) -> dict:
        return {
            "active": self._active_backend,
            "available": list(self._available_backends),
            "loaded": list(self._backends.keys()),
            "pending": self._pending_backend,
            "label": self._backend_label,
        }

    def _update_backend_label_locked(self) -> None:
        """Refresh the HUD label string from the currently-active detector."""
        if not self._active_backend or self._active_backend not in self._backends:
            self._backend_label = "?"
            return
        info = self._backends[self._active_backend].info()
        if info.get("backend") == "rfdetr":
            self._backend_label = f"RFDETR-{info.get('size', '?').upper()}"
        elif info.get("backend") == "ultralytics":
            from pathlib import Path as _P
            self._backend_label = f"ULTRALYTICS {_P(info.get('weights', '?')).stem}"
        else:
            self._backend_label = info.get("backend", "?").upper()

    # ---------------- internal -----------------

    def _run(self) -> None:
        # Lazy: detector + tracker imports defer model construction (which
        # downloads weights for rfdetr on first use) until the thread starts.
        import os as _os

        from traffic_intel_detector import build_detector, build_tracker
        # Phase 1.5 fix B: ORB+RANSAC homography keeps saved zone polygons
        # glued to road features when the camera drifts. Reused as-is from
        # phase 2 (no new dep, no logic duplication).
        from traffic_intel_phase2.homography import CameraTracker

        from .trajectory_buffer import TrajectoryBuffer

        try:
            zones: list[Zone] = load_zones(self.cfg.zones_path)
            lane_zones = load_lane_zones(self.cfg.zones_path)
        except Exception as exc:
            self.state.last_error = f"zones: {exc}"
            LOG.exception("failed to load zones")
            return

        counter = ApproachCounter(zones, lane_zones=lane_zones)
        self.counter = counter  # expose to the server for measured lane counts
        if lane_zones:
            LOG.info("loaded %d lane sub-zones across approaches", len(lane_zones))

        # Phase 1.5 fix B: camera-motion tracker. update_every=2 keeps it
        # cheap (~3-5ms per call); ORB extraction would otherwise add up.
        camera_tracker = CameraTracker(
            n_features=1200, smoothing=0.4, update_every=2,
        )
        camera_initialized = False
        # Trajectory buffer (Phase 1.5): persists closed tracks beside
        # counts.ndjson so the lane-induction algorithm can re-cluster on
        # historical data, not just whatever's live in memory right now.
        traj_sink = (
            self.cfg.counts_ndjson.parent / "trajectories.ndjson"
            if self.cfg.counts_ndjson else None
        )
        self.trajectory_buffer = TrajectoryBuffer(
            max_age_s=600.0, sink_path=traj_sink, close_after_idle_s=2.0
        )

        # Lazy-load: only one backend lives in VRAM at a time. On swap we
        # tear down the previous one (del + cuda.empty_cache) before
        # constructing the new one. On a 6 GB GPU this is mandatory —
        # holding both detectors plus their JIT/optimization caches has
        # been observed to wedge the driver.
        AVAILABLE_BACKENDS = ("ultralytics", "rfdetr")
        initial_choice = _os.environ.get("DETECTOR_BACKEND", "rfdetr").lower()
        if initial_choice not in AVAILABLE_BACKENDS:
            initial_choice = "rfdetr"
        _os.environ.setdefault("YOLO_WEIGHTS", str(self.cfg.model_path))

        def _load_backend(spec: str):
            _os.environ["DETECTOR_BACKEND"] = spec
            det = build_detector()
            byt = build_tracker(frame_rate=int(self.cfg.ingest_fps))
            return det, byt

        def _free_active_backend_locked() -> None:
            """Release the active detector's GPU memory before loading another."""
            try:
                for k in list(self._backends.keys()):
                    self._backends.pop(k, None)
                    self._byte_trackers.pop(k, None)
                import gc
                gc.collect()
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                LOG.exception("error freeing previous backend")

        try:
            det, byt = _load_backend(initial_choice)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("failed to load initial backend %s: %s",
                          initial_choice, exc)
            self.state.last_error = f"detector load failed: {exc}"
            return

        with self._backend_lock:
            # Available backends are advertised statically — the worker
            # may not have loaded them yet, but the API needs to know what
            # the user can ask for.
            self._backends[initial_choice] = det
            self._byte_trackers[initial_choice] = byt
            self._active_backend = initial_choice
            self._available_backends = list(AVAILABLE_BACKENDS)
            self._update_backend_label_locked()
        LOG.info("phase3 initial backend=%s", self._active_backend)

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
        per_approach_pce_crossings_prev = {z.approach: 0.0 for z in zones}

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
                # Camera-motion homography: reproject saved zone polygons
                # so they stay glued to road features even when the camera
                # drifts. set_reference is implicit on first update().
                if not camera_initialized:
                    camera_tracker.set_reference(frame)
                    camera_initialized = True
                else:
                    camera_tracker.update(frame)
                for _z in counter.zones:
                    _z.runtime_polygon = camera_tracker.transform_polygon(_z.polygon)
                    if _z.stop_line is not None:
                        _z.runtime_stop_line = camera_tracker.transform_line(
                            _z.stop_line[0], _z.stop_line[1]
                        )
                for _approach_lanes in counter.lane_zones.values():
                    for _lz in _approach_lanes:
                        _lz.runtime_polygon = camera_tracker.transform_polygon(_lz.polygon)
                        if _lz.centerline.size > 0:
                            _lz.runtime_centerline = camera_tracker.transform_polygon(
                                _lz.centerline.astype(np.int32)
                            )

                # Hot-swap point: if the API thread requested a different
                # backend, free the active one's VRAM, then load the new
                # one. The HUD reflects "label = LOADING …" while the
                # constructor runs so the operator sees the wait.
                with self._backend_lock:
                    pending = self._pending_backend
                    if pending and pending != self._active_backend:
                        old = self._active_backend
                        self._backend_label = f"LOADING {pending.upper()}…"
                # Run the heavy load OUTSIDE the lock so the API can still
                # answer GET /api/tracker/backend during the swap.
                if pending and pending != self._active_backend:
                    LOG.info("backend swap starting %s -> %s", old, pending)
                    _free_active_backend_locked()
                    try:
                        new_det, new_byt = _load_backend(pending)
                    except Exception as exc:  # noqa: BLE001
                        LOG.exception("backend swap to %s failed; reverting", pending)
                        self.state.last_error = f"swap to {pending} failed: {exc}"
                        # Try to bring the previous backend back so the
                        # tracker doesn't go silent.
                        try:
                            new_det, new_byt = _load_backend(old)
                        except Exception:  # noqa: BLE001
                            LOG.exception("could not restore previous backend %s", old)
                            with self._backend_lock:
                                self._pending_backend = None
                                self._active_backend = ""
                                self._backend_label = "FAILED"
                            return
                        with self._backend_lock:
                            self._backends[old] = new_det
                            self._byte_trackers[old] = new_byt
                            self._active_backend = old
                            self._pending_backend = None
                            self._update_backend_label_locked()
                        continue
                    with self._backend_lock:
                        self._backends[pending] = new_det
                        self._byte_trackers[pending] = new_byt
                        self._active_backend = pending
                        self._pending_backend = None
                        self._byte_trackers[pending].reset()
                        counter.reset_all()
                        per_approach_crossings_prev = {z.approach: 0 for z in zones}
                        per_approach_pce_crossings_prev = {z.approach: 0.0 for z in zones}
                        self._update_backend_label_locked()
                    LOG.info("backend swap complete: now %s", pending)
                with self._backend_lock:
                    active_name = self._active_backend
                detector = self._backends[active_name]
                tracker = self._byte_trackers[active_name]
                detections = detector.detect(frame)
                tracked = tracker.update(detections, frame)
                track_ids: list[int] = []
                centroids: list[tuple[float, float]] = []
                class_names: list[str] = []
                if tracked.tracker_id is not None and len(tracked) > 0:
                    xyxy = tracked.xyxy
                    cls_arr = (tracked.data.get("class_name")
                               if tracked.data else None)
                    for i, tid in enumerate(tracked.tracker_id):
                        if tid is None:
                            continue
                        x1, y1, x2, y2 = xyxy[i]
                        track_ids.append(int(tid))
                        centroids.append(((x1 + x2) * 0.5, (y1 + y2) * 0.5))
                        cls = (str(cls_arr[i]) if cls_arr is not None and i < len(cls_arr) else "car")
                        class_names.append(cls)

                counter.update(track_ids, centroids, class_names=class_names)
                # Feed the trajectory buffer (Phase 1.5 lane induction).
                if self.trajectory_buffer is not None and track_ids:
                    approach_map_for_buf = counter.approach_map()
                    class_map_for_buf = {
                        tid: cls for tid, cls in zip(track_ids, class_names)
                    }
                    self.trajectory_buffer.update(
                        now=now,
                        track_ids=track_ids,
                        centroids=centroids,
                        approach_map=approach_map_for_buf,
                        class_map=class_map_for_buf,
                    )
                snap = counter.snapshot()
                with self._lock:
                    self.state.counts = snap
                    self.state.frame_ts = now
                    fps_window.append(now)
                    if len(fps_window) >= 2:
                        self.state.fps = (len(fps_window) - 1) / max(fps_window[-1] - fps_window[0], 1e-3)
                    self.state.last_jpeg = self._annotate_jpeg(frame, tracked, zones, snap)

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
                    bin_pce_crossings = {
                        a: round(
                            snap[a]["crossings_pce_total"]
                            - per_approach_pce_crossings_prev.get(a, 0.0),
                            2,
                        )
                        for a in snap
                    }
                    per_approach_crossings_prev = {a: snap[a]["crossings_total"] for a in snap}
                    per_approach_pce_crossings_prev = {
                        a: snap[a]["crossings_pce_total"] for a in snap
                    }
                    bin_record = {
                        "bin_start": bin_start,
                        "bin_end": now,
                        "seconds": self.cfg.bin_seconds,
                        "in_zone": {a: snap[a]["in_zone"] for a in snap},
                        "crossings_in_bin": bin_counts,
                        "crossings_total": {a: snap[a]["crossings_total"] for a in snap},
                        # PCE-weighted aggregates (Phase 1 of production-readiness plan).
                        "in_zone_pce": {a: snap[a]["in_zone_pce"] for a in snap},
                        "crossings_pce_in_bin": bin_pce_crossings,
                        "crossings_pce_total": {a: snap[a]["crossings_pce_total"] for a in snap},
                        "mix": {a: snap[a]["mix"] for a in snap},
                        "fps": round(self.state.fps, 2),
                    }
                    with self._lock:
                        self.state.crossings_in_current_bin = bin_counts
                        self.state.crossings_pce_in_current_bin = bin_pce_crossings
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
        self, frame: np.ndarray, tracked, zones: list[Zone], snap: dict[str, dict[str, int]]
    ) -> bytes:
        img = frame.copy()

        # Approach polygons: dim them down once lanes have been calibrated
        # — the lane sub-polygons take over as the primary visual signal.
        has_lanes = bool(self.counter and self.counter.lane_zones
                         and any(self.counter.lane_zones.values()))
        approach_alpha = 0.10 if has_lanes else 0.20

        overlay = img.copy()
        for z in zones:
            color = APPROACH_BGR.get(z.approach, (200, 200, 200))
            zpoly = z.runtime_polygon if z.runtime_polygon is not None else z.polygon
            zline = z.runtime_stop_line if z.runtime_stop_line is not None else z.stop_line
            cv2.fillPoly(overlay, [zpoly], color)
            cv2.polylines(img, [zpoly], True, color, 2)
            if zline:
                cv2.line(img, zline[0], zline[1], (0, 255, 255), 3)
        img = cv2.addWeighted(overlay, approach_alpha, img, 1.0 - approach_alpha, 0)

        # Lane sub-polygons (Phase 1.5): drawn on top of the approach
        # zones with a stronger fill so the operator sees them clearly.
        # Per-lane color follows lane_type (left=blue, through=green,
        # right=amber) — same palette as the LaneCalibrationPage.
        LANE_BGR_BY_TYPE = {
            "left":    (250, 165,  96),   # blue (BGR)
            "through": (128, 222,  74),   # green
            "right":   ( 36, 191, 251),   # amber
            "shared":  (184, 163, 148),   # slate
        }
        if has_lanes:
            lane_overlay = img.copy()
            for approach, lane_list in (self.counter.lane_zones or {}).items():
                for lz in lane_list:
                    lcolor = LANE_BGR_BY_TYPE.get(lz.lane_type, LANE_BGR_BY_TYPE["shared"])
                    lpoly = lz.runtime_polygon if lz.runtime_polygon is not None else lz.polygon
                    cv2.fillPoly(lane_overlay, [lpoly], lcolor)
                    cv2.polylines(img, [lpoly], True, lcolor, 2)
            img = cv2.addWeighted(lane_overlay, 0.28, img, 0.72, 0)
            # Lane labels at centerline midpoint (runtime if available).
            for approach, lane_list in (self.counter.lane_zones or {}).items():
                for lz in lane_list:
                    cl = lz.runtime_centerline if lz.runtime_centerline is not None else lz.centerline
                    if cl is None or cl.size == 0:
                        continue
                    mid = cl[len(cl) // 2]
                    px, py = int(mid[0]), int(mid[1])
                    label = f"{lz.lane_id} {lz.lane_type}"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    cv2.rectangle(img, (px - 2, py - th - 6), (px + tw + 4, py + 2), (10, 14, 22), -1)
                    cv2.putText(img, label, (px + 2, py - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        # boxes + class fills + labels from supervision.Detections.
        # Filled interior is rendered to a separate overlay so we can blend
        # it back at low alpha — that gives the rfdetr-promo look without
        # actually running instance segmentation. Outline + label go on
        # top of the blended frame so they stay crisp.
        if len(tracked) > 0:
            xyxy_int = tracked.xyxy.astype(int)
            class_ids = tracked.class_id if tracked.class_id is not None else None
            confidences = tracked.confidence if tracked.confidence is not None else None
            cls_names = (tracked.data.get("class_name")
                         if tracked.data else None)
            tids = tracked.tracker_id

            box_overlay = img.copy()
            n = len(tracked)
            for i in range(n):
                x1, y1, x2, y2 = xyxy_int[i]
                cls_name = (
                    str(cls_names[i]).lower() if cls_names is not None and i < len(cls_names) else
                    str(int(class_ids[i])) if class_ids is not None else "?"
                )
                color = CLASS_BGR.get(cls_name, FALLBACK_CLASS_BGR)
                cv2.rectangle(box_overlay, (x1, y1), (x2, y2), color, -1)
            # Blend fills (~35% opacity) before drawing outlines/labels.
            img = cv2.addWeighted(box_overlay, 0.35, img, 0.65, 0)

            for i in range(n):
                x1, y1, x2, y2 = xyxy_int[i]
                cls_name = (
                    str(cls_names[i]) if cls_names is not None and i < len(cls_names) else
                    str(int(class_ids[i])) if class_ids is not None else "?"
                )
                color = CLASS_BGR.get(cls_name.lower(), FALLBACK_CLASS_BGR)
                conf = float(confidences[i]) if confidences is not None and i < len(confidences) else 0.0
                tid = int(tids[i]) if tids is not None and tids[i] is not None and i < len(tids) else None

                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

                tag = f"#{tid} " if tid is not None else ""
                label = f"{tag}{cls_name} {conf:.2f}"
                (tw, th), _ = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                lx1, ly1 = x1, max(0, y1 - th - 8)
                lx2, ly2 = x1 + tw + 10, ly1 + th + 8
                cv2.rectangle(img, (lx1, ly1), (lx2, ly2), color, -1)
                cv2.putText(img, label, (lx1 + 5, ly2 - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 14, 22), 1,
                            cv2.LINE_AA)

        # HUD: backend tag + per-approach counters
        pad = 10
        backend_txt = f"DETECTOR: {self._backend_label}"
        cv2.rectangle(img, (pad, 4), (pad + 360, 30), (0, 0, 0), -1)
        cv2.putText(img, backend_txt, (pad + 6, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2, cv2.LINE_AA)
        for i, (a, v) in enumerate(snap.items()):
            color = APPROACH_BGR.get(a, (200, 200, 200))
            txt = f"{a}: in={v['in_zone']}  cross={v['crossings_total']}"
            y = 60 + i * 30
            cv2.rectangle(img, (pad, y - 22), (pad + 360, y + 6), (0, 0, 0), -1)
            cv2.putText(img, txt, (pad + 6, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else b""
