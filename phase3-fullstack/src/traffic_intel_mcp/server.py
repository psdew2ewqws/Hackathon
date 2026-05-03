"""Stdio MCP server exposing the Wadi Saqra intersection tools.

The server constructs a DB-backed `LLMContext` (no live tracker process
needed — the standalone MCP server reads everything from the persisted
SQLite). Tools that normally read live state (e.g. `get_current_state`)
return the most recent persisted snapshot. Tools that already operate
against the DB (`get_history`, `list_incidents`, `query_sqlite`) work
unchanged.

External clients (Claude Desktop, Cursor, etc.) connect via stdio.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Tool surface is the single source of truth — both the in-app chat and
# this MCP server consume the same TOOL_SCHEMAS + dispatch.
from traffic_intel_phase3.poc_wadi_saqra.llm.tools import (
    LLMContext,
    TOOL_SCHEMAS,
    dispatch,
)
from traffic_intel_phase3.storage.db import Db, get_db

LOG = logging.getLogger("traffic_intel_mcp")


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "phase3-fullstack" / "data" / "traffic_intel.db"


# ---------------------------------------------------------------------------
# DB-backed context providers (stand-in for the in-process live-tracker ones)
# ---------------------------------------------------------------------------


def _db_live_state(db: Db, site_id: str) -> dict[str, Any]:
    """Return the most recent per-approach snapshot from `detector_counts`.

    The live tracker provides this in-process; from outside the FastAPI
    process we approximate by aggregating the latest 15-second bin per
    approach.
    """
    rows = db.query_all(
        """
        SELECT approach, ts, count
        FROM detector_counts
        WHERE site_id = ?
          AND ts >= datetime('now', '-2 minutes')
        ORDER BY ts DESC
        """,
        (site_id,),
    )
    by_approach: dict[str, dict[str, Any]] = {}
    for r in rows:
        ap = r["approach"]
        if ap in by_approach:
            continue
        by_approach[ap] = {
            "approach": ap,
            "latest_ts": r["ts"],
            "count_in_bin": r["count"],
        }
    return {
        "source": "mcp_db_snapshot",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "approaches": by_approach,
        "note": "MCP server runs against persisted SQLite, not the live tracker. "
                "For real-time queue state, use the dashboard chat instead.",
    }


def _db_forecast(_horizon_min: int, _approach: str | None) -> dict[str, Any]:
    """Forecasts from the persisted `forecasts` table.

    Returns the most recent prediction (per approach × horizon) instead
    of running the LightGBM model — avoids loading 100s of MB of model
    state into a stdio MCP process that may be invoked many times.
    """
    return {
        "available": False,
        "message": "Standalone MCP server doesn't run the LightGBM model. "
                   "Use query_sqlite('SELECT * FROM forecasts ORDER BY made_at DESC LIMIT 20') "
                   "to inspect persisted forecasts, or use the dashboard chat for live ML inference.",
    }


def _db_recommendation(_scope: str) -> dict[str, Any]:
    """Latest recommendation row from the persisted `recommendations` table."""
    return {
        "available": False,
        "message": "Standalone MCP server doesn't compute Webster on the fly. "
                   "Use query_sqlite('SELECT * FROM recommendations ORDER BY ts DESC LIMIT 1') "
                   "to fetch the most recent persisted recommendation.",
    }


def _db_signal_plan() -> dict[str, Any]:
    return {
        "mode": "static_three_phase",
        "note": "Standalone MCP server returns the static field plan; "
                "for the live-current phase use the dashboard /api/signal/current.",
        "current_plan": {
            "NS_green": 35,
            "E_green": 35,
            "W_green": 35,
            "yellow": 3,
            "all_red": 2,
            "cycle_seconds": 120,
        },
    }


# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------


def build_context(db_path: Path | None = None, site_id: str = "wadi_saqra") -> LLMContext:
    """Build a DB-backed LLMContext for use by an out-of-process MCP server."""
    db_path = Path(db_path or DEFAULT_DB_PATH)
    db = get_db(db_path)
    return LLMContext(
        db=db,
        db_path=db_path,
        site_id=site_id,
        live_state=lambda: _db_live_state(db, site_id),
        forecast=_db_forecast,
        recommendation=_db_recommendation,
        signal_plan=_db_signal_plan,
    )


def _to_mcp_tools() -> list[Tool]:
    """Convert each Anthropic-style schema into an MCP `Tool` definition."""
    out: list[Tool] = []
    for s in TOOL_SCHEMAS:
        out.append(Tool(
            name=s["name"],
            description=s.get("description", ""),
            inputSchema=s.get("input_schema") or {"type": "object", "properties": {}},
        ))
    return out


def build_server(ctx: LLMContext | None = None) -> Server:
    """Build the MCP `Server` with all 7 tools registered.

    Exposed for tests so they can drive the server's handlers directly
    without spinning up stdio transport.
    """
    server: Server = Server("traffic-intel")
    context = ctx if ctx is not None else build_context()

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return _to_mcp_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        result = dispatch(name, arguments or {}, context)
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def serve_stdio() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    logging.basicConfig(level=os.environ.get("MCP_LOG_LEVEL", "INFO"))
    import asyncio
    asyncio.run(serve_stdio())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
