# LLM Advisor — Design Spec

**Date:** 2026-04-28
**Status:** Approved (Q1–Q6 + Section 1 confirmed in brainstorming session)
**Scope:** Add a conversational LLM advisor to the Phase-3 Wadi Saqra dashboard,
shipped as an opt-in feature gated by `ANTHROPIC_API_KEY`. Without a key the
feature is visible-but-inactive, preserving §7.7 isolation by default.

## 1. Decisions locked in brainstorming

| # | Decision | Rationale |
|---|---|---|
| Q1 | **Conversational Q&A** — operator types questions, LLM answers grounded via tool use against live data | Highest demo ceiling — judges can interrogate the system live |
| Q2 | **Anthropic Claude API**, opt-in via `ANTHROPIC_API_KEY`. No key → no calls. | Best tool-use reliability; isolation preserved by default; activation is a deployment choice |
| Q3 | **Hybrid tools** — 6 curated 1:1-with-endpoint tools + 1 SQL escape-hatch | Curated tools handle 90% of demo questions reliably; SQL handles "wow" curveballs |
| Q4 | **Right-side drawer** that follows operator across all `/app/*` pages | Operator stays in current page; ask "what about this?" with full visual context |
| Q5 | **Visible toggle, "not configured" explainer when no key** | Honest demo posture — feature exists, architecture is built, isolation is the deliberate default |
| Q6 | Role gate `operator+`, persist every turn to SQLite, SSE streaming, model `claude-sonnet-4-6` (env override) | Same gate as `/api/ingest/*` and `/api/history/daily`; consistent with §7.7 audit story; streaming for typing-feel demo |

## 2. Module layout & data flow

### Backend package: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/llm/`

| File | Responsibility | LOC budget |
|---|---|---|
| `client.py` | Lazy `anthropic.Anthropic` factory. `is_configured() -> bool`. Raises `LLMNotConfiguredError` if chat attempted with no key (caught → 503). | ~80 |
| `tools.py` | Tool schema definitions (Anthropic tool format) + dispatch table. Each handler `(args: dict, ctx: LLMContext) -> dict`. | ~200 |
| `safety.py` | SQL guardrails: `parse_select_only(sql)`, table allowlist, row cap (1000), per-query timeout (5s via `progress_handler`). | ~120 |
| `system_prompt.py` | Domain-tuned prompt (Wadi Saqra context, 3-phase NS→E→W, 120s cycle, near-saturation rules). Pure function for snapshot tests. | ~80 |
| `conversations.py` | `start_conversation`, `append_turn`, `load_history`, `list_user_conversations`, `delete_conversation`. | ~150 |
| `runner.py` | Streaming loop. `async for ev in run_chat(...)` yields `text_delta` / `tool_use` / `tool_result` / `turn_done`. Manual agentic loop with `client.messages.stream()`. | ~200 |

**Why this split:** `runner.py` is the only file that knows about SSE protocol;
`tools.py` is the only file that knows the Anthropic tool schema; `safety.py` is
independently testable. Each unit stays small and replaceable.

### Per-turn data flow

```
Browser drawer
  └─ POST /api/llm/chat (SSE, body: {conversation_id?, message})
     └─ server.py: auth → require_role('operator') → load LLMContext
        └─ runner.run_chat()
           ├─ conversations.append_turn(role='user', content=msg)
           ├─ loop:
           │   ├─ client.messages.stream(model, tools, system, history)
           │   ├─ forward text_deltas to SSE
           │   ├─ on tool_use block:
           │   │   ├─ tools.dispatch(name, args, ctx)
           │   │   │   ├─ curated tool → existing fusion/forecast/db helpers
           │   │   │   └─ query_sqlite → safety.parse → exec → cap rows
           │   │   ├─ append tool_result to messages
           │   │   └─ emit SSE {type:'tool_use', name, args}
           │   └─ exit on stop_reason == 'end_turn'
           ├─ conversations.append_turn(role='assistant', content=full_text)
           └─ SSE: {type:'turn_done', tokens_in, tokens_out}
```

The SSE `tool_use` events feed an in-drawer context strip — the operator
sees "checking forecast" → chip lights up → answer arrives. That visible
grounding is the trust signal.

## 3. Tool surface + database schema

### 3.1 Tools (Anthropic tool-use format)

