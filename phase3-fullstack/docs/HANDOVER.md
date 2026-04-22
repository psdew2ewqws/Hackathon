# Phase 3 — Handover Runbook

Operational guide for running and extending the stack after the hackathon.
Written for the engineer who inherits the repo on day one.

## Environment variables

| Variable                        | Required | Default          | Purpose                                                  |
|---------------------------------|----------|------------------|----------------------------------------------------------|
| `TRAFFIC_INTEL_JWT_SECRET`      | yes      | random per-boot  | HS256 signing key for JWT tokens                         |
| `TRAFFIC_INTEL_JWT_TTL_MIN`     | no       | 30               | Token lifetime in minutes                                |
| `TRAFFIC_INTEL_VIEWER_PW`       | no       | `viewer123`      | Seeded on first boot if `users.viewer` is missing        |
| `TRAFFIC_INTEL_OPERATOR_PW`     | no       | `operator123`    | Seeded on first boot if `users.operator` is missing      |
| `TRAFFIC_INTEL_ADMIN_PW`        | no       | `admin123`       | Seeded on first boot if `users.admin` is missing         |
| `LOG_LEVEL`                     | no       | `INFO`           | Python logging level for the FastAPI process             |

The defaults are **dev-only** and must be overridden before exposing the
dashboard to a network.

## Rotating secrets

### JWT signing secret

1. Generate a new secret: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
2. Update the deployment env (systemd `EnvironmentFile`, Kubernetes
   Secret, Docker Compose `.env`, etc.).
3. Restart the FastAPI process. All active tokens become invalid —
   operators will be bounced to the login screen.
4. Announce a ≤30-min window before the rotation so operators can finish
   in-flight actions.

### Role passwords

Prefer using the API to change passwords so the bcrypt hash is generated
server-side:

```bash
# as admin
TOKEN=$(curl -s -X POST /api/auth/login -d '{"username":"admin","password":"OLD"}' | jq -r .token)
# (add a password-reset endpoint before first production deploy — not shipped in hackathon build)
```

Interim workaround: delete the row and let `ensure_default_users()`
re-seed with the new env password:

```bash
sqlite3 phase3-fullstack/data/traffic_intel.db "DELETE FROM users WHERE username='admin';"
export TRAFFIC_INTEL_ADMIN_PW='new-strong-password'
# restart FastAPI
```

## Swapping the RTSP source

The tracker reads `source.url` from `phase3-fullstack/configs/wadi_saqra.json`.
To point at a live camera:

1. Edit the config:
   ```json
   "source": {
     "kind": "rtsp",
     "url": "rtsp://CAM_USER:CAM_PASS@camera.example.com:554/stream1",
     "ingest_fps": 10
   }
   ```
2. Stop `scripts/run_rtsp.sh` (no longer needed when the camera is live).
3. Restart the FastAPI process. Tracker reconnect logic kicks in if the
   camera drops frames.

If the camera speaks ONVIF, start MediaMTX in puller mode instead: edit
`phase3-fullstack/configs/mediamtx.yml`:

```yaml
paths:
  wadi_saqra:
    source: rtsp://CAM_USER:CAM_PASS@camera.example.com:554/stream1
    sourceOnDemand: no
```

…and keep the tracker URL pointing at `rtsp://127.0.0.1:8554/wadi_saqra`
so you get MediaMTX's reconnect + fan-out for free.

## Retraining the forecaster

```bash
forecast-ml-train \
  --counts-dir  data/detector_counts \
  --signals-dir data/signal_logs \
  --lgb-out     models/forecast_lgb.json \
  --report-out  models/forecast_metrics.json \
  --skip-lstm
```

The FastAPI process loads the LightGBM bundle lazily on each
`/api/forecast*` call, so retraining takes effect after the next request.
Review `models/forecast_metrics.json` — if the new run's `lightgbm.*.mae`
regresses, roll back by `git checkout models/forecast_lgb.json`.

## Adding a second site

1. Insert the row:
   ```sql
   INSERT INTO sites (site_id, name, lat, lng)
   VALUES ('site2', 'Site Two', 31.9, 35.9);
   ```
2. Copy the config tree:
   ```bash
   cp phase3-fullstack/configs/wadi_saqra.json      phase3-fullstack/configs/site2.json
   cp phase3-fullstack/configs/wadi_saqra_zones.json phase3-fullstack/configs/site2_zones.json
   ```
3. Update `site_id`, `source.url`, zone polygons, and the gmaps NDJSON
   path inside `site2.json`.
4. Either launch a second FastAPI process on a different port with
   `PHASE3_SITE_CFG=/…/site2.json` (requires a small patch to
   `server._load_site_cfg` to read the env var — one line) or refactor
   `server.py` to multiplex both sites in one process. The storage
   schema is already multi-site — `site_id` is an FK on every sink kind.

## Cutting a release

```bash
# 1. Bump version
sed -i 's/version = "0\.1\.0"/version = "0.2.0"/' pyproject.toml

# 2. Build frontend bundle
cd frontend && npm ci && npm run build && cd ..

# 3. Tag
git add -A
git commit -m "release: v0.2.0"
git tag -a v0.2.0 -m "Phase 3 GA"
git push --tags

# 4. Bundle
tar --exclude='.venv*' --exclude='node_modules' --exclude='*.pt' \
    -czf traffic-intel-v0.2.0.tar.gz \
    phase3-fullstack/{bin,configs,scripts,src,docs,README.md} \
    frontend/dist frontend/package*.json \
    models/forecast_lgb.json models/forecast_metrics.json \
    pyproject.toml README.md
```

The bundle excludes the large YOLO weight files (`*.pt` > 5 MB each);
downstream installers should pull them from the Ultralytics hub on first
use, mirroring the AGPL licence notice in `open-source-components.md`.

## Operational checks

- **Daily**: open `/api/health`; confirm tracker running, signal_sim
  running, sink_queue < 100.
- **Weekly**: review `audit_log` for suspicious logins; rotate any
  password with ≥ 3 `login_failed` rows in the past 7 days.
- **Monthly**: re-run `forecast-ml-train` with the latest counts + signal
  logs. Review the delta in `models/forecast_metrics.json`.
- **On schema change**: SQLite `schema.sql` is idempotent on startup but
  it does not drop columns. For destructive migrations, dump → reshape →
  load: `sqlite3 .db .dump > dump.sql && sqlite3 new.db < dump.sql`.

## Who to call

- Tracker / CV issues — whoever owns `poc_wadi_saqra/tracker.py`
- Forecast / ML — `src/forecast_ml/`
- Auth / RBAC — `auth/*`
- Database — `storage/*`
- Frontend — `frontend/src/`
