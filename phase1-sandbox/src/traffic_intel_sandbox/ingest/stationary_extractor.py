"""Detect & extract stationary-camera segments from a moving-camera video.

Motivation: some sandbox source videos are dashcam drives rather than fixed
CCTV feeds. Within those drives there are usually stretches where the car
is stopped at a red light / parked / standing on a bridge, which approximate
a fixed-camera view of the intersection. This module finds those stretches
and cuts them out as usable fixed-view clips.

Algorithm
---------
1. Sample frames at ``--sample-fps`` (default 2 fps) with OpenCV.
2. Downscale to 320 px wide, convert to grayscale.
3. Compute mean absolute difference between consecutive sampled frames.
4. A frame is *stationary* if its diff < ``--diff-threshold`` (default 6.0
   on a 0–255 scale — tuned for daytime urban footage).
5. Run-length-encode stationary runs. Keep runs whose duration ≥
   ``--min-segment-s`` (default 45 s). A small dilation joins short
   hiccups so a brief jolt doesn't break a long stop.
6. For each kept run, cut the segment with ``ffmpeg -c copy`` into
   ``--out-dir/{src_stem}-stationary-NN.mp4``.

The *content* inside the frame (cars moving across the intersection) is of
course still dynamic — it's only the camera-itself that needs to be still
for downstream fixed-cam processing to work.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def __str__(self) -> str:
        return f"[{self.start_s:7.1f}s → {self.end_s:7.1f}s  ({self.duration_s:5.1f}s)]"


def _ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found on PATH")
    return found


def scan(
    video: Path,
    sample_fps: float = 2.0,
    diff_threshold: float = 6.0,
    min_segment_s: float = 45.0,
    bridge_gap_s: float = 3.0,
    downscale_width: int = 320,
) -> list[Segment]:
    """Return stationary segments discovered in *video*."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cv2 could not open {video}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if native_fps <= 0 or total_frames <= 0:
        raise RuntimeError(f"bad FPS/frame count for {video}: {native_fps}/{total_frames}")
    stride = max(1, int(round(native_fps / sample_fps)))
    step_s = stride / native_fps

    diffs: list[float] = [0.0]   # first sampled frame has no predecessor
    times: list[float] = [0.0]
    prev_small: np.ndarray | None = None
    frame_idx = 0

    while True:
        grabbed = cap.grab()
        if not grabbed:
            break
        if frame_idx % stride == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            scale = downscale_width / frame.shape[1]
            small = cv2.resize(frame, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_small is not None:
                diff = float(cv2.absdiff(small, prev_small).mean())
                diffs.append(diff)
                times.append(frame_idx / native_fps)
            prev_small = small
        frame_idx += 1
    cap.release()

    if len(diffs) < 3:
        return []

    # Boolean mask: stationary or not
    is_stationary = np.array(diffs) < diff_threshold

    # Bridge tiny gaps: if a non-stationary run is shorter than bridge_gap_s,
    # merge neighbouring stationary runs across it.
    bridge_samples = max(1, int(round(bridge_gap_s / step_s)))
    mask = is_stationary.copy()
    i = 0
    while i < len(mask):
        if not mask[i]:
            j = i
            while j < len(mask) and not mask[j]:
                j += 1
            gap_len = j - i
            if i > 0 and j < len(mask) and gap_len <= bridge_samples:
                mask[i:j] = True
            i = j
        else:
            i += 1

    # Run-length encode True runs → segments
    segments: list[Segment] = []
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            start_s = times[i]
            # end of segment = the time of the last stationary sample + 1 sample span
            end_s = times[j - 1] + step_s
            if end_s - start_s >= min_segment_s:
                segments.append(Segment(start_s, end_s))
            i = j
        else:
            i += 1

    return segments


def cut_segments(video: Path, segments: list[Segment], out_dir: Path) -> list[Path]:
    """Cut each segment with ffmpeg -c copy into out_dir. Returns written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for idx, seg in enumerate(segments, start=1):
        out_path = out_dir / f"{video.stem}-stationary-{idx:02d}.mp4"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[cut] skip {out_path.name} (exists)", file=sys.stderr)
            written.append(out_path)
            continue
        cmd = [
            _ffmpeg_bin(),
            "-y",
            "-loglevel", "error",
            "-ss", f"{seg.start_s:.3f}",
            "-i", str(video),
            "-t", f"{seg.duration_s:.3f}",
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
        print(f"[cut] {out_path.name}  {seg}", file=sys.stderr)
        written.append(out_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect stationary camera segments and cut them out.")
    parser.add_argument("--in-dir", type=Path, required=True,
                        help="Directory of input videos (*.mp4)")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Where to write stationary segment clips")
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--diff-threshold", type=float, default=6.0)
    parser.add_argument("--min-segment-s", type=float, default=45.0)
    parser.add_argument("--bridge-gap-s", type=float, default=3.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report segments without cutting")
    args = parser.parse_args(argv)

    videos = sorted(p for p in args.in_dir.iterdir() if p.suffix.lower() == ".mp4")
    if not videos:
        print(f"[scan] no mp4s in {args.in_dir}", file=sys.stderr)
        return 1

    total_segments = 0
    total_seconds = 0.0
    for v in videos:
        print(f"\n[scan] {v.name}", file=sys.stderr)
        try:
            segments = scan(
                v,
                sample_fps=args.sample_fps,
                diff_threshold=args.diff_threshold,
                min_segment_s=args.min_segment_s,
                bridge_gap_s=args.bridge_gap_s,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[scan] FAIL {v.name}: {exc}", file=sys.stderr)
            continue

        if not segments:
            print(f"[scan] {v.name}: no stationary segments ≥ {args.min_segment_s}s", file=sys.stderr)
            continue

        for seg in segments:
            print(f"    {seg}", file=sys.stderr)
            total_segments += 1
            total_seconds += seg.duration_s

        if not args.dry_run:
            cut_segments(v, segments, args.out_dir)

    print(
        f"\n[done] {total_segments} segment(s) total, {total_seconds:.0f}s of fixed-view footage",
        file=sys.stderr,
    )
    return 0 if total_segments > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