| # | Tool | Args | Returns | Backed by |
|---|---|---|---|---|
| 1 | `get_current_state` | (none) | `{local_hour, fused: Approach→FusedRow, signal_phase, plan_mode}` | Calls `fusion.fuse(...)` directly |
| 2 | `get_forecast` | `horizon_min: 0\|15\|30\|60`, `approach?: S\|N\|E\|W` | `{horizon, predicted: {approach: count}, model_metrics}` | `forecast_ml_horizons(...)` |
| 3 | `get_history` | `start_iso`, `end_iso`, `bucket_minutes: 15`, `approach?` | `{rows: [{ts, approach, count}]}` | SQL on `detector_counts` |
| 4 | `get_recommendation` | `scope: 'now'\|'forecast'` | `{mode, cycle_seconds, phases, comparison, near_saturation}` | `webster_three_phase(...)` |
| 5 | `list_incidents` | `since_iso?`, `types?: list[str]`, `limit: int (≤100)` | `{rows: [{ts, type, approach, severity, ...}]}` | SQL on `incidents` |
| 6 | `get_signal_plan` | (none) | `{mode, current_plan, video_anchor}` | reads site config + `signal_sim` state |
| 7 | `query_sqlite` | `sql: str` | `{columns, rows, row_count, truncated}` | `safety.parse_select_only` → exec |

### 3.2 SQL escape hatch — `query_sqlite` guardrails

**Allowlist (read-only):** `detector_counts`, `signal_events`, `incidents`,
`forecasts`, `recommendations`, `system_metrics`, `sites`, `ingest_errors`.

**Blocklist (privacy/security):** `users`, `audit_log`, `llm_conversations`,
`llm_messages`. Any reference returns a tool error, not a hallucination.

**Enforced via `safety.parse_select_only`:**
- Reject if not starting with `SELECT` or `WITH ... SELECT` (no `INSERT/UPDATE/DELETE/DROP/ATTACH/PRAGMA`)
- Reject if any `FROM`/`JOIN` references a non-allowlisted table
- Cap result at 1000 rows (set `truncated: true` if hit)
- 5-second timeout via `sqlite3` `set_progress_handler` (interrupts long scans)
- Read-only connection: open with `mode=ro` URI

### 3.3 Database schema additions (`schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS llm_conversations (
  id          TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL,
  username    TEXT NOT NULL,
  site_id     TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  title       TEXT,
  model       TEXT NOT NULL,
  total_tokens_in   INTEGER NOT NULL DEFAULT 0,
  total_tokens_out  INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (site_id) REFERENCES sites(site_id)
);
CREATE INDEX IF NOT EXISTS idx_llm_conv_user ON llm_conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS llm_messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool_use','tool_result')),
  content         TEXT NOT NULL,           -- text or JSON-encoded blocks
  tool_name       TEXT,
  tool_use_id     TEXT,
  tokens_in       INTEGER,
  tokens_out      INTEGER,
  FOREIGN KEY (conversation_id) REFERENCES llm_conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_llm_msg_conv ON llm_messages(conversation_id, ts);
```

## 4. HTTP API + frontend integration

### 4.1 Endpoints (added to `poc_wadi_saqra/server.py`)

| Method | Path | Min role | Body / Response |
|---|---|---|---|
| `GET` | `/api/llm/status` | viewer | `{configured: bool, model: str, role_required: 'operator'}` |
| `POST` | `/api/llm/chat` | operator | Body `{conversation_id?: str, message: str}`. SSE stream of `{type, ...}` events. |
| `GET` | `/api/llm/conversations` | operator | List user's own conversations (admins see all via `?all=1`). |
| `GET` | `/api/llm/conversations/{id}` | operator | Full transcript (user owns or is admin). |
| `DELETE` | `/api/llm/conversations/{id}` | operator | Delete user's own (admin: any). Cascades to messages. |

**SSE event types** emitted by `/api/llm/chat`:
```
{type: 'conversation', conversation_id: '...'}    // first event of a session
{type: 'text_delta', text: '...'}                 // for each chunk
{type: 'tool_use', tool_use_id, name, args}       // before dispatch
{type: 'tool_result', tool_use_id, ok: bool}      // after dispatch
{type: 'turn_done', stop_reason, tokens_in, tokens_out}
{type: 'error', message: '...'}                   // on any failure
```

### 4.2 Frontend additions

```
frontend/src/
├── api/
│   └── llm.ts                        # typed client + SSE EventSource wrapper
├── hooks/
│   └── useChatSession.ts             # state machine: idle | streaming | error
└── components/
    ├── AdvisorDrawer.tsx             # right-side drawer, mounted in App.tsx
    └── AdvisorDrawer.module.css      # styles (matches existing dashboard dark theme)
