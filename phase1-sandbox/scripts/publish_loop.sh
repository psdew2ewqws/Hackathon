#!/usr/bin/env bash
# publish_loop.sh — publish a normalized MP4 to MediaMTX in an infinite loop,
# simulating a live RTSP camera feed.
#
# Usage:
#   publish_loop.sh <normalized-video-dir> <rtsp-url>
#
# Behavior:
#   • Picks the first *.mp4 in the directory (alphabetical) as the source.
#   • Sends -stream_loop -1 -re to produce a steady "live" feed.
#   • Uses -c copy — no re-encode cost; the video is already 1920x1080 / 10 FPS
#     from the normalize step.
#   • Writes pid to /tmp/traffic-intel-ffmpeg.pid so `make stream-down` can kill it.
#   • Runs in the background and returns immediately.

set -euo pipefail

in_dir="${1:-data/normalized}"
rtsp_url="${2:-rtsp://localhost:8554/site1}"

shopt -s nullglob
candidates=( "${in_dir}"/*.mp4 )
if (( ${#candidates[@]} == 0 )); then
    echo "publish_loop: no .mp4 files in ${in_dir}" >&2
    echo "Run 'make fetch-videos && make normalize-videos' first." >&2
    exit 1
fi
src="${candidates[0]}"

pidfile="/tmp/traffic-intel-ffmpeg.pid"
logfile="/tmp/traffic-intel-ffmpeg.log"

# If already running, leave it alone (idempotent).
if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "publish_loop: already running (pid $(cat "$pidfile"))" >&2
    exit 0
fi

echo "publish_loop: streaming ${src}  →  ${rtsp_url}" >&2

nohup ffmpeg \
    -hide_banner -loglevel warning \
    -re \
    -stream_loop -1 \
    -i "$src" \
    -c copy \
    -f rtsp -rtsp_transport tcp \
    "$rtsp_url" \
    >"$logfile" 2>&1 &

echo $! > "$pidfile"
sleep 1

if ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "publish_loop: ffmpeg failed to start — see $logfile" >&2
    tail -n 20 "$logfile" >&2 || true
    exit 1
fi

echo "publish_loop: ffmpeg pid $(cat "$pidfile")  log=$logfile" >&2
