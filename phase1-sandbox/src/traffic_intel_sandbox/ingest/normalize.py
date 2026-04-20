"""C2 — Video normalizer.

Re-encodes every ``*.mp4`` (and common video extensions) in ``--in-dir``
into ``--out-dir`` at a common profile:

    • Container:  MP4
    • Video:      H.264 (libx264), yuv420p, CRF 23
    • Resolution: scale to fit inside 1920×1080, pad to 1920×1080 if needed
    • FPS:        10 (matches handbook §6.1 ingestion 5–15 FPS)
    • Audio:      stripped (traffic pipeline does not need audio)

Idempotent: skips files whose normalized counterpart exists and is non-empty.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts"}
TARGET_W, TARGET_H, TARGET_FPS = 1920, 1080, 10


def _ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found on PATH — install ffmpeg before running normalize.")
    return found


def _scale_pad_filter() -> str:
    # Preserve aspect ratio, fit inside 1920x1080, pad black bars to exact size.
    return (
        f"scale=w={TARGET_W}:h={TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={TARGET_FPS}"
    )


def normalize(src: Path, dst: Path) -> None:
    """Transcode one file to the normalized profile."""
    cmd: list[str] = [
        _ffmpeg_bin(),
        "-y",
        "-loglevel", "error",
        "-i", str(src),
        "-vf", _scale_pad_filter(),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",                 # drop audio
        "-movflags", "+faststart",
        str(dst),
    ]
    print(f"[norm] {src.name}  →  {dst.name}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize raw videos to 1920x1080 / 10 FPS / H.264.")
    parser.add_argument("--in-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    sources = sorted(p for p in args.in_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS)
    if not sources:
        print(f"[warn] {args.in_dir} contains no video files", file=sys.stderr)
        return 0

    for src in sources:
        dst = args.out_dir / f"{src.stem}.mp4"
        if dst.exists() and dst.stat().st_size > 0:
            print(f"[skip] {dst.name}", file=sys.stderr)
            continue
        normalize(src, dst)

    print(f"[done] {len(sources)} input(s) processed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