```

**Drawer behavior:**
- Toggle button: bottom-right floating, visible only when authenticated.
- Closed: 56×56 px circle with bot icon.
- Open: 420 px wide panel, full viewport height, slides in from right.
- Empty (no-key) state: "LLM Advisor — opt-in" explainer + link to `/api/docs/security_and_isolation.md#llm-advisor`.
- Configured state: message list (user + assistant + tool-use chips), input at bottom, "New chat" button, conversation history dropdown.
- Roles below `operator`: drawer shows the not-configured-or-unauthorised explainer (same visual; security_and_isolation doc explains why).

**App.tsx:** `<AdvisorDrawer />` rendered inside `<Shell>` when `isAuthenticated` is true; not present on `/login`.

## 5. Security & isolation amendment

### 5.1 `assert_no_outbound_writes.sh` (no change to grep patterns)

The Anthropic Python SDK exposes high-level methods (`client.messages.stream(...)`),
not raw `httpx.post(...)`. Our llm/client.py only uses these abstractions, so
the existing regex (`requests.post`, `httpx.post`, etc.) does not trip on our
source tree. Verified by running the script after implementation.

### 5.2 `security_and_isolation.md` — new section

Append a "LLM Advisor (opt-in)" section with:
- **Default posture:** `ANTHROPIC_API_KEY` unset → no outbound calls. Verifiable
  via `/api/llm/status` returning `{configured: false}` and pytest
  `test_llm_isolation.py`.
- **When activated:** the Anthropic Messages API (`api.anthropic.com`) is the
  *only* allowlisted egress. No data flows back to operational signal hardware.
- **Role gate:** `operator+` for `POST /api/llm/chat`. Same tier as ingest endpoints.
- **Audit:** every prompt and response persists to `llm_messages` with
  `user_id` + `ts` + token counts. Admins read via standard `/api/audit`
  surface (extended to include LLM activity).
- **Failure modes:** `LLMNotConfiguredError` → 503; rate-limited Anthropic →
  429 surfaced verbatim to the operator; tool error → SSE `error` event.

## 6. Testing plan

| File | What it asserts |
|---|---|
| `tests/phase3/test_llm_status.py` | `/api/llm/status` returns `configured: false` when env unset; `true` when set; role gate on chat endpoint without key returns 503 (not 401) — i.e. auth before unconfigured check |
| `tests/phase3/test_llm_safety.py` | `parse_select_only` accepts SELECT/WITH-SELECT; rejects INSERT/UPDATE/DELETE/DROP/PRAGMA; rejects blocklisted tables; row cap; timeout interrupts long query |
| `tests/phase3/test_llm_tools.py` | Each curated tool returns expected shape against an in-memory DB seeded with Wadi Saqra fixtures |
| `tests/phase3/test_llm_persistence.py` | `start_conversation` + `append_turn` round-trip; `load_history` orders by ts; `delete_conversation` cascades |
| `tests/phase3/test_llm_isolation.py` | When `ANTHROPIC_API_KEY` is unset, `client.is_configured()` is False; calling `client.get()` raises `LLMNotConfiguredError`; isolation script still PASSes after our changes |

Acceptance: `pytest tests/phase3 -q` green for all existing 37 tests + ~15 new
ones. `bash phase3-fullstack/scripts/assert_no_outbound_writes.sh` PASSes.

## 7. Out of scope

- Vision (camera frame in prompt) — Q1 chose B over D; can add later.
- Anomaly explainer / signal-plan reasoner (Q1 options C and E) — separate spec.
- Conversation export to CSV/PDF — operators can read transcripts via the API.
- Multi-site routing — `site_id` already on `llm_conversations`; UI to switch
  between sites is out of scope for this build.

## 8. Build order

1. Spec + commit (this doc)
2. `pyproject.toml` + `schema.sql`
3. `llm/` package (system_prompt → safety → conversations → tools → client → runner)
4. `server.py` endpoints
5. Frontend (`api/llm.ts` → `hooks/useChatSession.ts` → `AdvisorDrawer.tsx` → `App.tsx` mount)
6. `security_and_isolation.md` amendment
7. Tests + run full suite + isolation script
