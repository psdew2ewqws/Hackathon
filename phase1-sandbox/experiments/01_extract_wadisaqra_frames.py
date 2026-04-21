"""Experiment 01 — Extract high-quality keyframes from Wadi Saqra YouTube video.

Stage 1 of the sim-to-real pipeline (see docs/research_sim_to_real.md).

Reads a source MP4 from data/raw/youtube/, samples frames at a configurable
stride, rejects blurry / dark frames by Laplacian variance and mean luminance,
and writes the survivors to data/research/frames/ plus an index.json.

Deterministic: same --seed + same inputs ⇒ byte-identical outputs.

Usage
-----
    python experiments/01_extract_wadisaqra_frames.py \\
        --video data/raw/youtube/amman-wadi-saqra-tour.mp4 \\
        --out-dir data/research/frames \\
        --stride-s 2.0 --max-frames 400 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

DEFAULT_VIDEO = Path("data/raw/youtube/amman-wadi-saqra-tour.mp4")
DEFAULT_OUT = Path("data/research/frames")


@dataclass(frozen=True)
class FrameRecord:
    path: str
    frame_idx: int
    timestamp_s: float
    laplacian_var: float
    mean_luminance: float
    sha256: str


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _quality_ok(frame: np.ndarray, min_lap_var: float, min_luma: float, max_luma: float) -> tuple[bool, float, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_luma = float(gray.mean())
    ok = lap_var >= min_lap_var and min_luma <= mean_luma <= max_luma
    return ok, lap_var, mean_luma


def extract(
    video_path: Path,
    out_dir: Path,
    stride_s: float,
    max_frames: int,
    min_lap_var: float,
    min_luma: float,
    max_luma: float,
    seed: int,
) -> list[FrameRecord]:
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if n_total == 0:
            raise RuntimeError(f"cv2 reports 0 frames for {video_path}")

        stride_frames = max(1, int(round(stride_s * fps)))
        candidates = list(range(0, n_total, stride_frames))
        # Shuffle deterministically then walk so that if max_frames < len we
        # still get temporally-distributed samples rather than only the start.
        rng = random.Random(seed)
        rng.shuffle(candidates)

        src_sha = _file_sha256(video_path)
        records: list[FrameRecord] = []

        for idx in candidates:
            if len(records) >= max_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            good, lap_var, mean_luma = _quality_ok(frame, min_lap_var, min_luma, max_luma)
            if not good:
                continue
            ts = idx / fps
            name = f"wadisaqra_f{idx:08d}.jpg"
            out_path = out_dir / name
            # JPEG quality 92 for a balance of fidelity and size
            cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            records.append(FrameRecord(
                path=str(out_path.relative_to(out_dir.parent.parent)) if out_dir.parent.parent in out_path.parents else str(out_path),
                frame_idx=idx,
                timestamp_s=round(ts, 3),
                laplacian_var=round(lap_var, 2),
                mean_luminance=round(mean_luma, 2),
                sha256=src_sha,
            ))
    finally:
        cap.release()

    records.sort(key=lambda r: r.frame_idx)
    index = {
        "source_video": str(video_path),
        "source_sha256": src_sha,
        "source_fps": fps,
        "stride_s": stride_s,
        "seed": seed,
        "min_lap_var": min_lap_var,
        "min_luma": min_luma,
        "max_luma": max_luma,
        "n_frames": len(records),
        "frames": [asdict(r) for r in records],
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    print(f"[frames] kept {len(records)} frames from {video_path.name}  →  {out_dir}",
          file=sys.stderr)
    return records


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--stride-s", type=float, default=2.0,
                   help="Seconds between sampled frames")
    p.add_argument("--max-frames", type=int, default=400)
    p.add_argument("--min-lap-var", type=float, default=40.0,
                   help="Reject frame if Laplacian variance below this (blurry)")
    p.add_argument("--min-luma", type=float, default=30.0,
                   help="Reject frame darker than this (night/occluded)")
    p.add_argument("--max-luma", type=float, default=230.0,
                   help="Reject frame brighter than this (overexposed)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    extract(
        args.video,
        args.out_dir,
        args.stride_s,
        args.max_frames,
        args.min_lap_var,
        args.min_luma,
        args.max_luma,
        args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
