#!/usr/bin/env bash
# One-command launcher for the full Phase-3 stack.
#
# Starts (if not already running):
#   1. MediaMTX RTSP server on :8554                         (system-managed in PoC)
#   2. ffmpeg loop of phase3-fullstack/data/wadi_saqra_5210_1080p.mp4 -> rtsp://127.0.0.1:8554/wadi_saqra
#   3. uvicorn backend on :8000   (traffic_intel_phase3.poc_wadi_saqra.server:app)
#   4. Vite dev server on :3000   (frontend/)  - optional, toggled by FRONTEND env var
#
# Creates the SQLite schema + seeds it from NDJSON if the DB is empty.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PHASE3="${ROOT}/phase3-fullstack"
VENV="${ROOT}/.venv"
DB="${PHASE3}/data/traffic_intel.db"
LOG_DIR="${PHASE3}/data/logs"
mkdir -p "${LOG_DIR}"

: "${TRAFFIC_INTEL_JWT_SECRET:=dev-secret-change-in-prod-aaa111}"
export TRAFFIC_INTEL_JWT_SECRET

_is_listening() {
    ss -ltn "sport = :$1" 2>/dev/null | grep -q ":$1"
}

echo "[run_full_stack] venv=${VENV}  root=${ROOT}"

# 1. MediaMTX — assume system-managed or pre-started. If port free, try to start
#    the bundled binary.
if ! _is_listening 8554; then
    if [[ -x "${PHASE3}/bin/mediamtx" ]]; then
        echo "[run_full_stack] starting bundled mediamtx"
        "${PHASE3}/bin/mediamtx" "${PHASE3}/configs/mediamtx.yml" \
            >"${LOG_DIR}/mediamtx.log" 2>&1 &
    else
        echo "[run_full_stack] WARN: no mediamtx listening on :8554 and no bundled binary"
    fi
    sleep 1
fi

# 2. ffmpeg RTSP push loop (uses the helper that reads the site config).
if ! pgrep -f 'ffmpeg.*rtsp://127.0.0.1:8554/wadi_saqra' >/dev/null 2>&1; then
    echo "[run_full_stack] starting RTSP push loop"
    "${PHASE3}/scripts/run_rtsp.sh" >"${LOG_DIR}/ffmpeg_push.log" 2>&1 &
fi

# 3. SQLite init + seed (idempotent).
if [[ ! -s "${DB}" ]]; then
    echo "[run_full_stack] seeding SQLite from NDJSON"
    "${VENV}/bin/python" "${PHASE3}/src/traffic_intel_phase3/storage/migrate_ndjson.py" \
        || echo "[run_full_stack] WARN: migration had non-zero exit"
fi

# 4. uvicorn backend.
if ! _is_listening 8000; then
    echo "[run_full_stack] starting uvicorn on :8000"
    "${VENV}/bin/python" -m uvicorn traffic_intel_phase3.poc_wadi_saqra.server:app \
        --host 0.0.0.0 --port 8000 --log-level warning \
        >"${LOG_DIR}/uvicorn.log" 2>&1 &
fi

# 5. frontend Vite dev server (opt-in).
if [[ "${FRONTEND:-0}" == "1" ]] && ! _is_listening 3000; then
    if command -v npm >/dev/null 2>&1; then
        echo "[run_full_stack] starting vite dev server on :3000"
        ( cd "${ROOT}/frontend" && npm run dev >"${LOG_DIR}/vite.log" 2>&1 & )
    fi
fi

sleep 3
echo ""
echo "[run_full_stack] endpoints:"
echo "  backend:  http://localhost:8000/"
echo "  react:    http://localhost:8000/app/  (built dist) or http://localhost:3000/ (dev)"
echo "  login:    admin/admin123  operator/operator123  viewer/viewer123"
echo "  api:      /api/health  /api/ingest/metrics  /api/forecast/ml/metrics"
echo "  logs:     ${LOG_DIR}/"

if _is_listening 8000; then
    curl -sS http://127.0.0.1:8000/api/health | python3 -m json.tool 2>/dev/null || true
fi
