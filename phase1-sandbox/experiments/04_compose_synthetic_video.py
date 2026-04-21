"""Experiment 04 — Composite synthetic video from SUMO tracks + Wadi Saqra plate.

Stage 4 of the sim-to-real pipeline (see docs/research_sim_to_real.md).

Takes:
  - The clean background plate from 02_segment_and_inpaint.py
  - Vehicle crops (alpha PNGs) from 02_segment_and_inpaint.py
  - Per-vehicle trajectory rows from 03_sumo_scenario.py
  - Camera calibration from metadata/site1.example.json

Projects each trajectory into pixel space (approach-aware travel along the
stop-line normal), composites crops at per-frame positions, writes a labeled
MP4 at 1080p/10fps + a per-frame annotation JSON with bboxes, track IDs, and
class labels.

This is the deterministic CPU path. A GPU polish pass using CogVideoX-5B-I2V
is described in experiments/README.md and is *not* required to produce
schema-valid output.

Usage
-----
    python experiments/04_compose_synthetic_video.py \\
        --plate data/research/plates/wadisaqra_plate.jpg \\
        --crops-dir data/research/crops \\
        --trajectories data/research/sumo/trajectories_2026-04-20.parquet \\
        --site-meta phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json \\
        --out-video data/research/composed/video.mp4 \\
        --out-labels data/research/composed/labels.json \\
        --seconds 30
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

FPS = 10
W, H = 1920, 1080


@dataclass
class Crop:
    name: str
    class_name: str
    rgba: np.ndarray  # HxWx4


def _load_crops(crops_dir: Path) -> dict[str, list[Crop]]:
    """Return crops bucketed by class_name."""
    buckets: dict[str, list[Crop]] = {}
    for p in sorted(crops_dir.glob("*.png")):
        # Filename convention: <stem>_<idx>_<class>.png
        parts = p.stem.rsplit("_", 2)
        if len(parts) < 3:
            continue
        class_name = parts[-1]
        img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if img is None or img.ndim != 3 or img.shape[2] != 4:
            continue
        buckets.setdefault(class_name, []).append(Crop(p.name, class_name, img))
    return buckets


APPROACH_TRAVEL_VECTORS = {
    # Directed unit vectors in image-space pixel coords that a vehicle travels
    # along from the upstream edge toward the stop line.
    # Stop-line geometry in site1.example.json:
    #   N approach stop line at y=620 (vehicles travel from top down, so +y)
    #   S approach stop line at y=460 (vehicles travel from bottom up, so -y)
    #   E approach stop line at x=1100 (vehicles travel from right to left, so -x)
    #   W approach stop line at x=820 (vehicles travel from left to right, so +x)
    "N": (0.0, +1.0),
    "S": (0.0, -1.0),
    "E": (-1.0, 0.0),
    "W": (+1.0, 0.0),
}
# Pixel distance traveled per second at typical urban speed (45 km/h ≈ 12.5 m/s;
# assume 1 m ≈ 12 px at this camera) — used only for compositing motion.
PX_PER_SEC = 150.0


@dataclass
class ActiveVehicle:
    vehicle_id: str
    class_name: str
    approach: str
    x: float
    y: float
    vx: float
    vy: float
    crop: Crop
    born_frame: int
    track_id: int


def _alpha_composite(base: np.ndarray, overlay_rgba: np.ndarray, x: int, y: int) -> None:
    """In-place composite of overlay_rgba onto base at top-left (x, y)."""
    h, w = overlay_rgba.shape[:2]
    x0 = max(0, x); y0 = max(0, y)
    x1 = min(base.shape[1], x + w); y1 = min(base.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sx0 = x0 - x; sy0 = y0 - y
    sx1 = sx0 + (x1 - x0); sy1 = sy0 + (y1 - y0)
    fg = overlay_rgba[sy0:sy1, sx0:sx1]
    alpha = (fg[..., 3:4].astype(np.float32) / 255.0)
    bg = base[y0:y1, x0:x1].astype(np.float32)
    fg_rgb = fg[..., :3].astype(np.float32)
    base[y0:y1, x0:x1] = (alpha * fg_rgb + (1 - alpha) * bg).astype(np.uint8)


def compose(
    plate_path: Path,
    crops_dir: Path,
    trajectories_path: Path,
    site_meta_path: Path,
    out_video: Path,
    out_labels: Path,
    seconds: int,
    seed: int,
) -> dict:
    if not plate_path.exists():
        raise FileNotFoundError(f"plate missing: {plate_path} (run 02_segment_and_inpaint.py)")
    plate = cv2.imread(str(plate_path))
    if plate is None:
        raise RuntimeError(f"could not read plate image: {plate_path}")
    if plate.shape[:2] != (H, W):
        plate = cv2.resize(plate, (W, H))

    crops = _load_crops(crops_dir)
    if not crops:
        print("[compose] no crops found — compositing will draw class-colored rectangles as a fallback",
              file=sys.stderr)

    meta = json.loads(site_meta_path.read_text())
    stop_lines = {sl["approach"]: sl["polyline_px"] for sl in meta["stop_lines"]}

    traj = pd.read_parquet(trajectories_path) if trajectories_path.exists() and trajectories_path.stat().st_size else pd.DataFrame()
    if traj.empty:
        print("[compose] empty trajectories — will emit an empty (but valid) MP4", file=sys.stderr)

    out_video.parent.mkdir(parents=True, exist_ok=True)
    out_labels.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_video), fourcc, FPS, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"could not open VideoWriter at {out_video}")

    rng = random.Random(seed)
    # Collapse trajectory rows into spawn events on a 1s grid
    spawn_events: list[dict] = []
    if not traj.empty:
        # Map the full-day trajectory timestamps into the seconds-long clip
        # timeline by using fractional time-of-day. This gives us diurnal
        # variety even in a short clip.
        traj = traj.copy()
        traj["sec_of_day"] = pd.to_datetime(traj["timestamp"]).dt.hour * 3600 + \
            pd.to_datetime(traj["timestamp"]).dt.minute * 60 + \
            pd.to_datetime(traj["timestamp"]).dt.second
        # Evenly distribute over our clip length
        n = len(traj)
        clip_seconds = max(1, seconds)
        # Deterministic subsample
        if n > clip_seconds * 4:
            traj = traj.sample(n=clip_seconds * 4, random_state=seed).reset_index(drop=True)
        for i, row in traj.iterrows():
            spawn_events.append({
                "t_s": (i * clip_seconds) / max(1, len(traj)),
                "approach": row["approach"],
                "sl_x": float(row["stop_line_px_x"]),
                "sl_y": float(row["stop_line_px_y"]),
                "vehicle_id": row["vehicle_id"],
            })

    active: list[ActiveVehicle] = []
    per_frame_labels = []
    next_track_id = 0
    total_frames = seconds * FPS
    fallback_colors = {"car": (0, 200, 255), "truck": (200, 120, 60),
                       "bus": (255, 100, 100), "motorcycle": (100, 255, 100),
                       "bicycle": (100, 255, 255), "pedestrian": (255, 100, 255)}

    for frame_idx in range(total_frames):
        t_s = frame_idx / FPS
        # Spawn any events at or before t_s
        while spawn_events and spawn_events[0]["t_s"] <= t_s:
            ev = spawn_events.pop(0)
            vx, vy = APPROACH_TRAVEL_VECTORS.get(ev["approach"], (0.0, 0.0))
            # Start far upstream; head toward stop line at PX_PER_SEC
            start_x = ev["sl_x"] - vx * PX_PER_SEC * 2.0
            start_y = ev["sl_y"] - vy * PX_PER_SEC * 2.0
            class_pool = list(crops.keys()) or ["car"]
            class_name = rng.choice(class_pool)
            crop_list = crops.get(class_name, [])
            crop = rng.choice(crop_list) if crop_list else Crop("fallback", class_name,
                                                                 np.zeros((40, 80, 4), dtype=np.uint8))
            if crop.name == "fallback":
                # Draw a class-colored rectangle with full alpha so fallback renders
                color = fallback_colors.get(class_name, (255, 255, 255))
                crop.rgba[:, :, :3] = color
                crop.rgba[:, :, 3] = 220
            active.append(ActiveVehicle(
                vehicle_id=ev["vehicle_id"],
                class_name=class_name,
                approach=ev["approach"],
                x=start_x, y=start_y,
                vx=vx * PX_PER_SEC / FPS,
                vy=vy * PX_PER_SEC / FPS,
                crop=crop,
                born_frame=frame_idx,
                track_id=next_track_id,
            ))
            next_track_id += 1

        frame = plate.copy()
        live_labels = []
        still_active: list[ActiveVehicle] = []
        for v in active:
            v.x += v.vx
            v.y += v.vy
            h_c, w_c = v.crop.rgba.shape[:2]
            tlx, tly = int(v.x - w_c / 2), int(v.y - h_c / 2)
            if tlx + w_c < 0 or tly + h_c < 0 or tlx > W or tly > H:
                continue  # left the frame
            _alpha_composite(frame, v.crop.rgba, tlx, tly)
            live_labels.append({
                "track_id": v.track_id,
                "class": v.class_name,
                "bbox_xyxy": [max(0, tlx), max(0, tly),
                              min(W, tlx + w_c), min(H, tly + h_c)],
                "approach": v.approach,
            })
            still_active.append(v)
        active = still_active
        per_frame_labels.append({"frame": frame_idx, "t_s": round(t_s, 3), "instances": live_labels})
        writer.write(frame)

    writer.release()
    out_labels.write_text(json.dumps({
        "video": str(out_video),
        "fps": FPS,
        "resolution": [W, H],
        "total_frames": total_frames,
        "frames": per_frame_labels,
    }, indent=2))
    print(f"[compose] wrote {total_frames} frames  labels={len(per_frame_labels)}  →  {out_video}",
          file=sys.stderr)
    return {"video": out_video, "labels": out_labels, "frames": total_frames}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--plate", type=Path, default=Path("data/research/plates/wadisaqra_plate.jpg"))
    p.add_argument("--crops-dir", type=Path, default=Path("data/research/crops"))
    p.add_argument("--trajectories", type=Path,
                   default=Path("data/research/sumo/trajectories_2026-04-20.parquet"))
    p.add_argument("--site-meta", type=Path,
                   default=Path("phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"))
    p.add_argument("--out-video", type=Path, default=Path("data/research/composed/video.mp4"))
    p.add_argument("--out-labels", type=Path, default=Path("data/research/composed/labels.json"))
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    compose(
        args.plate,
        args.crops_dir,
        args.trajectories,
        args.site_meta,
        args.out_video,
        args.out_labels,
        args.seconds,
        args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
