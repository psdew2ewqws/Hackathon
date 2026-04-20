"""Video stabilization — turn a shaky / slowly-moving camera into a 'virtual CCTV'.

For Phase-1 source videos that are dashcam drives or handheld tours rather than
proper fixed CCTV footage, this module applies a two-pass point-feature-based
stabilizer:

    1. For each consecutive pair of frames, detect good features in the first
       frame (``cv2.goodFeaturesToTrack``) and track them into the next with
       Lucas-Kanade optical flow (``cv2.calcOpticalFlowPyrLK``).
    2. From matched points, estimate a rigid (rotation + translation) transform
       using ``cv2.estimateAffinePartial2D`` (RANSAC).
    3. Integrate per-frame transforms into a cumulative trajectory.
    4. Smooth the trajectory with a moving-average filter (window =
       ``--smooth-radius`` frames on each side).
    5. Warp every frame by `smoothed − original` so the background stays still.

This is the classic two-pass rigid stabilizer described in the OpenCV docs and
Grundmann et al. 2011 ("auto-directed video stabilization with robust L1
optimal camera paths"). It collapses engine vibration and slow drift into a
near-fixed view, producing a convincing CCTV-like output for any video where
the camera is *roughly* framing one scene.

Limitations documented in methodology.md:
    • Does not re-frame different intersections as one — if the source
      traverses multiple locations, stabilization just smooths each stretch.
    • Aggressive warps leave black borders; we crop inward by ``--crop-pct``.
    • Not a true perspective change; for top-down CCTV use ``warp_homography``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

DEFAULT_SMOOTH_RADIUS = 30
DEFAULT_CROP_PCT = 4.0  # percent, applied per side


def _estimate_transforms(cap: cv2.VideoCapture) -> np.ndarray:
    """Estimate (dx, dy, dtheta) for each frame transition."""
    ok, prev = cap.read()
    if not ok:
        raise RuntimeError("cannot read first frame")
    prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)

    transforms: list[tuple[float, float, float]] = []
    while True:
        ok, curr = cap.read()
        if not ok:
            break
        curr_gray = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY)

        prev_pts = cv2.goodFeaturesToTrack(
            prev_gray, maxCorners=200, qualityLevel=0.01, minDistance=30, blockSize=3
        )
        if prev_pts is None or len(prev_pts) < 8:
            transforms.append((0.0, 0.0, 0.0))
            prev_gray = curr_gray
            continue

        curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, curr_gray, prev_pts, None)
        if curr_pts is None:
            transforms.append((0.0, 0.0, 0.0))
            prev_gray = curr_gray
            continue
        good_prev = prev_pts[status.squeeze().astype(bool)]
        good_curr = curr_pts[status.squeeze().astype(bool)]

        if len(good_prev) < 8:
            transforms.append((0.0, 0.0, 0.0))
            prev_gray = curr_gray
            continue

        mat, _ = cv2.estimateAffinePartial2D(good_prev, good_curr)
        if mat is None:
            transforms.append((0.0, 0.0, 0.0))
        else:
            dx = float(mat[0, 2])
            dy = float(mat[1, 2])
            dtheta = float(np.arctan2(mat[1, 0], mat[0, 0]))
            transforms.append((dx, dy, dtheta))

        prev_gray = curr_gray

    return np.asarray(transforms, dtype=np.float64)


def _smooth(trajectory: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return trajectory
    kernel = np.ones(2 * radius + 1) / (2 * radius + 1)
    smoothed = np.empty_like(trajectory)
    for i in range(trajectory.shape[1]):
        padded = np.pad(trajectory[:, i], radius, mode="edge")
        smoothed[:, i] = np.convolve(padded, kernel, mode="valid")
    return smoothed


def stabilize(
    src: Path,
    dst: Path,
    smooth_radius: int = DEFAULT_SMOOTH_RADIUS,
    crop_pct: float = DEFAULT_CROP_PCT,
) -> None:
    """Stabilize *src* → *dst* (MP4, same FPS, cropped by crop_pct)."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {src}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    print(f"[stab] {src.name}  {width}x{height}@{fps:.1f}  frames={n_frames}", file=sys.stderr)

    # Pass 1: estimate per-frame transforms
    transforms = _estimate_transforms(cap)
    if len(transforms) == 0:
        raise RuntimeError(f"{src}: no transforms estimated")

    trajectory = np.cumsum(transforms, axis=0)
    smoothed_trajectory = _smooth(trajectory, smooth_radius)
    diff = smoothed_trajectory - trajectory
    smoothed_transforms = transforms + diff

    # Pass 2: re-read + warp
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    crop_x = int(round(width * crop_pct / 100.0))
    crop_y = int(round(height * crop_pct / 100.0))
    out_w = width - 2 * crop_x
    out_h = height - 2 * crop_y
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(dst), fourcc, fps, (out_w, out_h))
    if not writer.isOpened():
        raise RuntimeError(f"cannot open writer for {dst}")

    ok, prev = cap.read()
    if not ok:
        raise RuntimeError("empty video after pass 1")
    # Write first frame unaltered (just cropped)
    writer.write(prev[crop_y:crop_y + out_h, crop_x:crop_x + out_w])

    i = 0
    while i < len(smoothed_transforms):
        ok, frame = cap.read()
        if not ok:
            break
        dx, dy, dtheta = smoothed_transforms[i]
        m = np.array([
            [np.cos(dtheta), -np.sin(dtheta), dx],
            [np.sin(dtheta),  np.cos(dtheta), dy],
        ], dtype=np.float32)
        warped = cv2.warpAffine(frame, m, (width, height), borderMode=cv2.BORDER_REFLECT)
        writer.write(warped[crop_y:crop_y + out_h, crop_x:crop_x + out_w])
        i += 1
        if i % 300 == 0:
            print(f"[stab] {src.name}  frame {i}/{n_frames}", file=sys.stderr)

    cap.release()
    writer.release()
    print(f"[stab] done  →  {dst}  ({out_w}x{out_h}, {i+1} frames written)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stabilize moving-camera video into a virtual fixed view.")
    parser.add_argument("--in-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--smooth-radius", type=int, default=DEFAULT_SMOOTH_RADIUS,
                        help="± frames around each frame to average (higher = stiller)")
    parser.add_argument("--crop-pct", type=float, default=DEFAULT_CROP_PCT,
                        help="Percent to crop from each side to hide warp borders")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    videos = sorted(p for p in args.in_dir.iterdir() if p.suffix.lower() == ".mp4")
    if not videos:
        print(f"[stab] no mp4s in {args.in_dir}", file=sys.stderr)
        return 1

    for v in videos:
        dst = args.out_dir / f"{v.stem}-stabilized.mp4"
        if dst.exists() and dst.stat().st_size > 0:
            print(f"[stab] skip {dst.name}", file=sys.stderr)
            continue
        stabilize(v, dst, smooth_radius=args.smooth_radius, crop_pct=args.crop_pct)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
