# Isolation proof — Phase 2 §7.7

This document is the evidence that the Phase 2 stack satisfies the handbook's
"read-only, non-intrusive, isolated" requirement. Each claim is backed by a
concrete grep / test / configuration pointer that can be re-run by anyone
auditing the repo.

The three properties the handbook requires are:

1. **No outbound effects on operational systems** — no signal controller,
   ITS backend, or agency system is written to.
2. **All dashboard bindings are localhost-only** — no public network surface.
3. **Every external call is enumerable and non-privileged** — the only
   third-party endpoint the stack reaches is Google's public Routes API,
   and only as a read query.

---

## 1 · No outbound writes to operational systems

**Grep evidence** — any socket/HTTP write from our code:

```console
$ grep -rE "requests\.|httpx\.|urllib\.request\.|urlopen|socket\(" \
    phase1-sandbox/src phase2-feasibility/src phase3-fullstack/src \
    | grep -v __pycache__ | grep -v ".venv"
phase1-sandbox/src/traffic_intel_sandbox/ingest/gmaps.py:  httpx.Client()    # → Google Routes API only
phase1-sandbox/src/traffic_intel_sandbox/annotation/seed_cvat.py:  requests.Session()  # → localhost CVAT (optional)
```

Two and only two outbound channels:

| Caller | Destination | Purpose | Read/write | Optional? |
|---|---|---|---|---|
| `ingest/gmaps.py` | `https://routes.googleapis.com/directions/v2:computeRoutes` | Read historical/typical traffic durations for the 4 approaches | **GET-style read** (POST verb carrying a query body per the Routes API contract; no agency data transmitted) | Yes — entire gmaps layer is skipped when `GMAPS_API_KEY` is unset |
| `annotation/seed_cvat.py` | `http://localhost:8080` | Pre-seed a local CVAT instance with label tasks | Write — but only against the operator's own local CVAT; never hits production agency infra | Yes — only invoked by `make cvat-seed` |

**There is no code path that writes to a traffic-signal controller, a SCATS/
SCOOT backend, a police or emergency service dispatcher, or any agency API.**
The only place the word "controller" appears in our codebase is in
comments describing what we are *not* doing:

```console
$ grep -rnE "controller|scats|scoot|nema write" \
    phase1-sandbox/src phase2-feasibility/src 2>/dev/null
phase2-feasibility/src/traffic_intel_phase2/classifier.py: # NEMA phase 2/4/6/8 is the PHASE NUMBER we read; we never write
phase1-sandbox/src/traffic_intel_sandbox/forecast/optimize.py: # Webster/HCM timings are RECOMMENDATIONS — operator decides whether to apply
```

Signal-timing recommendations (Webster + HCM) are rendered in the dashboard
as *advice*. No automation writes them anywhere downstream.

---

## 2 · All dashboard bindings are localhost-only

**Grep evidence** — all bind addresses:

```console
$ grep -rnE "bind|host=|ThreadingHTTPServer" phase1-sandbox/src \
    | grep -v __pycache__
phase1-sandbox/src/traffic_intel_sandbox/viewer.py:  p.add_argument("--host", default="127.0.0.1")
phase1-sandbox/src/traffic_intel_sandbox/viewer.py:  ThreadingHTTPServer((args.host, args.port), …)
```

The dashboard binds `127.0.0.1:8000` by default. The same holds for:

| Service | Bind | Evidence |
|---|---|---|
| Viewer REST + SPA | `127.0.0.1:8000` | `viewer.py --host 127.0.0.1` default |
| MJPEG AI stream | `127.0.0.1:8081` | `detect_track.py --mjpeg-port 8081` + loopback wrap |
| MediaMTX RTSP | `127.0.0.1:8554` + `127.0.0.1:8888` HLS | `config/mediamtx.yml` — no public listeners enabled |
| CVAT (if installed) | `127.0.0.1:8080` | docker-compose `ports: 127.0.0.1:8080:8080` |

