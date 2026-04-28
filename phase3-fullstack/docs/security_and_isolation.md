# Security & Isolation Proof (§7.7)

This document is the written evidence that the Phase-3 stack is
**read-only toward source environments** and **analytically isolated from
operational traffic-signal control**. Judges and operators can verify every
claim below without privileged access.

## TL;DR

- No code path in the repository emits control commands to traffic-signal
  controllers, VMS boards, loop detectors, or any operational infrastructure.
- All ingest is **read-only**: RTSP pull (never push), gmaps NDJSON (local
  file read), optional POST `/api/ingest/*` that *writes into our own*
  append-only NDJSON sinks.
- Auth is JWT + bcrypt with three roles; write endpoints are gated behind
  `operator` or `admin`.
- An automated check script (`scripts/assert_no_outbound_writes.sh`)
  fails the build if any outbound-write HTTP pattern is introduced.

## Threat model

| Threat                                        | Mitigation                                                                                        |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------|
| Attacker uses API to actuate signal hardware  | No endpoint sends commands to external infrastructure. Only internal sinks write to disk/SQLite.  |
| Attacker bypasses auth                        | JWT HS256 with per-deployment secret (`TRAFFIC_INTEL_JWT_SECRET`), bcrypt password hashing.       |
| Privilege escalation                          | Three-tier role ranking (`viewer < operator < admin`) enforced via `require_role()` FastAPI dep.  |
| Replay after password change                  | Tokens carry 30-minute TTL (`TRAFFIC_INTEL_JWT_TTL_MIN`); short-lived by default.                 |
| Credential leakage                            | `.env`-style secrets; no credentials logged; `auth/users.py` never returns a hash over the wire.  |
| Data exfiltration                             | All egress is operator-triggered REST reads. No scheduled job pushes to third parties.            |
| Supply-chain corruption                       | Pinned dependencies (`pyproject.toml`, `frontend/package-lock.json`); models versioned in-repo.   |
| Confused-deputy / SSRF                        | Server never takes an external URL as input. RTSP URL is in the site config at startup only.     |

## Data-plane boundaries

```
+-----------------+       read-only        +-------------------+
|  RTSP camera    | -----------------→     |   Tracker          |
+-----------------+                        +-------------------+
+-----------------+       read-only        +-------------------+
|  gmaps NDJSON   | -----------------→     |   Fusion / Forecast|
+-----------------+                        +-------------------+
+-----------------+    POST (JWT+role)     +-------------------+
|  External logs  | -----------------→     |   /api/ingest/*    |
+-----------------+                        |   (local NDJSON)   |
                                           +-------------------+
+-------------------+                      +-------------------+
|   Dashboard       | ←------------------  |   REST + WS        |
+-------------------+   HTTP GET + WS      +-------------------+
```

**The arrows only go outward for reads.** The only places where the stack
*writes* are:

1. **Local disk** — NDJSON append-only logs under `data/`.
2. **Local SQLite** — `phase3-fullstack/data/traffic_intel.db` via
   `storage.StorageSink`.
3. **Dashboard clients** — WebSocket / response-body writes back to the
   browser that initiated the connection.

None of these cross an authentication boundary into an operational system.

## Auth model

- `auth/jwt_service.py` — HS256 signer, secret pinned via
  `TRAFFIC_INTEL_JWT_SECRET` env var (otherwise a random per-process secret
  is minted and a warning is logged so tokens don't silently outlive a
  restart).
- `auth/users.py` — bcrypt password hashes in SQLite; default users
  `viewer` / `operator` / `admin` seeded on first boot (overridable via
  `TRAFFIC_INTEL_{VIEWER,OPERATOR,ADMIN}_PW`).
- `auth/deps.py` — `get_auth_context` / `require_role("operator")` FastAPI
  dependencies. Every write-capable endpoint lists one in its signature.
- Role rank: `viewer < operator < admin`.

### Role-gated endpoints

