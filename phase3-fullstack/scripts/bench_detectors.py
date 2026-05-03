"""Side-by-side detector benchmark.

Runs every requested backend over the same N-second window of a video source,
under the same supervision.ByteTrack config, with the same zone definitions.
Each backend gets its own annotated MP4 plus per-frame metrics. Comparison
across backends is then a CSV diff.

Usage:
    python phase3-fullstack/scripts/bench_detectors.py \\
        --source data/calibration_pack/real/img_5210/full.mp4 \\
        --zones  phase3-fullstack/configs/wadi_saqra_zones.json \\
        --seconds 30 \\
        --backends ultralytics,rfdetr-base,rfdetr-large \\
        --out-dir bench/
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "phase3-fullstack" / "src"))

# All paths below are anchored to REPO_ROOT so the script works from any CWD.
DEFAULT_SOURCE = REPO_ROOT / "data" / "calibration_pack" / "real" / "img_5210" / "full.mp4"


def _approach_for(zones, cx: float, cy: float):
    """Return the zone.approach a centroid falls inside (or None)."""
    pt = (float(cx), float(cy))
    for z in zones:
        if cv2.pointPolygonTest(z.polygon, pt, False) >= 0:
            return z.approach
    return None


def _make_backend(spec: str):
    """spec is one of: 'ultralytics' | 'rfdetr-base' | 'rfdetr-large'."""
    if spec == "ultralytics":
        os.environ["DETECTOR_BACKEND"] = "ultralytics"
    elif spec.startswith("rfdetr-"):
        os.environ["DETECTOR_BACKEND"] = "rfdetr"
        os.environ["RFDETR_SIZE"] = spec.split("-", 1)[1]
    else:
        raise ValueError(f"unknown backend spec {spec!r}")

    # Re-import factory each call so env-driven config takes effect cleanly.
    from importlib import reload

    import traffic_intel_detector.factory as fac
    reload(fac)
    return fac.build_detector(), fac.build_tracker(frame_rate=10)


def _gpu_mem_mb():
    try:
        import torch

        if torch.cuda.is_available():
            return float(torch.cuda.memory_allocated() / 1e6)
    except Exception:
        pass
    return 0.0


def _annotate(frame, det, snap):
    img = frame.copy()
    if det.tracker_id is not None and len(det) > 0:
        xyxy = det.xyxy.astype(int)
        for i, tid in enumerate(det.tracker_id):
            if tid is None:
                continue
            x1, y1, x2, y2 = xyxy[i]
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(img, f"#{int(tid)}", (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
    pad = 10
    for i, (a, n) in enumerate(snap.items()):
        y = 30 + i * 26
        cv2.rectangle(img, (pad, y - 20), (pad + 220, y + 5), (0, 0, 0), -1)
        cv2.putText(img, f"{a}: {n}", (pad + 6, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    return img


def run_one(spec: str, source: str, zones, seconds: int, out_dir: Path) -> dict:
    print(f"\n=== {spec} ===", flush=True)
    detector, tracker = _make_backend(spec)

    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {source}")
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    target_frames = int(round(seconds * fps_in))

    # Warmup on one frame so cold-load latency doesn't pollute the run.
    ok, warm = cap.read()
    if not ok:
        raise RuntimeError("could not read first frame")
    detector.warmup(warm)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    tracker.reset()

    out_path = out_dir / f"{spec}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps_in, (width, height))

    per_frame = []
    crossings = {z.approach: 0 for z in zones}
    in_zone_now = {z.approach: 0 for z in zones}
    seen_in_zone: dict[int, set[str]] = {}  # tid -> approaches it has been seen in
    track_ids = set()
    total_dets = 0

    t_run = time.time()
    for fi in range(target_frames):
        ok, frame = cap.read()
        if not ok or frame is None:
            break

        t0 = time.time()
        det = detector.detect(frame)
        det = tracker.update(det, frame)
        latency_ms = (time.time() - t0) * 1000.0
        total_dets += len(det)

        in_zone_now = {z.approach: 0 for z in zones}
        if det.tracker_id is not None and len(det) > 0:
            xyxy = det.xyxy
            for i, tid in enumerate(det.tracker_id):
                if tid is None:
                    continue
                tid = int(tid)
                track_ids.add(tid)
                x1, y1, x2, y2 = xyxy[i]
                cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
                approach = _approach_for(zones, cx, cy)
                if approach is None:
                    continue
                in_zone_now[approach] += 1
                seen = seen_in_zone.setdefault(tid, set())
                if approach not in seen:
                    seen.add(approach)
                    crossings[approach] += 1

        per_frame.append({
            "frame": fi,
            "latency_ms": round(latency_ms, 2),
            "n_det": int(len(det)),
            "vram_mb": round(_gpu_mem_mb(), 1),
        })
        writer.write(_annotate(frame, det, in_zone_now))

    writer.release()
    cap.release()
    elapsed = time.time() - t_run

    lat = np.array([r["latency_ms"] for r in per_frame], dtype=np.float64)
    nframes = len(per_frame)
    summary = {
        "backend": spec,
        "frames": nframes,
        "elapsed_s": round(elapsed, 2),
        "fps_mean": round(nframes / max(elapsed, 1e-6), 2),
        "latency_p50_ms": round(float(np.percentile(lat, 50)) if lat.size else 0.0, 2),
        "latency_p95_ms": round(float(np.percentile(lat, 95)) if lat.size else 0.0, 2),
        "vram_peak_mb": round(max((r["vram_mb"] for r in per_frame), default=0.0), 1),
        "total_detections": int(total_dets),
        "unique_tracks": int(len(track_ids)),
        "video_out": str(out_path),
        **{f"crossings_{a}": v for a, v in crossings.items()},
    }
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def parse_args():
    p = argparse.ArgumentParser(description="Side-by-side detector benchmark.")
    p.add_argument("--source", default=str(DEFAULT_SOURCE))
    p.add_argument("--zones", required=True, help="phase-3 zones JSON path")
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument(
        "--backends",
        default="ultralytics,rfdetr-base",
        help="comma-separated: ultralytics,rfdetr-base,rfdetr-large",
    )
    p.add_argument("--out-dir", default=None,
                   help="defaults to bench/<UTC timestamp>/")
    return p.parse_args()


def main():
    args = parse_args()

    from traffic_intel_phase3.poc_wadi_saqra.counters import load_zones

    zones = load_zones(Path(args.zones))
    out_dir = Path(args.out_dir or REPO_ROOT / "bench" /
                   datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out_dir.mkdir(parents=True, exist_ok=True)

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    rows = []
    for spec in backends:
        try:
            rows.append(run_one(spec, args.source, zones, args.seconds, out_dir))
        except Exception as exc:
            print(f"[bench] {spec} FAILED: {exc}", file=sys.stderr)
            rows.append({"backend": spec, "error": str(exc)})

    # CSV
    csv_path = out_dir / "summary.csv"
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Manifest
    import platform
    try:
        import torch
        gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        torch_v = torch.__version__
    except Exception:
        gpu, torch_v = None, None
    manifest = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "zones": args.zones,
        "seconds": args.seconds,
        "backends": backends,
        "host": platform.node(),
        "gpu": gpu,
        "torch": torch_v,
        "python": sys.version.split()[0],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\n[bench] done → {out_dir}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
