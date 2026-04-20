"""C6 — RTSP stream healthcheck.

Uses ``ffprobe`` to verify the configured stream is live and meets the
handbook §6.1 ingestion assumptions:

    • Resolution  1920×1080
    • FPS         in [5, 15]
    • Codec       H.264 / H.265

Exits 0 on pass, 1 on fail. Emits a single JSON line on stdout so it can
also be consumed programmatically by pytest / downstream tooling.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from fractions import Fraction

ALLOWED_CODECS = {"h264", "hevc"}
ALLOWED_FPS = (5, 15)
TARGET_RES = (1920, 1080)


def _probe(url: str, timeout_us: int = 5_000_000) -> dict:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found on PATH — install ffmpeg.")
    cmd = [
        "ffprobe",
        "-v", "error",
        "-rw_timeout", str(timeout_us),
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
        "-of", "json",
        "-rtsp_transport", "tcp",
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed (rc={res.returncode}): {res.stderr.strip()}")
    payload = json.loads(res.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError("ffprobe returned no video streams")
    return streams[0]


def _parse_fps(expr: str) -> float:
    if not expr or expr in {"0/0", "0"}:
        return 0.0
    try:
        return float(Fraction(expr))
    except (ValueError, ZeroDivisionError):
        return 0.0


def evaluate(info: dict) -> tuple[dict, list[str]]:
    report: dict = {
        "codec": info.get("codec_name"),
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": _parse_fps(info.get("avg_frame_rate") or info.get("r_frame_rate") or ""),
    }
    failures: list[str] = []
    if report["codec"] not in ALLOWED_CODECS:
        failures.append(f"codec={report['codec']} not in {sorted(ALLOWED_CODECS)}")
    if (report["width"], report["height"]) != TARGET_RES:
        failures.append(f"resolution={report['width']}x{report['height']} != {TARGET_RES[0]}x{TARGET_RES[1]}")
    if not (ALLOWED_FPS[0] <= report["fps"] <= ALLOWED_FPS[1]):
        failures.append(f"fps={report['fps']:.2f} not in {ALLOWED_FPS}")
    report["healthy"] = not failures
    report["failures"] = failures
    return report, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify RTSP stream health.")
    parser.add_argument("--url", default="rtsp://localhost:8554/site1")
    parser.add_argument("--quiet", action="store_true", help="Suppress stderr prose")
    args = parser.parse_args(argv)

    try:
        info = _probe(args.url)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"healthy": False, "error": str(exc), "url": args.url}))
        if not args.quiet:
            print(f"[stream-check] FAIL: {exc}", file=sys.stderr)
        return 1

    report, failures = evaluate(info)
    report["url"] = args.url
    print(json.dumps(report))
    if failures:
        if not args.quiet:
            print(f"[stream-check] FAIL: {'; '.join(failures)}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(
            f"[stream-check] OK  {report['width']}x{report['height']}"
            f" @ {report['fps']:.1f} fps ({report['codec']})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
