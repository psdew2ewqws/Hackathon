"""Tool definitions and dispatch for the LLM advisor.

Each tool handler takes ``(args: dict, ctx: LLMContext) -> dict``. Curated
tools delegate to live-state / forecast / recommendation / signal-plan
providers held on the context (set up by ``server.py`` at boot). The SQL
escape hatch goes through ``safety.execute_readonly``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from . import safety
from ...storage.db import Db

LOG = logging.getLogger(__name__)


class LiveStateProvider(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class ForecastProvider(Protocol):
    def __call__(self, horizon_min: int, approach: str | None) -> dict[str, Any]: ...


class RecommendationProvider(Protocol):
    def __call__(self, scope: str) -> dict[str, Any]: ...


class SignalPlanProvider(Protocol):
    def __call__(self) -> dict[str, Any]: ...


@dataclass
class LLMContext:
    """Everything tool handlers need from the server.

    Held for one chat turn; in-memory only.
    """

    db: Db
    db_path: Path
    site_id: str
    live_state: LiveStateProvider
    forecast: ForecastProvider
    recommendation: RecommendationProvider
    signal_plan: SignalPlanProvider


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _tool_get_current_state(args: dict, ctx: LLMContext) -> dict:
    return ctx.live_state()


def _tool_get_forecast(args: dict, ctx: LLMContext) -> dict:
    horizon = int(args.get("horizon_min", 15))
    if horizon not in (0, 15, 30, 60):
        return {"error": f"horizon_min must be one of 0/15/30/60, got {horizon}"}
    approach = args.get("approach")
    if approach is not None and approach not in ("S", "N", "E", "W"):
        return {"error": f"approach must be S/N/E/W, got {approach!r}"}
    return ctx.forecast(horizon, approach)


def _tool_get_history(args: dict, ctx: LLMContext) -> dict:
    start_iso = args.get("start_iso")
    end_iso = args.get("end_iso")
    if not (start_iso and end_iso):
        return {"error": "start_iso and end_iso are required (ISO 8601 strings)"}
    bucket_minutes = int(args.get("bucket_minutes", 15))
    if bucket_minutes not in (15, 30, 60):
        return {"error": "bucket_minutes must be 15, 30, or 60"}
    approach = args.get("approach")
    where = ["site_id = ?", "ts >= ?", "ts <= ?"]
    params: list[Any] = [ctx.site_id, start_iso, end_iso]
    if approach:
        if approach not in ("S", "N", "E", "W"):
            return {"error": f"approach must be S/N/E/W, got {approach!r}"}
        where.append("approach = ?")
        params.append(approach)
    bucket_seconds = bucket_minutes * 60
    sql = (
        "SELECT approach, "
        "       (CAST(strftime('%s', ts) AS INTEGER) / ?) * ? AS bucket_epoch, "
        "       SUM(count) AS count "
        f"FROM detector_counts WHERE {' AND '.join(where)} "
        "GROUP BY approach, bucket_epoch ORDER BY bucket_epoch ASC, approach ASC LIMIT 1000"
    )
    full_params = (bucket_seconds, bucket_seconds, *params)
    rows = ctx.db.query_all(sql, full_params)
    return {
        "bucket_minutes": bucket_minutes,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "row_count": len(rows),
        "rows": rows,
    }


def _tool_get_recommendation(args: dict, ctx: LLMContext) -> dict:
    scope = args.get("scope", "now")
    if scope not in ("now", "forecast"):
        return {"error": "scope must be 'now' or 'forecast'"}
    return ctx.recommendation(scope)


def _tool_list_incidents(args: dict, ctx: LLMContext) -> dict:
    since_iso = args.get("since_iso")
    types = args.get("types")
    limit = int(args.get("limit", 20))
    limit = max(1, min(limit, 100))
    where = ["site_id = ?"]
    params: list[Any] = [ctx.site_id]
    if since_iso:
        where.append("ts >= ?")
        params.append(since_iso)
    if types:
        if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
            return {"error": "types must be a list of strings"}
        placeholders = ",".join(["?"] * len(types))
        where.append(f"event_type IN ({placeholders})")
        params.extend(types)
    sql = (
        "SELECT ts, event_id, event_type, approach, severity, confidence, status "
        f"FROM incidents WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?"
    )
    rows = ctx.db.query_all(sql, (*params, limit))
    return {"row_count": len(rows), "rows": rows}


def _tool_get_signal_plan(args: dict, ctx: LLMContext) -> dict:
    return ctx.signal_plan()


def _tool_query_sqlite(args: dict, ctx: LLMContext) -> dict:
    sql = args.get("sql", "")
    if not isinstance(sql, str):
        return {"error": "sql must be a string"}
    try:
        return safety.execute_readonly(ctx.db_path, sql)
    except safety.SQLValidationError as e:
        return {"error": f"sql validation failed: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"query failed: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_current_state",
        "description": (
            "Return the current per-approach state of the Wadi Saqra intersection: "
            "live tracker counts, queue, gmaps congestion ratio/label, current signal "
            "phase, and the active plan mode. Call this first when you need to know "
            "what's happening right now."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_forecast",
        "description": (
            "Return the LightGBM forecast at horizon_min (0/15/30/60 minutes ahead). "
            "Optionally filter to one approach. Returns predicted veh/15-min per approach."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon_min": {"type": "integer", "enum": [0, 15, 30, 60]},
                "approach": {"type": "string", "enum": ["S", "N", "E", "W"]},
            },
            "required": ["horizon_min"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_history",
        "description": (
            "Return historical detector counts in 15/30/60-minute buckets between "
            "start_iso and end_iso (ISO 8601). Optionally filter to one approach. "
            "Use for trend questions like 'compare today's PM peak to yesterday'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string", "description": "ISO 8601 start, inclusive"},
                "end_iso": {"type": "string", "description": "ISO 8601 end, inclusive"},
                "bucket_minutes": {"type": "integer", "enum": [15, 30, 60]},
                "approach": {"type": "string", "enum": ["S", "N", "E", "W"]},
            },
            "required": ["start_iso", "end_iso"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recommendation",
        "description": (
            "Return the Webster/HCM 3-phase signal-timing recommendation. "
            "scope='now' uses live demand; scope='forecast' uses +1h predicted demand. "
            "Includes near_saturation flag — if true, the field plan is preserved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["now", "forecast"]}},
            "required": ["scope"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_incidents",
        "description": (
            "List detected incidents (wrong_way, queue_spillback, stalled_vehicle, etc.). "
            "Default limit 20, max 100. since_iso narrows the window; types filters by event_type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "since_iso": {"type": "string"},
                "types": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_signal_plan",
        "description": (
            "Return the current signal plan (NS/E/W green seconds, yellow, all-red, "
            "cycle, mode) and the video anchor when set. This is the field plan, not "
            "the recommendation."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "query_sqlite",
        "description": (
            "Read-only SELECT (or WITH ... SELECT) against the local SQLite database. "
            "Allowlisted tables only: detector_counts, signal_events, incidents, forecasts, "
            "recommendations, system_metrics, sites, ingest_errors. Max 1000 rows, 5s timeout. "
            "Use for novel questions the curated tools can't answer (e.g. 'how often does "
            "wrong_way fire on Fridays after 6pm?'). Always SELECT only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single SELECT or WITH ... SELECT statement. No semicolons.",
                }
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]


_DISPATCH: dict[str, Callable[[dict, LLMContext], dict]] = {
    "get_current_state": _tool_get_current_state,
    "get_forecast": _tool_get_forecast,
    "get_history": _tool_get_history,
    "get_recommendation": _tool_get_recommendation,
    "list_incidents": _tool_list_incidents,
    "get_signal_plan": _tool_get_signal_plan,
    "query_sqlite": _tool_query_sqlite,
}


def dispatch(name: str, args: dict, ctx: LLMContext) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return handler(args or {}, ctx)
    except Exception as e:  # noqa: BLE001
        LOG.exception("tool %s failed", name)
        return {"error": f"{type(e).__name__}: {e}"}
