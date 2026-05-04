# MCP Tools — Reference

The traffic-intel MCP server exposes **8 tools** that an LLM (Claude Desktop,
Cursor, the in-app `/api/llm/chat` advisor, etc.) can call to reason about the
intersection. The same `TOOL_SCHEMAS` + `dispatch` are used by both surfaces:

- **Standalone MCP server** — `phase3-fullstack/src/traffic_intel_mcp/server.py`
  — stdio transport, started via `python -m traffic_intel_mcp`. Reads only the
  persisted SQLite DB (no live tracker process needed).
- **In-process LLM advisor** — `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/server.py`
  `/api/llm/chat` — same tools, but the live providers
  (`get_current_state`, `get_forecast`, `get_recommendation`) hit the running
  tracker / forecast / Webster modules directly.

## Tool surface

Source of truth: `phase3-fullstack/src/traffic_intel_phase3/poc_wadi_saqra/llm/tools.py`.

| # | Tool | Args | Source | Purpose |
| - | --- | --- | --- | --- |
| 1 | `get_current_state` | — | live tracker (in-app) / latest 2-min DB snapshot (MCP) | per-approach counts, queue, gmaps congestion, current phase |
| 2 | `get_forecast` | `horizon_min: 0\|15\|30\|60`, `approach?: S\|N\|E\|W` | LightGBM (in-app) / `forecasts` table (MCP) | predicted demand at horizon |
| 3 | `get_history` | `start_iso`, `end_iso`, `bucket_minutes?: 15\|30\|60`, `approach?` | SQLite `detector_counts` | historical per-approach counts |
| 4 | `get_recommendation` | `scope: now\|forecast` | Webster/HCM (in-app) / `recommendations` table (MCP) | green-time advisory plan + delay reduction |
| 5 | `list_incidents` | `since_iso?`, `types?`, `limit?: 1–100` | SQLite `incidents` | wrong_way / spillback / stalled / etc. |
| 6 | `get_signal_plan` | — | site config | current field plan + mode + anchor |
| 7 | **`get_typical_day_gmaps`** ★ | `corridor?: N\|S\|E\|W`, `hour?: 0.0–23.5` | `data/research/gmaps/typical_2026-04-26.json` | Google-typical congestion grid |
| 8 | `query_sqlite` | `sql: SELECT…` | SQLite (allowlisted tables) | escape hatch, max 1000 rows / 5 s |

★ = added in Dashboard v2 batch.

## get_typical_day_gmaps — the new tool

### Why

Without it, the advisor only sees what's happening *right now*. To answer "is
this peak unusually heavy?" or "should we apply tomorrow's recommended split
now?", the model needs the **typical-day baseline**.

### Source

`tools/build_typical_day_json.py` reads
`data/research/gmaps/typical_2026-04-26.ndjson` (192 rows, 4 corridors × 48
half-hour bins from the Google Routes API) and emits a clean JSON keyed by
`corridors[corridor][half_hour]`. Cells where the API errored are `null`
(corridor S has 2 such cells — kept honest, not synthesised).

```bash
.venv/bin/python tools/build_typical_day_json.py
# → data/research/gmaps/typical_2026-04-26.json (190/192 cells filled)
```

### Schema

```json
{
  "site_id": "wadi_saqra",
  "captured": "2026-04-26",
  "schema_version": 1,
  "corridors": {
    "N": {
      "0.0":  { "congestion_ratio": 0.93, "congestion_label": "free",  "speed_kmh": 20.6, "static_speed_kmh": 19.1, "duration_s": 421, "static_duration_s": 453 },
      "0.5":  { ... },
      "...":  "every half-hour 0.0..23.5",
      "23.5": { ... }
    },
    "S": { ... },
    "E": { ... },
    "W": { ... }
  },
  "summary": {
    "peak_hour_per_corridor": { "N": 15.5, "S": 16.0, "E": 15.0, "W": 16.0 },
    "daily_avg_congestion_ratio": { "N": 0.886, "S": 0.926, "E": 1.125, "W": 0.938 }
  }
}
```

### Filtering

| Args | Returns |
| --- | --- |
| `{}` | full grid + summary |
| `{ corridor: "E" }` | one corridor, all 48 bins, + summary |
| `{ hour: 14.0 }` | one half-hour slice across all 4 corridors, + summary |
| `{ corridor: "E", hour: 14.0 }` | single row + summary |

Hours snap to the nearest half-hour (`14.2` → `14.0`, `14.3` → `14.5`).

### Example LLM turn

```
User:    How does the East approach right now compare to typical for this hour?

Tools:   get_current_state ()
         → { approaches: { E: { count_in_bin: 47, …}}}
         get_typical_day_gmaps ({ corridor: "E", hour: 14.0 })
         → { row: { congestion_ratio: 1.32, congestion_label: "light", speed_kmh: 15.6 }}

Claude:  East right now is running ~22% above the typical Tuesday-14:00 ratio
         (1.32 vs ~1.08 baseline). Speed is matching baseline, so it's volume-
         driven not incident-driven. No action needed unless this persists past
         15:00 — that's when typical demand peaks at 1.5× free-flow.
```

## Standalone MCP server

### Start

```bash
.venv/bin/python -m traffic_intel_mcp
# stdio; expects no port. Use .mcp.json.example to register with Claude Desktop:
```

```json
{
  "mcpServers": {
    "traffic-intel": {
      "command": ".venv/bin/python",
      "args": ["-m", "traffic_intel_mcp"],
      "env": { "MCP_LOG_LEVEL": "INFO" }
    }
  }
}
```

### Tests

```bash
.venv/bin/python -m pytest tests/phase3/test_mcp_server.py -xvs
# 11 tests, including 3 new typical-day cases:
#   - test_typical_day_gmaps_corridor_hour
#   - test_typical_day_gmaps_full_grid
#   - test_typical_day_gmaps_schema_rejects_bad_corridor
```

### Limits & guardrails

- **`query_sqlite`** is the only escape hatch and is locked to read-only
  SELECT/WITH against an allowlist (`detector_counts`, `signal_events`,
  `incidents`, `forecasts`, `recommendations`, `system_metrics`, `sites`,
  `ingest_errors`). DELETE / UPDATE / INSERT all raise validation errors.
- Max 1000 rows per query; 5 s timeout.
- The MCP server can't switch detectors, modify lanes, or restart processes —
  only the in-app advisor (which holds the live tracker reference) can. This
  is intentional: external clients shouldn't have side-effect access.

## Adding a new tool

1. Add a handler `_tool_<name>(args, ctx)` in `tools.py`
2. Register it in `_DISPATCH`
3. Add its schema to `TOOL_SCHEMAS` (Anthropic format — `name`, `description`,
   `input_schema` with JSON Schema)
4. If it needs new context (a file path, a service), add a field to
   `LLMContext` and populate it in **both**:
   - `traffic_intel_mcp/server.py` `build_context()`
   - `poc_wadi_saqra/server.py` `_llm_build_context()`
5. Add a test case in `tests/phase3/test_mcp_server.py` calling it via
   `_call_tool_sync(server, "<name>", {...})`

The schema flows automatically to the MCP `Tool` definition (`_to_mcp_tools`)
and to the Anthropic chat client. Tool count in the dashboard's AI advisor
panel auto-updates from the schema list, so no UI change needed.
