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
import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

from .events import EventLog
from .zones import load_stop_lines, load_zones

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
) -> dict:
    """Run detect + track. Returns a summary dict."""

    device = device or _select_device()
    print(f"[phase2] loading {model_name} on device={device}", file=sys.stderr)
    model = YOLO(model_name)

    # Build overlay annotators up front (supervision)
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.45, text_thickness=1, text_padding=3)
    trace_annotator = sv.TraceAnnotator(trace_length=30, thickness=1)

    # Zones + lines from Phase 1 metadata (if present)
    zones: list = []
    lines: list = []
    if metadata_path and metadata_path.exists():
        try:
            zones = load_zones(metadata_path)
            lines = load_stop_lines(metadata_path)
            print(
                f"[phase2] loaded {len(zones)} zones, {len(lines)} stop-lines "
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

    # Summary accumulators
    started = time.monotonic()
    frame_count = 0
    det_count_total = 0
    track_ids_seen: set[int] = set()
    latencies_ms: list[float] = []
    line_crossings: dict[str, int] = {n.approach: 0 for n in lines}
    zone_counts_running: dict[str, int] = {z.name: 0 for z in zones}

    try:
        stream = model.track(
            source=source,
            tracker=tracker,
            classes=list(VEHICLE_CLASSES),
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            device=device,
            persist=True,
            stream=True,
            verbose=False,
        )

        for result in stream:
            t0 = time.monotonic()
            frame = result.orig_img  # BGR numpy array
            if frame is None:
                continue

            detections = sv.Detections.from_ultralytics(result)
            n_det = len(detections)
            det_count_total += n_det
            if detections.tracker_id is not None:
                track_ids_seen.update(int(t) for t in detections.tracker_id if t is not None)

            # Line crossings
            for named in lines:
                named.line.trigger(detections)
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

            # Zone occupancy
            for named in zones:
                mask = named.zone.trigger(detections)
                inside = int(mask.sum())
                prev = zone_counts_running[named.name]
                zone_counts_running[named.name] = inside
                if event_log and inside != prev:
                    event_log.emit(
                        "zone_occupancy",
                        name=named.name, kind=named.kind,
                        count=inside, prev=prev, frame=frame_count,
                    )

            # Annotate (only if we need a video)
            if video_out or show_overlay:
                annotated = frame.copy()
                labels = [
                    f"#{int(tid)} {model.names.get(int(cid), cid)} {c:.2f}"
                    for tid, cid, c in zip(
                        detections.tracker_id if detections.tracker_id is not None
                            else [-1] * n_det,
                        detections.class_id if detections.class_id is not None
                            else [-1] * n_det,
                        detections.confidence if detections.confidence is not None
                            else [0.0] * n_det,
                    )
                ]
                annotated = trace_annotator.annotate(annotated, detections=detections)
                annotated = box_annotator.annotate(annotated, detections=detections)
                annotated = label_annotator.annotate(annotated, detections=detections, labels=labels)
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
    p.add_argument("--show", action="store_true", help="Show annotated window (requires GUI)")
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