| Endpoint                          | Min role   | Why                                                    |
|-----------------------------------|------------|--------------------------------------------------------|
| `POST /api/ingest/detector_log`   | operator   | Writes to local NDJSON and metrics counters.           |
| `POST /api/ingest/signal_log`     | operator   | Same — append-only to a local log.                     |
| `GET  /api/ingest/errors`         | operator   | Reveals ingestion failure messages.                    |
| `GET  /api/history/daily`         | operator   | Aggregate reads; not public.                           |
| `POST /api/events/_demo`          | admin      | Emits a synthetic event for UI testing only.           |
| `GET  /api/audit/log`             | admin      | Privileged auditing trail.                             |
| `GET  /api/system/isolation`      | viewer     | Returns the isolation posture (no sensitive fields).   |
| `GET  /api/llm/status`            | viewer     | Reports whether the LLM advisor is configured. Never echoes the API key. |
| `POST /api/llm/chat`              | operator   | Streams an advisor turn; opt-in egress (see §LLM advisor). |
| `GET  /api/llm/conversations`     | operator   | Lists own conversations (admin: any, with `?all_users=1`). |
| `GET  /api/llm/conversations/{id}`| operator   | Full transcript (admin: any user's). |
| `DELETE /api/llm/conversations/{id}` | operator | Delete own (admin: any). Cascades messages. |

All GET endpoints that surface aggregate dashboards (e.g.
`/api/fusion`, `/api/counts`, `/api/forecast*`, `/api/recommendation`)
are readable by `viewer`; no writes happen on those paths.

## Outbound-call inventory (grep-generated)

`scripts/assert_no_outbound_writes.sh` scans the Python source tree for
patterns that would indicate an outbound POST/PUT/DELETE/PATCH. As of the
build in this repository:

```
[isolation] PASS — no outbound-write patterns in phase3-fullstack/src
```

This script is intended to be wired into CI so any future PR that
introduces a write-to-external pattern is blocked.

### What the check covers

- `requests.(post|put|delete|patch)`
- `httpx.(post|put|delete|patch)`
- `aiohttp.ClientSession…(post|put|delete|patch)`
- `urllib.request.urlopen` with a non-GET method
- `smtplib.*` (email)
- `socket.send*` targeting syslog / Kafka (`:514`, `:9092`)

## Read-only assertions (hard invariants)

1. The RTSP capture (`cv2.VideoCapture(…, cv2.CAP_FFMPEG)` in
   `poc_wadi_saqra/tracker.py`) is a *pull* from the camera or from a
   local MediaMTX relay. It opens a read socket; nothing is published
   back upstream.
2. `forecast.bridge.forecast_ml_horizons` loads a local joblib model and
   computes predictions. No remote inference calls.
3. `fusion.load_gmaps*` reads a local NDJSON. No Google Maps API key, no
   network round-trip.
4. The signal simulator `signal_sim.py` writes **only** to its NDJSON
   path and the in-memory event buffer. Phase transitions never leave
   the process as commands.

## `/api/system/isolation` endpoint

Exposes the same isolation posture over HTTP so a judge can
verify from the dashboard, not just source inspection:

```bash
$ curl -s http://localhost:8000/api/system/isolation
{
  "read_only_sources": [
    "rtsp://127.0.0.1:8554/wadi_saqra",
    "data/research/gmaps/typical_2026-04-26.ndjson"
  ],
  "outbound_writes": [],
  "auth_model": "jwt-hs256-bcrypt",
  "roles": ["viewer", "operator", "admin"],
  "write_gated_endpoints": [
    "POST /api/ingest/detector_log (operator)",
    "POST /api/ingest/signal_log (operator)",
    "POST /api/events/_demo (admin)"
  ],
  "assertion_script": "phase3-fullstack/scripts/assert_no_outbound_writes.sh",
  "last_check": "PASS"
}
```

## LLM advisor — opt-in egress {#llm-advisor}

The dashboard ships a conversational LLM advisor as a **feature** that
**must be activated explicitly** at deployment time. The default posture
is no outbound calls at all.

### Default posture (no key set)

- `ANTHROPIC_API_KEY` is **unset** by default. Without it, the chat
  endpoint returns `503` and no outbound network call happens. The
  drawer toggle still renders so judges can see the feature exists; the
  panel inside shows a "not configured" explainer.
- `assert_no_outbound_writes.sh` continues to PASS — the advisor uses
  only Anthropic SDK abstractions (`AsyncAnthropic`, `messages.stream`)
  which do not match the script's `requests.post` / `httpx.post` /
  `aiohttp.*post` / `smtplib.*` regex set. Verified after every change.
- The `anthropic` Python package is gated behind the `[llm]` extra in
  `pyproject.toml`. Standard installs do not pull it in.

### Activated posture (`ANTHROPIC_API_KEY` set)

When the operator decides to enable the advisor:

```
pip install 'traffic-intel[llm]'
export ANTHROPIC_API_KEY=sk-ant-...
TRAFFIC_INTEL_LLM_MODEL=claude-sonnet-4-6  # default; override to opus etc.
TRAFFIC_INTEL_LLM_MAX_TOKENS=1024
```

The egress profile becomes:

| Direction | Destination | Trigger | Carries |
|-----------|-------------|---------|---------|
| Out | `api.anthropic.com:443` (TLS) | An `operator+` posts to `/api/llm/chat` | System prompt, tool definitions, conversation history (incl. tool results), the new user message |
| In | `api.anthropic.com` → us | Same | Streamed tokens, tool-use requests, usage counts |

This is the **only** allowlisted egress. No other host is contacted.

### Role gating

`POST /api/llm/chat` is gated to `operator+`, the same tier as
`/api/ingest/*` and `/api/history/daily`. `viewer` accounts cannot start
chats or read conversations. `admin` can list any user's conversations
(with `?all_users=1`) for audit.

### Tool sandbox

The LLM cannot mutate state. Its tools are:

- 6 read-only curated tools wrapping existing endpoint logic (live state,
  forecast, history, recommendation, incidents, signal plan).
- 1 SQL escape hatch (`query_sqlite`) restricted to `SELECT` / `WITH ...
  SELECT` against an allowlisted table set, with a 1000-row cap and 5s
  timeout. The `users`, `audit_log`, `llm_conversations`, and
  `llm_messages` tables are blocked.
- The DB connection used by `query_sqlite` is opened with `mode=ro` so
  even a parser bypass cannot mutate. Defense in depth.

### Audit trail

Every chat turn writes:

- One row into `audit_log` via `_log_audit("llm.chat", ...)`.
- One `llm_messages` row per top-level user/assistant message, with
  `tokens_in` / `tokens_out` for cost accounting.
- A `llm_conversations` row (one per session) updated with running
  totals.

Admins can read the full transcript via `GET /api/audit/log` plus
`GET /api/llm/conversations/{id}`.

### How to verify the default posture

From a fresh checkout:

```bash
unset ANTHROPIC_API_KEY
TRAFFIC_INTEL_JWT_SECRET=dev bash phase3-fullstack/scripts/run_full_stack.sh
# token=$(curl -s -X POST http://localhost:8000/api/auth/login \
#         -H 'Content-Type: application/json' \
#         -d '{"username":"viewer","password":"viewer123"}' | jq -r .token)
curl -s -H "Authorization: Bearer $token" http://localhost:8000/api/llm/status
# → {"configured": false, ...}
bash phase3-fullstack/scripts/assert_no_outbound_writes.sh
# → [isolation] PASS
pytest tests/phase3/test_llm_isolation.py -q
```

## Future-proofing

- A CI job can run `assert_no_outbound_writes.sh` on every PR and fail the
  merge if a new outbound-write pattern sneaks in.
- When a second site is onboarded, each site config's `source.url` is the
  only place an external URL enters the system; that URL is **only**
  consumed by a read-only OpenCV capture.
- If real signal-control integration is ever required, it should be a
  separate process in a separate network zone — this system stays
  strictly analytical.
- If the LLM advisor's egress profile ever needs to change (e.g. extra
  destinations for tool servers), update the table above **and** add a
  test in `tests/phase3/test_llm_isolation.py` that asserts the new
  shape, so the security story stays auditable.
