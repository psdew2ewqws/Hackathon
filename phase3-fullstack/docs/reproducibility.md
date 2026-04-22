# Phase 3 — Reproducibility

Fresh-machine walkthrough to bring the Phase 3 stack up end-to-end.
Target OS: Ubuntu 24.04+/25.10; Python 3.11+ (tested on 3.12); Node 20+
for the frontend build. Hardware: the tracker runs on CPU; a GPU makes
`YOLO.track()` ~5× faster but is not required.

## 1. Clone + Python environment

```bash
git clone https://github.com/<your-org>/traffic-intel.git
cd traffic-intel

python3 -m venv .venv3
source .venv3/bin/activate
python -m pip install --upgrade pip wheel
pip install -e .
pip install ultralytics lightgbm fastapi uvicorn[standard] bcrypt pyjwt pyarrow pandas opencv-python-headless supervision
```

The project is a namespace layout — `pip install -e .` makes
`traffic_intel_sandbox`, `traffic_intel_phase2`, `traffic_intel_phase3` and
`forecast_ml` importable from any working directory.

## 2. Download MediaMTX

The binary is committed at `phase3-fullstack/bin/mediamtx`. If it's
missing, fetch a release:

```bash
MTX_VER=1.16.0
curl -L -o /tmp/mediamtx.tar.gz \
  "https://github.com/bluenviron/mediamtx/releases/download/v${MTX_VER}/mediamtx_v${MTX_VER}_linux_amd64.tar.gz"
tar -xzf /tmp/mediamtx.tar.gz -C /tmp
cp /tmp/mediamtx phase3-fullstack/bin/mediamtx
chmod +x phase3-fullstack/bin/mediamtx
```

## 3. Install ffmpeg

```bash
sudo apt install -y ffmpeg        # Ubuntu/Debian
# macOS:  brew install ffmpeg
# Windows: https://www.gyan.dev/ffmpeg/builds/
```

## 4. Frontend dependencies and build

```bash
cd frontend
npm ci                 # reproducible install from package-lock.json
npm run build          # emits frontend/dist/ served at /app
cd ..
```

For development with hot reload use `npm run dev` (Vite on :5173, proxies
`/api` to :8000).

## 5. Start the stack

Three long-running processes. Easiest path is four terminal panes (or a
tmux layout):

```bash
# Terminal 1 - MediaMTX (RTSP server on :8554)
./phase3-fullstack/bin/mediamtx phase3-fullstack/configs/mediamtx.yml

# Terminal 2 - loop the archived video into MediaMTX as a live publisher
./phase3-fullstack/scripts/run_rtsp.sh

# Terminal 3 - FastAPI (tracker + signal sim + REST + WS)
export TRAFFIC_INTEL_JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export TRAFFIC_INTEL_JWT_TTL_MIN=30
export TRAFFIC_INTEL_VIEWER_PW=viewer123
export TRAFFIC_INTEL_OPERATOR_PW=operator123
export TRAFFIC_INTEL_ADMIN_PW=admin123
uvicorn traffic_intel_phase3.poc_wadi_saqra.server:app --host 0.0.0.0 --port 8000

# Terminal 4 - Vite dev server (optional; the FastAPI app also serves
# the built SPA at /app)
cd frontend && npm run dev
```

If you prefer a single-command launcher, wrap the above in
`phase3-fullstack/scripts/run_full_stack.sh` (not shipped; add one locally
if needed).

## 6. Seed the database and create users

The first FastAPI boot does both:

- `get_db()` applies `storage/schema.sql` (11 tables).
- `ensure_default_users()` inserts `viewer` / `operator` / `admin` using
  the env passwords set above.

Verify:

```bash
sqlite3 phase3-fullstack/data/traffic_intel.db \
  "SELECT id, username, role FROM users;"
```

## 7. Log in

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python -m json.tool
```

Response contains a `token` — use `Authorization: Bearer <token>` on any
privileged endpoint (e.g. `/api/audit/log`).

## 8. Retrain the forecaster (optional)

```bash
forecast-ml-train \
  --counts-dir data/detector_counts \
  --signals-dir data/signal_logs \
  --lgb-out models/forecast_lgb.json \
  --report-out models/forecast_metrics.json \
  --skip-lstm
```

Retrains in ≈10 min on CPU; new metrics land in
`models/forecast_metrics.json` and the FastAPI `/api/forecast` endpoints
pick the new bundle up on process restart.

## 9. Run the tests

```bash
pytest tests/phase3 -x --tb=short
pytest phase1-sandbox phase2-feasibility   # legacy suites
```
