#!/usr/bin/env bash
# publish_loop.sh — publish normalized MP4s to MediaMTX in an infinite loop,
# simulating a live RTSP camera feed.
#
# Usage:
#   publish_loop.sh <normalized-video-dir> <rtsp-url>
#
# Behavior:
#   • Gathers *all* .mp4 files in the directory (alphabetical).
#   • If one clip: `-stream_loop -1` on that single file (no re-encode).
#   • If multiple clips: builds an ffmpeg concat playlist and loops it forever
#     via `-f concat -stream_loop -1`. Re-encodes only if container/codec
#     parameters differ; otherwise `-c copy` for zero CPU cost.
#   • Sends at source FPS via `-re` so the RTSP output behaves like a live feed.
#   • Writes pid to /tmp/traffic-intel-ffmpeg.pid so `make stream-down` can kill it.
#   • Runs in the background and returns immediately.

set -euo pipefail

in_dir="${1:-data/normalized}"
rtsp_url="${2:-rtsp://localhost:8554/site1}"

shopt -s nullglob
candidates=( "${in_dir}"/*.mp4 )
if (( ${#candidates[@]} == 0 )); then
    echo "publish_loop: no .mp4 files in ${in_dir}" >&2
    echo "Run 'make veo3-ingest' (or 'make fetch-videos && make normalize-videos') first." >&2
    exit 1
fi

pidfile="/tmp/traffic-intel-ffmpeg.pid"
logfile="/tmp/traffic-intel-ffmpeg.log"
playlist="/tmp/traffic-intel-playlist.txt"

# If already running, leave it alone (idempotent).
if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "publish_loop: already running (pid $(cat "$pidfile"))" >&2
    exit 0
fi

if (( ${#candidates[@]} == 1 )); then
    src="${candidates[0]}"
    echo "publish_loop: streaming 1 clip  ${src##*/}  →  ${rtsp_url}" >&2
    nohup ffmpeg \
        -hide_banner -loglevel warning \
        -re -stream_loop -1 \
        -i "$src" \
        -c copy \
        -f rtsp -rtsp_transport tcp \
        "$rtsp_url" \
        >"$logfile" 2>&1 &
else
    # Multi-clip concat playlist (absolute paths, single-quoted for safety)
    : > "$playlist"
    for f in "${candidates[@]}"; do
        abs="$(readlink -f "$f")"
        printf "file '%s'\n" "$abs" >> "$playlist"
    done
    echo "publish_loop: streaming ${#candidates[@]} clips (concat loop)  →  ${rtsp_url}" >&2
    for f in "${candidates[@]}"; do echo "   • ${f##*/}" >&2; done

    nohup ffmpeg \
        -hide_banner -loglevel warning \
        -re -stream_loop -1 \
        -f concat -safe 0 -i "$playlist" \
        -c copy \
        -f rtsp -rtsp_transport tcp \
        "$rtsp_url" \
        >"$logfile" 2>&1 &
fi

echo $! > "$pidfile"
sleep 1

if ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "publish_loop: ffmpeg failed to start — see $logfile" >&2
    tail -n 20 "$logfile" >&2 || true
    exit 1
fi

echo "publish_loop: ffmpeg pid $(cat "$pidfile")  log=$logfile" >&2
