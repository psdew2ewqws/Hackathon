"""Phase 2 detect+track runner.

Pulls frames from an RTSP (or any ffmpeg-readable) source, runs Ultralytics
YOLO26 detection with BoT-SORT multi-object tracking, annotates each frame
with bounding boxes + track IDs + stop-line counters, and emits structured
events to an ndjson log.

Typical usage:

    phase2-detect \\
        --source rtsp://localhost:8554/site1 \\
        --model  yolo26n.pt \\
        --tracker botsort.yaml \\
        --metadata phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \\
        --events-out data/events/phase2.ndjson \\
        --video-out  /tmp/phase2-annotated.mp4 \\
        --max-frames 600
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from .events import EventLog
from .homography import CameraTracker
from .zones import load_lane_lines, load_lane_zones, load_stop_lines, load_zones


class _MjpegBroadcaster:
    """Thread-safe latest-frame buffer + HTTP MJPEG server.

    One writer (the detector) updates the latest frame; many readers (the
    browser tabs) pull it via /stream.mjpeg as multipart/x-mixed-replace.
    We only ever hold the most recent frame — slow readers never block fast
    producers, they just see dropped frames.
    """

    # Snapshot sink — Chromium in this VM SIGILLs on multipart/x-mixed-replace,
    # so the viewer polls this file over plain HTTP instead of the MJPEG stream.
    _LATEST_SNAPSHOT = Path("/tmp/traffic-intel-phase2-latest.jpg")
    _SNAPSHOT_EVERY = 3  # write ~every Nth frame to limit disk I/O

    def __init__(self, port: int, jpeg_quality: int = 72) -> None:
        self.port = port
        self._jpeg_quality = jpeg_quality
        self._cv = threading.Condition()
        self._latest_jpeg: bytes | None = None
        self._stop = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._snapshot_ctr = 0

    @classmethod
    def _write_latest(cls, jpeg_bytes: bytes) -> None:
        try:
            tmp = cls._LATEST_SNAPSHOT.with_suffix(".tmp.jpg")
            tmp.write_bytes(jpeg_bytes)
            tmp.replace(cls._LATEST_SNAPSHOT)
        except Exception:
            pass

    def update(self, bgr_frame: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", bgr_frame,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
        if not ok:
            return
        jpeg_bytes = buf.tobytes()
        with self._cv:
            self._latest_jpeg = jpeg_bytes
            self._cv.notify_all()
        # Atomic snapshot sink (every Nth frame) — consumed by the dashboard.
        self._snapshot_ctr = (self._snapshot_ctr + 1) % self._SNAPSHOT_EVERY
        if self._snapshot_ctr == 0:
            self._write_latest(jpeg_bytes)

    def _wait_for_frame(self, timeout: float = 5.0) -> bytes | None:
        with self._cv:
            if self._latest_jpeg is None:
                self._cv.wait(timeout=timeout)
            return self._latest_jpeg

    @staticmethod
    def _handler_cls(broadcaster: "_MjpegBroadcaster"):
        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args): pass

            # Any exception in handle() should just end the connection — never
            # propagate up and tear down the producer loop.
            def handle_one_request(self):  # noqa: N802
                try:
                    return super().handle_one_request()
                except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                    return
                except Exception:
                    return

            def do_GET(self):  # noqa: N802
                if self.path.startswith("/stream.mjpeg"):
                    boundary = "frame"
                    try:
                        self.send_response(200)
                        self.send_header("Age", "0")
                        self.send_header("Cache-Control", "no-cache, private")
                        self.send_header("Pragma", "no-cache")
                        self.send_header("Content-Type",
                                         f"multipart/x-mixed-replace; boundary={boundary}")
                        self.end_headers()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return
                    while not broadcaster._stop.is_set():
                        jpeg = broadcaster._wait_for_frame(timeout=1.0)
                        if jpeg is None:
                            continue
                        try:
                            self.wfile.write(
                                f"--{boundary}\r\n".encode()
                                + b"Content-Type: image/jpeg\r\n"
                                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                                + jpeg
                                + b"\r\n"
                            )
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                            return
                        except Exception:
                            return
                elif self.path in ("/", "/index.html"):
                    html = (
                        b"<!doctype html><meta charset=utf-8>"
                        b"<title>Phase 2 live</title>"
                        b"<style>body{margin:0;background:#000}img{width:100%;height:100vh;object-fit:contain}</style>"
                        b"<img src=/stream.mjpeg>"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self.send_response(404); self.end_headers()
        return H

    def start(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port),
                                           self._handler_cls(self))
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        print(f"[mjpeg] serving on http://127.0.0.1:{self.port}/stream.mjpeg",
              file=sys.stderr)

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()

# COCO class IDs for the vehicle subset we actually care about.
# 2=car, 3=motorcycle, 5=bus, 7=truck
VEHICLE_CLASSES = (2, 3, 5, 7)
DEFAULT_MODEL = "yolo26n.pt"
DEFAULT_TRACKER = "botsort.yaml"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_METADATA = REPO_ROOT / "phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"


def _select_device() -> str:
    """'0' if a CUDA GPU is available, else 'cpu'."""
    try:
        import torch  # noqa: WPS433 (local import on demand)
        if torch.cuda.is_available():
            return "0"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def run(
    source: str,
    model_name: str = DEFAULT_MODEL,
    tracker: str = DEFAULT_TRACKER,
    metadata_path: Path | None = None,
    events_out: Path | None = None,
    video_out: Path | None = None,
    conf: float = 0.3,
    iou: float = 0.5,
    imgsz: int = 640,
    max_frames: int | None = None,
    device: str | None = None,
    show_overlay: bool = False,
    mjpeg_port: int | None = None,
    half: bool | None = None,
    homography: bool = True,
) -> dict:
    """Run detect + track. Returns a summary dict."""

    device = device or _select_device()
    # FP16 auto-enables on GPU (2–3× throughput, minimal accuracy cost); off on CPU.
    if half is None:
        half = device != "cpu"
    print(f"[phase2] loading {model_name} on device={device} half={half}", file=sys.stderr)
    model = YOLO(model_name)

    # Build overlay annotators up front (supervision)
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.45, text_thickness=1, text_padding=3)
    trace_annotator = sv.TraceAnnotator(trace_length=30, thickness=1)

    # Zones + lines from Phase 1 metadata (if present)
    zones: list = []
    lines: list = []
    lane_lines: list = []
    lane_zones: list = []
    if metadata_path and metadata_path.exists():
        try:
            zones = load_zones(metadata_path)
            lines = load_stop_lines(metadata_path)
            lane_lines = load_lane_lines(metadata_path)
            lane_zones = load_lane_zones(metadata_path)
            print(
                f"[phase2] loaded {len(zones)} zones, {len(lines)} stop-lines, "
                f"{len(lane_lines)} lane sub-lines, {len(lane_zones)} lane zones "
                f"from {metadata_path.name}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[phase2] WARN could not load metadata: {exc}", file=sys.stderr)

    zone_annotators = [
        sv.PolygonZoneAnnotator(zone=z.zone, color=sv.Color.RED, thickness=2, text_thickness=1, text_scale=0.4)
        for z in zones
    ]
    line_annotator = sv.LineZoneAnnotator(thickness=2, text_scale=0.5)

    # Event log
    event_log: EventLog | None = None
    if events_out:
        event_log = EventLog(events_out)
        event_log.emit("run_start", source=source, model=model_name, tracker=tracker,
                       device=device, conf=conf, iou=iou)

    # Video writer (lazy — we need first frame to get size)
    writer: cv2.VideoWriter | None = None
    writer_size: tuple[int, int] | None = None

    # MJPEG broadcaster (optional — live browser view)
    mjpeg: _MjpegBroadcaster | None = None
    if mjpeg_port:
        mjpeg = _MjpegBroadcaster(port=mjpeg_port)
        mjpeg.start()

    # Summary accumulators
    started = time.monotonic()
    frame_count = 0
    det_count_total = 0
    track_ids_seen: set[int] = set()
    latencies_ms: list[float] = []
    line_crossings: dict[str, int] = {n.approach: 0 for n in lines}
    zone_counts_running: dict[str, int] = {z.name: 0 for z in zones}
    lane_crossings_running: dict[str, int] = {ll.lane_id: 0 for ll in lane_lines}

    # ── Camera motion tracker ─────────────────────────────────────────
    # The site JSON defines all zones in the reference-frame pixel space.
    # The RTSP feed (TheVideo.mp4 looped) pans/zooms, so we homography-
    # warp every polygon per frame before drawing + counting.
    camera = CameraTracker(update_every=2, smoothing=0.4, n_features=1200)

    def _line_endpoints(line_zone) -> tuple[tuple[int, int], tuple[int, int]]:
        """Pull (x0, y0), (x1, y1) out of an sv.LineZone regardless of
        which supervision version exposes which attribute names."""
        if hasattr(line_zone, "vector"):
            v = line_zone.vector
            return ((int(v.start.x), int(v.start.y)),
                    (int(v.end.x),   int(v.end.y)))
        return ((int(line_zone.start.x), int(line_zone.start.y)),
                (int(line_zone.end.x),   int(line_zone.end.y)))

    # Cache reference-frame geometry so we always warp from the same
    # source (avoids warping-the-warped drift).
    lane_zone_ref_polys = [lz.polygon.copy() for lz in lane_zones]
    lane_line_ref_pts   = [_line_endpoints(ll.line) for ll in lane_lines]
    stop_line_ref_pts   = [_line_endpoints(n.line)  for n in lines]
    zone_ref_polys      = [z.polygon.copy() if z.polygon is not None else None
                           for z in zones]

    try:
        stream = model.track(
            source=source,
            tracker=tracker,
            classes=list(VEHICLE_CLASSES),
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            device=device,
            half=half,
            persist=True,
            stream=True,
            verbose=False,
        )

        for result in stream:
            t0 = time.monotonic()
            frame = result.orig_img  # BGR numpy array
            if frame is None:
                continue

            # Camera motion: update homography when enabled. For static
            # cameras (e.g. TheVideo.mp4) we skip it — the reference-frame
            # polygons are the source of truth and ORB keypoint noise would
            # just add jitter.
            if homography:
                camera.update(frame)
                warped_lane_polys = [
                    camera.transform_polygon(p) for p in lane_zone_ref_polys]
                warped_zone_polys = [
                    camera.transform_polygon(p) if p is not None else None
                    for p in zone_ref_polys]
                warped_stop_line_pts = [
                    camera.transform_line(p0, p1) for p0, p1 in stop_line_ref_pts]
                warped_lane_line_pts = [
                    camera.transform_line(p0, p1) for p0, p1 in lane_line_ref_pts]
            else:
                # Identity — use the reference-frame coords untouched.
                warped_lane_polys = [p.copy() for p in lane_zone_ref_polys]
                warped_zone_polys = [p.copy() if p is not None else None
                                     for p in zone_ref_polys]
                warped_stop_line_pts = list(stop_line_ref_pts)
                warped_lane_line_pts = list(lane_line_ref_pts)
            # Sync sv.LineZone endpoints so trigger() uses the warped line.
            # The in/out counters stay preserved — we only mutate geometry.
            # supervision's LineZone stores positions as .start and .end
            # (sv.Point). Some versions cache them as .vector internally; we
            # defensively refresh both without constructing sv.Vector
            # (which isn't available in all supervision releases).
            def _set_endpoints(line_zone, wx0, wy0, wx1, wy1):
                try:
                    line_zone.start = sv.Point(float(wx0), float(wy0))
                    line_zone.end   = sv.Point(float(wx1), float(wy1))
                except Exception:
                    pass
                # If the LineZone has a .vector with mutable start/end, patch it too
                v = getattr(line_zone, "vector", None)
                if v is not None:
                    try:
                        if hasattr(v, "start") and hasattr(v.start, "x"):
                            v.start.x = float(wx0); v.start.y = float(wy0)
                        if hasattr(v, "end") and hasattr(v.end, "x"):
                            v.end.x = float(wx1); v.end.y = float(wy1)
                    except Exception:
                        pass

            for named, ((wx0, wy0), (wx1, wy1)) in zip(lines, warped_stop_line_pts):
                _set_endpoints(named.line, wx0, wy0, wx1, wy1)
            for ll, ((wx0, wy0), (wx1, wy1)) in zip(lane_lines, warped_lane_line_pts):
                _set_endpoints(ll.line, wx0, wy0, wx1, wy1)
            # sv.PolygonZone caches a mask at __init__ and doesn't refresh
            # when .polygon is mutated — plus our NamedZone / NamedLaneZone
            # dataclasses are frozen. Build fresh PolygonZone instances keyed
            # by name / lane_id each frame; trigger() against the fresh one.
            fresh_lane_zones: dict[str, sv.PolygonZone] = {}
            for lz, wpoly in zip(lane_zones, warped_lane_polys):
                if wpoly is not None and len(wpoly) >= 3:
                    try:
                        fresh_lane_zones[lz.lane_id] = sv.PolygonZone(polygon=wpoly)
                    except Exception:
                        pass
            fresh_big_zones: dict[str, sv.PolygonZone] = {}
            for nz, wpoly in zip(zones, warped_zone_polys):
                if wpoly is not None and len(wpoly) >= 3:
                    try:
                        fresh_big_zones[nz.name] = sv.PolygonZone(polygon=wpoly)
                    except Exception:
                        pass

            detections = sv.Detections.from_ultralytics(result)
            n_det = len(detections)
            det_count_total += n_det
            if detections.tracker_id is not None:
                track_ids_seen.update(int(t) for t in detections.tracker_id if t is not None)

            # Line crossings — LineZone needs tracker_id; skip rows without it
            tracked_for_lines = detections
            if detections.tracker_id is not None and len(detections) > 0:
                m = np.array([t is not None for t in detections.tracker_id])
                tracked_for_lines = detections[m] if m.any() else None
            for named in lines:
                if tracked_for_lines is not None and len(tracked_for_lines) > 0:
                    named.line.trigger(tracked_for_lines)
                crossed = int(named.line.in_count) + int(named.line.out_count)
                if crossed != line_crossings[named.approach]:
                    delta = crossed - line_crossings[named.approach]
                    line_crossings[named.approach] = crossed
                    if event_log:
                        event_log.emit(
                            "stop_line_crossing",
                            approach=named.approach,
                            delta=delta,
                            in_count=int(named.line.in_count),
                            out_count=int(named.line.out_count),
                            frame=frame_count,
                        )

            # Per-lane subdivision — each approach's polyline is split into
            # N equal segments (one per lane). Emit a lane_crossing event
            # every time any lane segment's total count changes.
            for ll in lane_lines:
                if tracked_for_lines is not None and len(tracked_for_lines) > 0:
                    ll.line.trigger(tracked_for_lines)
                ll_total = int(ll.line.in_count) + int(ll.line.out_count)
                if ll_total != lane_crossings_running[ll.lane_id]:
                    delta = ll_total - lane_crossings_running[ll.lane_id]
                    lane_crossings_running[ll.lane_id] = ll_total
                    if event_log:
                        event_log.emit(
                            "lane_crossing",
                            approach=ll.approach,
                            lane_id=ll.lane_id,
                            lane_type=ll.lane_type,
                            lane_idx=ll.lane_idx,
                            delta=delta,
                            in_count=int(ll.line.in_count),
                            out_count=int(ll.line.out_count),
                            frame=frame_count,
                        )

            # Zone occupancy — prefer freshly-built warped zone, fall back
            # to the cached reference zone if the warped copy is bad.
            for named in zones:
                zone_for_count = fresh_big_zones.get(named.name) or named.zone
                mask = zone_for_count.trigger(detections)
                inside = int(mask.sum())
                prev = zone_counts_running[named.name]
                zone_counts_running[named.name] = inside
                if event_log and inside != prev:
                    event_log.emit(
                        "zone_occupancy",
                        name=named.name, kind=named.kind,
                        count=inside, prev=prev, frame=frame_count,
                    )

            # Annotate (only if we need a video, mjpeg stream, or on-screen)
            if video_out or show_overlay or mjpeg is not None:
                annotated = frame.copy()

                has_tracker_ids = (
                    detections.tracker_id is not None
                    and len(detections) > 0
                    and any(t is not None for t in detections.tracker_id)
                )

                # Build labels. Include "#id" prefix only when we actually have it.
                n_all = len(detections)
                labels: list[str] = []
                for i in range(n_all):
                    tid = None
                    if detections.tracker_id is not None and i < len(detections.tracker_id):
                        raw_tid = detections.tracker_id[i]
                        if raw_tid is not None:
                            tid = int(raw_tid)
                    cid = int(detections.class_id[i]) if detections.class_id is not None else -1
                    conf = float(detections.confidence[i]) if detections.confidence is not None else 0.0
                    name = model.names.get(cid, str(cid))
                    tag = f"#{tid} " if tid is not None else ""
                    labels.append(f"{tag}{name} {conf:.2f}")

                if has_tracker_ids:
                    # Keep only rows that have a tracker_id for the trace.
                    mask = np.array([t is not None for t in detections.tracker_id])
                    tracked_subset = detections[mask]
                    if len(tracked_subset) > 0:
                        annotated = trace_annotator.annotate(annotated, detections=tracked_subset)

                annotated = box_annotator.annotate(annotated, detections=detections)
                annotated = label_annotator.annotate(annotated, detections=detections, labels=labels)

                # Per-lane colored heat-map — instantaneous occupancy
                # (warped lane polygons follow camera motion)
                # Per-approach instantaneous occupancy — emit once per second
                # as the primary live signal for the dashboard.
                lane_counts_now: dict[str, int] = {}
                approach_occupancy_now: dict[str, int] = {
                    "N": 0, "S": 0, "E": 0, "W": 0,
                }
                if lane_zones:
                    overlay = annotated.copy()
                    for lz, wpoly in zip(lane_zones, warped_lane_polys):
                        zone_for_count = fresh_lane_zones.get(lz.lane_id) or lz.zone
                        try:
                            mask = zone_for_count.trigger(detections)
                            n_in = int(mask.sum())
                        except Exception:
                            n_in = 0
                        lane_counts_now[lz.lane_id] = n_in
                        if   n_in == 0: color = (80, 200,  80)
                        elif n_in <= 2: color = (80, 230, 220)
                        elif n_in <= 4: color = (80, 220, 240)
                        elif n_in <= 8: color = (60, 140, 240)
                        else:           color = (60,  60, 230)
                        cv2.fillPoly(overlay, [wpoly], color)
                        cx = int(wpoly[:, 0].mean())
                        cy = int(wpoly[:, 1].mean())
                        cv2.putText(overlay, str(n_in), (cx - 10, cy + 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                    (255, 255, 255), 2, cv2.LINE_AA)
                    annotated = cv2.addWeighted(overlay, 0.30, annotated, 0.70, 0)

                # Aggregate per-approach instantaneous counts from the lanes
                for lid, v in lane_counts_now.items():
                    a = lid.split("-")[0] if "-" in lid else None
                    if a in approach_occupancy_now:
                        approach_occupancy_now[a] += v

                # Emit a per-second approach_occupancy event so the dashboard
                # can surface "cars waiting at each stop" as the primary
                # live metric. Throttle to every 15 frames (~1s at 15fps).
                if event_log and frame_count % 15 == 0:
                    for a, n in approach_occupancy_now.items():
                        event_log.emit(
                            "approach_occupancy",
                            approach=a,
                            count=int(n),
                            frame=frame_count,
                        )

                # N/S/E/W big labels at warped approach zone centroids
                # Use ASCII-only text (Hershey fonts don't render Unicode),
                # colour-code per compass direction for at-a-glance clarity.
                approach_label = {
                    "N": "NORTH", "S": "SOUTH",
                    "E": "EAST",  "W": "WEST",
                }
                approach_bgr = {
                    "N": (232, 180, 100),   # amber
                    "S": (100, 180, 232),   # sky blue
                    "E": (120, 220, 140),   # green
                    "W": (200, 140, 255),   # purple
                }
                for nz, wpoly in zip(zones, warped_zone_polys):
                    if (not nz.name.startswith("queue_spillback_")
                            or wpoly is None):
                        continue
                    approach = nz.name.split("_")[-1]
                    total = sum(
                        v for k, v in lane_counts_now.items()
                        if k.startswith(f"{approach}-")
                    )
                    cx = int(wpoly[:, 0].mean())
                    cy = int(wpoly[:, 1].mean())
                    label = approach_label.get(approach, approach)
                    color = approach_bgr.get(approach, (200, 200, 200))

                    # Two-line label: "NORTH" + "N cars: 0"
                    top_text = label
                    bot_text = f"{total} cars"
                    (tw1, th1), _ = cv2.getTextSize(
                        top_text, cv2.FONT_HERSHEY_SIMPLEX, 1.3, 3)
                    (tw2, th2), _ = cv2.getTextSize(
                        bot_text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
                    box_w = max(tw1, tw2) + 28
                    box_h = th1 + th2 + 30
                    x0, y0 = cx - box_w // 2, cy - box_h // 2
                    x1, y1 = cx + box_w // 2, cy + box_h // 2
                    # Solid dark background so white text is readable even
                    # on top of the colored zone fills
                    cv2.rectangle(annotated, (x0, y0), (x1, y1),
                                  (14, 18, 26), -1)
                    cv2.rectangle(annotated, (x0, y0), (x1, y1),
                                  color, 3)
                    # Top line — direction in the approach colour
                    cv2.putText(annotated, top_text,
                                (cx - tw1 // 2, y0 + th1 + 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3,
                                cv2.LINE_AA)
                    # Bottom line — count in white
                    cv2.putText(annotated, bot_text,
                                (cx - tw2 // 2, y1 - 9),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                (255, 255, 255), 2, cv2.LINE_AA)

                for za in zone_annotators:
                    annotated = za.annotate(scene=annotated)
                for named in lines:
                    annotated = line_annotator.annotate(frame=annotated, line_counter=named.line)

                if video_out:
                    if writer is None:
                        h, w = annotated.shape[:2]
                        writer_size = (w, h)
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        writer = cv2.VideoWriter(str(video_out), fourcc, 10.0, writer_size)
                        print(f"[phase2] writing annotated video → {video_out}  ({w}x{h})",
                              file=sys.stderr)
                    writer.write(annotated)
                if mjpeg is not None:
                    mjpeg.update(annotated)
                if show_overlay:
                    cv2.imshow("phase2", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

            latencies_ms.append((time.monotonic() - t0) * 1000.0)
            frame_count += 1

            if frame_count % 30 == 0:
                fps_so_far = frame_count / max(time.monotonic() - started, 1e-6)
                print(
                    f"[phase2] frame={frame_count}  det={n_det}  "
                    f"tracks={len(track_ids_seen)}  fps={fps_so_far:5.2f}  "
                    f"lines={sum(line_crossings.values())}",
                    file=sys.stderr,
                )
            if max_frames is not None and frame_count >= max_frames:
                break

    finally:
        if writer:
            writer.release()
        if show_overlay:
            cv2.destroyAllWindows()
        if mjpeg is not None:
            mjpeg.stop()

    elapsed = time.monotonic() - started
    summary = {
        "frames": frame_count,
        "elapsed_s": round(elapsed, 3),
        "fps": round(frame_count / max(elapsed, 1e-6), 2),
        "detections_total": det_count_total,
        "unique_tracks": len(track_ids_seen),
        "latency_ms": {
            "mean": round(float(np.mean(latencies_ms or [0.0])), 2),
            "p50":  round(float(np.percentile(latencies_ms or [0.0], 50)), 2),
            "p95":  round(float(np.percentile(latencies_ms or [0.0], 95)), 2),
        },
        "line_crossings": line_crossings,
        "video_out": str(video_out) if video_out else None,
        "events_out": str(events_out) if events_out else None,
    }

    if event_log:
        event_log.emit("run_end", **summary)
        event_log.close()
    print(f"[phase2] done {summary}", file=sys.stderr)
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 2 — YOLO26 detect+track on RTSP / video.")
    p.add_argument("--source", default=os.environ.get("RTSP_URL", "rtsp://localhost:8554/site1"))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--tracker", default=DEFAULT_TRACKER, help="botsort.yaml or bytetrack.yaml")
    p.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    p.add_argument("--events-out", type=Path, default=None)
    p.add_argument("--video-out", type=Path, default=None)
    p.add_argument("--conf", type=float, default=0.3)
    p.add_argument("--iou", type=float, default=0.5)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--max-frames", type=int, default=None,
                   help="Stop after N frames (useful for benchmarking)")
    p.add_argument("--device", default=None, help="'0' (GPU), 'cpu', or None (auto)")
    p.add_argument("--half", dest="half", action="store_true", default=None,
                   help="Force FP16 inference (default: auto — on for GPU, off for CPU)")
    p.add_argument("--no-half", dest="half", action="store_false",
                   help="Disable FP16 even on GPU")
    p.add_argument("--show", action="store_true", help="Show annotated window (requires GUI)")
    p.add_argument("--mjpeg-port", type=int, default=None,
                   help="Also serve annotated frames as MJPEG on http://127.0.0.1:<port>/stream.mjpeg")
    p.add_argument("--no-homography", dest="homography", action="store_false",
                   default=True,
                   help="Disable camera-motion homography tracking (use for static feeds)")
    args = p.parse_args(argv)

    run(
        source=args.source,
        model_name=args.model,
        tracker=args.tracker,
        metadata_path=args.metadata,
        events_out=args.events_out,
        video_out=args.video_out,
        conf=args.conf,
        iou=args.iou,
        imgsz=args.imgsz,
        max_frames=args.max_frames,
        device=args.device,
        show_overlay=args.show,
        mjpeg_port=args.mjpeg_port,
        half=args.half,
        homography=args.homography,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
