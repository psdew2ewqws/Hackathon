#!/usr/bin/env python3
"""
Build the §6.2 Historical CCTV training & calibration pack.

Inputs
------
  --source   a source video (MP4/MOV). Will be sliced into clips.
  --out      output directory (e.g. data/calibration_pack)
  --clip-seconds   length of each clip (default 15s)
  --label    scenario tag applied to every clip from this source
             (e.g. "free", "light", "heavy", "jam"). Can be "auto" to
             leave blank for manual labelling.

Output layout
-------------
  <out>/
    manifest.json
    README.md
    real/
      <source_stem>/
        full.mp4                     (copy of transcoded source if 1080p, else re-encoded)
        ground_truth.csv             (stub for manual per-approach counts)
        clips/
          clip_0000.mp4
          clip_0001.mp4
          ...

Manifest JSON schema (one entry per clip) is documented in the README.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]).decode().strip()
    return float(out)


def _slice_clip(src: Path, start: float, length: float, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Fast stream copy for H.264 inputs; re-key slightly to ensure playability.
    subprocess.check_call([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{length:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ])


def build(source: Path, out_root: Path, clip_seconds: float, label: str,
          site_id: str, captured_at: str | None) -> dict:
    stem = source.stem.lower().replace(" ", "_")
    real_dir = out_root / "real" / stem
    clips_dir = real_dir / "clips"
    real_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    full_dst = real_dir / "full.mp4"
    if not full_dst.exists():
        # Re-encode to 1080p H.264 to standardise (idempotent; skips if exists).
        subprocess.check_call([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-vf", "scale=1920:1080:flags=lanczos",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-r", "30", "-pix_fmt", "yuv420p", "-an",
            str(full_dst),
        ])

    duration = _ffprobe_duration(full_dst)
    n_clips = max(1, int(duration // clip_seconds))
    clips_meta: list[dict] = []
    for i in range(n_clips):
        start = i * clip_seconds
        dst = clips_dir / f"clip_{i:04d}.mp4"
        if not dst.exists():
            _slice_clip(full_dst, start, clip_seconds, dst)
        clips_meta.append({
            "clip_id": f"{stem}_clip_{i:04d}",
            "source_video": str(full_dst.relative_to(out_root)),
            "clip_file": str(dst.relative_to(out_root)),
            "start_seconds": round(start, 3),
            "end_seconds": round(start + clip_seconds, 3),
            "duration_seconds": round(clip_seconds, 3),
            "scenario_label": None if label == "auto" else label,
            "ground_truth": {
                "S_crossings": None,
                "N_crossings": None,
                "E_crossings": None,
                "W_crossings": None,
                "event": None,
            },
        })

    # Ground-truth CSV template for the labeller.
    gt_csv = real_dir / "ground_truth.csv"
    if not gt_csv.exists():
        header = "clip_id,start_seconds,S_crossings,N_crossings,E_crossings,W_crossings,event,notes\n"
        lines = [header] + [
            f"{c['clip_id']},{c['start_seconds']},,,,,,\n" for c in clips_meta
        ]
        gt_csv.write_text("".join(lines))

    return {
        "site_id": site_id,
        "source_stem": stem,
        "source_original": str(source),
        "full_mp4": str(full_dst.relative_to(out_root)),
        "ground_truth_csv": str(gt_csv.relative_to(out_root)),
        "duration_seconds": round(duration, 2),
        "captured_at_local": captured_at,
        "scenario_label_default": None if label == "auto" else label,
        "clip_seconds": clip_seconds,
        "clip_count": len(clips_meta),
        "clips": clips_meta,
    }


def write_manifest(out_root: Path, entries: list[dict]) -> Path:
    manifest_path = out_root / "manifest.json"
    manifest = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "spec": "Phase 1 §6.2 - Historical CCTV training and calibration pack",
        "purpose": [
            "model training",
            "model calibration",
            "AI tuning",
            "validation of event detection logic",
        ],
        "scenario_taxonomy": ["free", "light", "moderate", "heavy", "jam", "event"],
        "sources": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def write_readme(out_root: Path) -> Path:
    readme = out_root / "README.md"
    readme.write_text(
        "# Historical CCTV training & calibration pack (Phase 1 - 6.2)\n\n"
        "Layout:\n"
        "- `manifest.json` - index of every clip with metadata.\n"
        "- `real/<stem>/full.mp4` - 1920x1080 H.264 master of the source video.\n"
        "- `real/<stem>/clips/clip_NNNN.mp4` - 15-second slices.\n"
        "- `real/<stem>/ground_truth.csv` - per-clip ground-truth template.\n\n"
        "Ground-truth columns:\n"
        "- `S_crossings,N_crossings,E_crossings,W_crossings`: manual count of vehicles crossing each stop line during the clip.\n"
        "- `event`: one of `free,light,moderate,heavy,jam,incident,none` (free-form allowed).\n"
        "- `notes`: free text.\n\n"
        "Weak labels from the live tracker are written to `phase3-fullstack/data/counts.ndjson` (15-second bins) - join on `bin_start` approximate to the clip's wall-clock window.\n\n"
        "Scenario taxonomy matches the gmaps corridor labels: free, light, moderate, heavy, jam.\n"
    )
    return readme


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True, action="append",
                    help="source video; repeat for multiple")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--clip-seconds", type=float, default=15.0)
    ap.add_argument("--label", default="auto",
                    help="scenario tag for every clip from this batch (or 'auto')")
    ap.add_argument("--site-id", default="wadi_saqra")
    ap.add_argument("--captured-at", default=None)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    entries = [
        build(src, args.out, args.clip_seconds, args.label, args.site_id, args.captured_at)
        for src in args.source
    ]
    manifest = write_manifest(args.out, entries)
    readme = write_readme(args.out)
    print(f"wrote {manifest}")
    print(f"wrote {readme}")
    total_clips = sum(e["clip_count"] for e in entries)
    print(f"{len(entries)} source(s), {total_clips} clip(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
