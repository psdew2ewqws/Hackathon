"""Experiment 05 — Seed §6.6 event scenarios and render labeled clips.

Stage 5 of the sim-to-real pipeline (see docs/research_sim_to_real.md).

Runs the compositor from step 04 multiple times with targeted mutations that
realise each handbook §6.6 event class:

  stalled_vehicle        — one vehicle frozen in a travel lane for the clip
  abnormal_stop          — one vehicle stops at a random mid-lane position
  unexpected_trajectory  — one vehicle moves in the wrong direction
  queue_spillback        — one approach flooded with vehicles, signal red
  sudden_congestion      — arrival rate doubles mid-clip on one approach

Writes per-class labeled MP4s under data/research/events/<class>/ plus a
manifest.json that lists every clip with its seed, mutation, and ground-truth
tag. Compatible with the existing Pass A/B rule classifier for self-check.

Target volume: N clips per class (default 20; raise with --per-class for full
training runs).

Usage
-----
    python experiments/05_generate_event_clips.py \\
        --out-root data/research/events --per-class 10 --seconds 15 --seed 42
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd

# Reuse composite primitives from step 04
sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module  # noqa: E402
_compose_mod = import_module("04_compose_synthetic_video")

APPROACH_VECTORS = _compose_mod.APPROACH_TRAVEL_VECTORS
PX_PER_SEC = _compose_mod.PX_PER_SEC
FPS = _compose_mod.FPS
W, H = _compose_mod.W, _compose_mod.H
ActiveVehicle = _compose_mod.ActiveVehicle
Crop = _compose_mod.Crop
_load_crops = _compose_mod._load_crops
_alpha_composite = _compose_mod._alpha_composite

EVENT_CLASSES = (
    "stalled_vehicle",
    "abnormal_stop",
    "unexpected_trajectory",
    "queue_spillback",
    "sudden_congestion",
)


@dataclass
class Scenario:
    event: str
    seed: int
    seconds: int
    plate: Path
    crops_dir: Path
    site_meta: Path
    approach: str = "N"
    stalled_frame: int = 0          # frame at which the stalled vehicle appears
    stalled_location_frac: float = 0.5  # 0 = upstream, 1 = stop line
    congestion_spike_frac: float = 0.5
    extra: dict[str, Any] = field(default_factory=dict)


def _load_site(site_meta_path: Path) -> dict:
    return json.loads(site_meta_path.read_text())


def _render_clip(scenario: Scenario, out_video: Path, out_labels: Path) -> dict:
    plate = cv2.imread(str(scenario.plate))
    if plate is None:
        raise RuntimeError(f"bad plate: {scenario.plate}")
    if plate.shape[:2] != (H, W):
        plate = cv2.resize(plate, (W, H))

    crops = _load_crops(scenario.crops_dir)
    meta = _load_site(scenario.site_meta)
    stop_lines = {sl["approach"]: sl["polyline_px"] for sl in meta["stop_lines"]}

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_video), fourcc, FPS, (W, H))
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter open failed: {out_video}")

    rng = random.Random(scenario.seed)
    total_frames = scenario.seconds * FPS
    active: list[ActiveVehicle] = []
    per_frame_labels = []
    next_track_id = 0

    # Spawn schedule: base background traffic every ~0.5 s on major approach
    # (N), plus event-specific additions.
    spawn_schedule: list[tuple[int, str, bool]] = []  # (frame, approach, is_event_vehicle)
    base_rate_frames = int(0.5 * FPS)
    for f in range(0, total_frames, base_rate_frames):
        a = rng.choice(["N", "S", "E", "W"])
        spawn_schedule.append((f, a, False))

    # Apply per-event mutations
    stalled_info: dict | None = None
    wrongway_info: dict | None = None
    congestion_start_frame: int | None = None
    if scenario.event == "queue_spillback":
        # Flood one approach
        flood_frames = list(range(0, total_frames, 3))
        for f in flood_frames:
            spawn_schedule.append((f, scenario.approach, True))
    elif scenario.event == "sudden_congestion":
        # Second half: burst arrivals on one approach
        congestion_start_frame = int(total_frames * scenario.congestion_spike_frac)
        for f in range(congestion_start_frame, total_frames, 2):
            spawn_schedule.append((f, scenario.approach, True))
    elif scenario.event == "stalled_vehicle":
        stalled_info = {"approach": scenario.approach, "spawn_frame": scenario.stalled_frame}
        spawn_schedule.append((scenario.stalled_frame, scenario.approach, True))
    elif scenario.event == "abnormal_stop":
        stalled_info = {"approach": scenario.approach, "spawn_frame": scenario.stalled_frame}
        spawn_schedule.append((scenario.stalled_frame, scenario.approach, True))
    elif scenario.event == "unexpected_trajectory":
        # Wrong-way: flip the travel vector
        wrongway_info = {"approach": scenario.approach, "spawn_frame": scenario.stalled_frame}
        spawn_schedule.append((scenario.stalled_frame, scenario.approach, True))

    spawn_schedule.sort()

    stalled_vehicle_id: int | None = None
    wrongway_vehicle_id: int | None = None

    for frame_idx in range(total_frames):
        while spawn_schedule and spawn_schedule[0][0] <= frame_idx:
            _, approach, is_event = spawn_schedule.pop(0)
            sl = stop_lines.get(approach, [[960, 540], [960, 540]])
            sx = (sl[0][0] + sl[1][0]) / 2
            sy = (sl[0][1] + sl[1][1]) / 2
            vx, vy = APPROACH_VECTORS[approach]
            # Wrong-way flip
            if is_event and scenario.event == "unexpected_trajectory":
                vx, vy = -vx, -vy

            # Start upstream
            start_x = sx - vx * PX_PER_SEC * 2.0
            start_y = sy - vy * PX_PER_SEC * 2.0

            class_pool = list(crops.keys()) or ["car"]
            class_name = rng.choice(class_pool)
            crop_list = crops.get(class_name, [])
            if crop_list:
                crop = rng.choice(crop_list)
            else:
                fb = np.zeros((40, 80, 4), dtype=np.uint8)
                fb[:, :, :3] = (0, 200, 255)
                fb[:, :, 3] = 220
                crop = Crop("fallback", class_name, fb)

            vehicle = ActiveVehicle(
                vehicle_id=f"V{next_track_id:05d}",
                class_name=class_name,
                approach=approach,
                x=start_x, y=start_y,
                vx=vx * PX_PER_SEC / FPS,
                vy=vy * PX_PER_SEC / FPS,
                crop=crop,
                born_frame=frame_idx,
                track_id=next_track_id,
            )
            # Stalled/abnormal_stop: zero velocity once inside the frame
            if is_event and scenario.event in ("stalled_vehicle", "abnormal_stop"):
                # Place somewhere along the travel path
                frac = scenario.stalled_location_frac if scenario.event == "stalled_vehicle" else rng.uniform(0.2, 0.8)
                vehicle.x = sx - vx * PX_PER_SEC * 2.0 * (1 - frac)
                vehicle.y = sy - vy * PX_PER_SEC * 2.0 * (1 - frac)
                vehicle.vx = 0.0
                vehicle.vy = 0.0
                stalled_vehicle_id = vehicle.track_id
            if is_event and scenario.event == "unexpected_trajectory":
                wrongway_vehicle_id = vehicle.track_id
            active.append(vehicle)
            next_track_id += 1

        frame = plate.copy()
        live_labels = []
        still_active: list[ActiveVehicle] = []
        for v in active:
            v.x += v.vx
            v.y += v.vy
            h_c, w_c = v.crop.rgba.shape[:2]
            tlx, tly = int(v.x - w_c / 2), int(v.y - h_c / 2)
            if tlx + w_c < -200 or tly + h_c < -200 or tlx > W + 200 or tly > H + 200:
                continue
            _alpha_composite(frame, v.crop.rgba, tlx, tly)
            label_entry = {
                "track_id": v.track_id,
                "class": v.class_name,
                "bbox_xyxy": [max(0, tlx), max(0, tly),
                              min(W, tlx + w_c), min(H, tly + h_c)],
                "approach": v.approach,
                "event_actor": False,
            }
            if stalled_vehicle_id is not None and v.track_id == stalled_vehicle_id:
                label_entry["event_actor"] = True
                label_entry["event_role"] = scenario.event
            if wrongway_vehicle_id is not None and v.track_id == wrongway_vehicle_id:
                label_entry["event_actor"] = True
                label_entry["event_role"] = "unexpected_trajectory"
            live_labels.append(label_entry)
            still_active.append(v)
        active = still_active
        per_frame_labels.append({"frame": frame_idx, "instances": live_labels})
        writer.write(frame)

    writer.release()
    labels_payload = {
        "event_class": scenario.event,
        "approach": scenario.approach,
        "seed": scenario.seed,
        "seconds": scenario.seconds,
        "fps": FPS,
        "resolution": [W, H],
        "total_frames": total_frames,
        "congestion_start_frame": congestion_start_frame,
        "stalled_info": stalled_info,
        "wrongway_info": wrongway_info,
        "frames": per_frame_labels,
    }
    out_labels.write_text(json.dumps(labels_payload, indent=2))
    return {"video": str(out_video), "labels": str(out_labels), "event": scenario.event}


def run_all(
    out_root: Path,
    plate: Path,
    crops_dir: Path,
    site_meta: Path,
    per_class: int,
    seconds: int,
    seed: int,
) -> dict:
    out_root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    manifest: list[dict] = []
    for event in EVENT_CLASSES:
        class_dir = out_root / event
        class_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            clip_seed = rng.randrange(1, 2**31 - 1)
            approach = rng.choice(["N", "S", "E", "W"])
            stalled_frame = rng.randrange(0, max(1, seconds * FPS // 2))
            sc = Scenario(
                event=event,
                seed=clip_seed,
                seconds=seconds,
                plate=plate,
                crops_dir=crops_dir,
                site_meta=site_meta,
                approach=approach,
                stalled_frame=stalled_frame,
                stalled_location_frac=rng.uniform(0.3, 0.8),
                congestion_spike_frac=rng.uniform(0.3, 0.6),
            )
            clip_name = f"{event}_{i:04d}_seed{clip_seed}"
            out_video = class_dir / f"{clip_name}.mp4"
            out_labels = class_dir / f"{clip_name}.json"
            try:
                result = _render_clip(sc, out_video, out_labels)
                manifest.append({**result, "seed": clip_seed, "approach": approach})
            except Exception as e:
                print(f"[events] {clip_name} failed: {e}", file=sys.stderr)

    manifest_path = out_root / "manifest.json"
    manifest_path.write_text(json.dumps({
        "classes": list(EVENT_CLASSES),
        "per_class": per_class,
        "seconds": seconds,
        "total_clips": len(manifest),
        "clips": manifest,
    }, indent=2))
    print(f"[events] wrote {len(manifest)} clips across {len(EVENT_CLASSES)} classes  →  {out_root}",
          file=sys.stderr)
    return {"manifest": manifest_path, "total": len(manifest)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out-root", type=Path, default=Path("data/research/events"))
    p.add_argument("--plate", type=Path, default=Path("data/research/plates/wadisaqra_plate.jpg"))
    p.add_argument("--crops-dir", type=Path, default=Path("data/research/crops"))
    p.add_argument("--site-meta", type=Path,
                   default=Path("phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"))
    p.add_argument("--per-class", type=int, default=10)
    p.add_argument("--seconds", type=int, default=15)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    run_all(
        args.out_root,
        args.plate,
        args.crops_dir,
        args.site_meta,
        args.per_class,
        args.seconds,
        args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