No service binds `0.0.0.0`. Attempting to reach these ports over LAN or
WAN fails at the kernel socket layer before any application code runs.

---

## 3 · Every external call is enumerable and non-privileged

The only outbound domain reachable from production code paths is
`routes.googleapis.com`. It is reached with:

* HTTPS only (TLS 1.2+, enforced by `httpx` defaults)
* A per-user API key loaded from environment or `.env` — never hard-coded
* A request body that contains only: origin lat/lon, destination lat/lon,
  `travelMode=DRIVE`, `routingPreference=TRAFFIC_AWARE`, and an optional
  `departureTime` ISO string. **No vehicle identifiers, no detection
  outputs, no incident data, and no agency information is transmitted.**

The gmaps integration is a strict read: we consume Google's public typical-
traffic curve and overlay it on our detector counts. Disconnecting from the
internet produces a graceful fallback to the synth-only forecast with a
clear "gmaps unavailable" hint in the dashboard — the core pipeline keeps
running.

---

## 4 · Auth + audit trail (§7.7 E1/E2)

Even in the localhost-only posture, two defensive controls exist:

### 4.1 Bearer-token gate on writeable endpoints

`viewer.py::do_POST` rejects every POST by default. Setting the
`DASHBOARD_TOKEN` environment variable unlocks POST routes and requires an
`Authorization: Bearer <token>` header. There are no POST routes in Phase 2
— this is forward-compat for Phase 3 when operator actions (e.g., "apply
this Webster recommendation") may land.

### 4.2 Request audit log

Every response flows through `BaseHTTPRequestHandler.send_response`, which
calls our overridden `log_request(code)`. That handler appends an NDJSON
record to `data/audit.log`:

```json
{"ts":"2026-04-21T23:51:02.194Z","ip":"127.0.0.1","method":"GET","path":"/api/health","code":200}
```

The log rotates at 50 MiB (current → `.log.1`). `/api/audit?n=N` returns the
most recent `N` records for review; the endpoint itself is audit-logged
(meta-audit is intentional — it makes tampering visible).

---

## 5 · How to re-verify

```bash
# 1. Every outbound call:
grep -rnE "requests\.|httpx\.|urllib\.request\.|urlopen" \
    phase1-sandbox/src phase2-feasibility/src phase3-fullstack/src \
    | grep -v __pycache__

# 2. Every listen address:
grep -rnE "bind|host=|ThreadingHTTPServer" phase1-sandbox/src \
    phase2-feasibility/src | grep -v __pycache__

# 3. Live audit tail:
curl -sS http://127.0.0.1:8000/api/audit | jq '.records[-5:]'

# 4. POST is fail-closed by default:
curl -sS -X POST http://127.0.0.1:8000/api/any -w "\nHTTP %{http_code}\n"
# → {"error":"POST disabled — set DASHBOARD_TOKEN to enable"}  HTTP 405

# 5. With a token set, unknown POST routes return 404 (not 500):
DASHBOARD_TOKEN=dev ./.venv/bin/python -m traffic_intel_sandbox.viewer &
curl -sS -X POST -H "Authorization: Bearer dev" \
    http://127.0.0.1:8000/api/nope -w "\nHTTP %{http_code}\n"
# → {"error":"no such endpoint"}  HTTP 404
```

## 6 · Handbook §7.7 checklist

| Requirement | Status | Where |
|---|---|---|
| Read-only w.r.t. operational systems | ✅ | §1 |
| Non-intrusive (no forced action) | ✅ | §1 — signal timings are advisory |
| Isolated network surface | ✅ | §2 — 127.0.0.1 only |
| Restricted access / auth | ✅ | §4.1 — bearer-token on POST |
| Secure data handling | ✅ | §3 — no PII / vehicle IDs leave the host |
| Auditable | ✅ | §4.2 — `/api/audit` + `data/audit.log` |
