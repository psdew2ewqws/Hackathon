#!/usr/bin/env bash
# Loop the transcoded Wadi Saqra video into a running MediaMTX server as RTSP.
# Assumes a MediaMTX (or equivalent) is listening on :8554 and accepts
# publishers on arbitrary paths (mediamtx's default behaviour).
# Target URL: rtsp://127.0.0.1:8554/wadi_saqra

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${ROOT}/.." && pwd)"
SITE_CFG="${ROOT}/configs/wadi_saqra.json"
# Read video file from site config, fall back to default.
if [[ -n "${VIDEO:-}" ]]; then
  :  # honour env override
elif command -v jq >/dev/null 2>&1 && [[ -f "${SITE_CFG}" ]]; then
  VIDEO_REL="$(jq -r '.video.file' "${SITE_CFG}")"
  VIDEO="${REPO_ROOT}/${VIDEO_REL}"
else
  VIDEO="${ROOT}/data/wadi_saqra_5210_1080p.mp4"
fi
LOG_DIR="${ROOT}/data/logs"
mkdir -p "${LOG_DIR}"

if [[ ! -f "${VIDEO}" ]]; then
  echo "video not found at ${VIDEO}" >&2; exit 1
fi
if ! ss -ltn 2>/dev/null | grep -q ':8554'; then
  echo "no RTSP server listening on :8554 — start MediaMTX first" >&2
  echo "  (e.g. ${ROOT}/bin/mediamtx ${ROOT}/configs/mediamtx.yml)" >&2
  exit 1
fi

echo "[run_rtsp] pushing loop: ${VIDEO} -> rtsp://127.0.0.1:8554/wadi_saqra"
# Record the ffmpeg start wall-clock (seconds since epoch, float). The signal
# simulator reads this so its phase transitions stay locked to the video.
# Written atomically so a partial read never happens.
printf '%s' "$(date +%s.%N)" > "${ROOT}/data/ffmpeg_start.txt.tmp"
mv "${ROOT}/data/ffmpeg_start.txt.tmp" "${ROOT}/data/ffmpeg_start.txt"
exec ffmpeg -hide_banner -loglevel warning \
  -re -stream_loop -1 -i "${VIDEO}" \
  -c:v copy -an -f rtsp -rtsp_transport tcp \
  rtsp://127.0.0.1:8554/wadi_saqra
