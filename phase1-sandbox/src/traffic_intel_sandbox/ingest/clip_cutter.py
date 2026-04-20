"""C3 — Historical clip cutter.

Turns a pool of normalized long videos into a ``--days`` day historical
pack at ``--out-dir/YYYY-MM-DD/clip-NN.mp4``. Each day folder gets a few
clips distributed across AM / midday / PM windows, sampled from the source
pool. Clips are *extracted* (no re-encode) with ``ffmpeg -c copy`` for speed.

This preserves the spirit of the handbook §6.2 "~2 weeks of representative
video samples" without requiring 14 distinct days of real footage —
sampling+timestamping is the honest approach for a synthesized sandbox,
documented in ``methodology.md``.
"""

from __future__ import annotations

import argparse
import random
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WINDOWS: list[tuple[str, str]] = [
    ("am_peak",   "07:30:00"),
    ("midday",    "12:30:00"),
    ("pm_peak",   "17:30:00"),
]
CLIP_SECONDS = 180   # 3-minute clips


def _ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found on PATH")
    return found


def _probe_duration_sec(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(res.stdout.strip() or 0.0)


def _cut(src: Path, start_s: float, seconds: int, dst: Path) -> None:
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-loglevel", "error",
        "-ss", f"{start_s:.3f}",
        "-i", str(src),
        "-t", str(seconds),
        "-c", "copy",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)


def build_pack(
    in_dir: Path,
    out_dir: Path,
    days: int,
    start_date: date,
    seed: int = 42,
) -> int:
    """Write ``days`` day-directories, each with a clip per window."""
    rng = random.Random(seed)
    sources = sorted(in_dir.glob("*.mp4"))
    if not sources:
        print(f"[warn] no normalized mp4s in {in_dir}", file=sys.stderr)
        return 0
    durations = {p: _probe_duration_sec(p) for p in sources}
    usable = [p for p, d in durations.items() if d >= CLIP_SECONDS + 5]
    if not usable:
        raise RuntimeError(
            f"All sources shorter than {CLIP_SECONDS}s — cannot cut clips. "
            "Download longer videos or lower CLIP_SECONDS."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    total_clips = 0
    for i in range(days):
        d = start_date + timedelta(days=i)
        day_dir = out_dir / d.isoformat()
        day_dir.mkdir(exist_ok=True)
        for win_idx, (win_name, _win_time) in enumerate(WINDOWS, start=1):
            src = rng.choice(usable)
            max_start = max(0.0, durations[src] - CLIP_SECONDS - 1)
            start_s = rng.uniform(0, max_start)
            dst = day_dir / f"clip-{win_idx:02d}-{win_name}.mp4"
            if dst.exists() and dst.stat().st_size > 0:
                continue
            _cut(src, start_s, CLIP_SECONDS, dst)
            total_clips += 1
            print(f"[cut] {d} {win_name:<8}  ← {src.name} @ {start_s:6.1f}s  →  {dst.name}", file=sys.stderr)
    return total_clips


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a N-day historical clip pack.")
    parser.add_argument("--in-dir", type=Path, required=True, help="Normalized mp4 pool")
    parser.add_argument("--out-dir", type=Path, required=True, help="Historical pack root")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--start-date", type=str, default=None,
                        help="ISO date; defaults to (today - days)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    start = (
        datetime.fromisoformat(args.start_date).date()
        if args.start_date
        else date.today() - timedelta(days=args.days)
    )
    n = build_pack(args.in_dir, args.out_dir, args.days, start, args.seed)
    print(f"[done] {n} clips written into {args.out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
