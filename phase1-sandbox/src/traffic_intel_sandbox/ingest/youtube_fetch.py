"""C1 — YouTube video acquisition.

Reads a YAML source list (url + slug + optional clip range) and downloads
each entry at ≤1080p into ``data/raw/youtube/{slug}.mp4`` via yt-dlp.

The list is user-curated. An example lives at
``phase1-sandbox/configs/sources.yml`` — see that file for the schema.

Idempotent: skips a source whose output file already exists and is non-empty.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Use `python -m yt_dlp` so this works whether or not the yt-dlp binary is on
# PATH (e.g. running from Makefile without venv activation).
YT_DLP_CMD = [sys.executable, "-m", "yt_dlp"]

SLUG_RE = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class Source:
    slug: str
    url: str
    description: str | None = None
    start: str | None = None  # ffmpeg/yt-dlp time expr, e.g. "00:05:00"
    end: str | None = None
    tags: tuple[str, ...] = ()

    @staticmethod
    def from_dict(raw: dict) -> "Source":
        slug_in = str(raw.get("slug") or raw["url"])
        slug = SLUG_RE.sub("-", slug_in.lower()).strip("-") or "source"
        return Source(
            slug=slug,
            url=raw["url"],
            description=raw.get("description"),
            start=raw.get("start"),
            end=raw.get("end"),
            tags=tuple(raw.get("tags", [])),
        )


def load_sources(path: Path) -> list[Source]:
    with path.open() as fh:
        payload = yaml.safe_load(fh) or {}
    items = payload.get("sources") or []
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected top-level 'sources:' list")
    return [Source.from_dict(item) for item in items]


def download(source: Source, out_dir: Path) -> Path:
    """Run yt-dlp for one source. Returns the produced path."""
    out_path = out_dir / f"{source.slug}.mp4"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"[skip] {source.slug} (already present)", file=sys.stderr)
        return out_path

    # Prefer mp4 at <=1080p; merge if necessary. `--no-playlist` avoids accidental
    # multi-hour playlist downloads. `--concurrent-fragments` speeds DASH streams.
    cmd: list[str] = [
        *YT_DLP_CMD,
        "--no-playlist",
        "--concurrent-fragments", "4",
        "--format", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", str(out_path),
    ]
    if source.start or source.end:
        section = ""
        if source.start:
            section += f"*{source.start}"
        section += "-"
        if source.end:
            section += source.end
        cmd += ["--download-sections", section]
    cmd.append(source.url)

    print(f"[dl] {source.slug}  ← {source.url}", file=sys.stderr)
    subprocess.run(cmd, check=True)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download YouTube sources for the sandbox.")
    parser.add_argument("--sources", type=Path, required=True, help="Path to sources.yml")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for .mp4 files")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    sources = load_sources(args.sources)
    if not sources:
        print(
            f"[warn] {args.sources} has no entries — add URLs under `sources:` to download.",
            file=sys.stderr,
        )
        return 0

    failures = 0
    for src in sources:
        try:
            download(src, args.out)
        except subprocess.CalledProcessError as exc:
            failures += 1
            print(f"[fail] {src.slug}: yt-dlp exit {exc.returncode}", file=sys.stderr)
    if failures:
        print(f"[done] {len(sources) - failures}/{len(sources)} sources fetched", file=sys.stderr)
        return 1
    print(f"[done] {len(sources)} sources fetched", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
