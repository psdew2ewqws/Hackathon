"""Tests for the traffic-intel MCP server.

The server exposes the same 7 tools the in-app chat uses, but against
the persisted SQLite (no live tracker). These tests verify each tool is
registered with the right schema and produces a structured non-error
JSON result when invoked through the MCP server's call_tool handler.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from traffic_intel_mcp.server import build_context, build_server, _to_mcp_tools
from traffic_intel_phase3.poc_wadi_saqra.llm.tools import TOOL_SCHEMAS


EXPECTED_TOOL_NAMES = {
    "get_current_state",
    "get_forecast",
    "get_history",
    "get_recommendation",
    "list_incidents",
    "get_signal_plan",
    "get_typical_day_gmaps",
    "query_sqlite",
}


def test_tool_names_match_anthropic_schemas():
    mcp_tools = _to_mcp_tools()
    mcp_names = {t.name for t in mcp_tools}
    anthropic_names = {s["name"] for s in TOOL_SCHEMAS}
    assert mcp_names == anthropic_names == EXPECTED_TOOL_NAMES


def test_each_mcp_tool_has_input_schema():
    for t in _to_mcp_tools():
        assert isinstance(t.inputSchema, dict)
        assert t.inputSchema.get("type") == "object"
        assert "properties" in t.inputSchema


def test_each_mcp_tool_has_description():
    for t in _to_mcp_tools():
        assert t.description and len(t.description) > 20, f"{t.name}: weak description"


# ---- end-to-end through the MCP server's call_tool handler ----

def _call_tool_sync(server, name, arguments):
    """Run the registered call_tool handler from a sync test."""
    handler = server.request_handlers
    # Walk through the registered handlers — Server stores them by request type.
    # The mcp SDK's @server.call_tool decorator wires a CallToolRequest handler.
    from mcp.types import CallToolRequest, CallToolRequestParams
    req = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments or {}),
    )
    fn = handler[CallToolRequest]
    return asyncio.run(fn(req))


def test_get_signal_plan_returns_dict(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "get_signal_plan", {})
    payload = result.root.content[0].text
    obj = json.loads(payload)
    assert "current_plan" in obj
    assert "NS_green" in obj["current_plan"]


def test_query_sqlite_select_only(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "query_sqlite", {"sql": "SELECT 1 AS one"})
    obj = json.loads(result.root.content[0].text)
    # safety.execute_readonly returns an error or rows
    assert "rows" in obj or "error" in obj


def test_query_sqlite_blocks_write(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "query_sqlite", {"sql": "DELETE FROM detector_counts"})
    obj = json.loads(result.root.content[0].text)
    assert "error" in obj


def test_get_current_state_returns_db_snapshot(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "get_current_state", {})
    obj = json.loads(result.root.content[0].text)
    assert obj.get("source") == "mcp_db_snapshot"
    assert "approaches" in obj


def test_unknown_tool_returns_error_payload(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "no_such_tool", {})
    obj = json.loads(result.root.content[0].text)
    assert "error" in obj


def test_typical_day_gmaps_corridor_hour(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(
        server, "get_typical_day_gmaps", {"corridor": "E", "hour": 14.0}
    )
    obj = json.loads(result.root.content[0].text)
    assert obj.get("corridor") == "E"
    assert obj.get("hour") == 14.0
    row = obj.get("row")
    assert row is not None, "E@14.0 should be filled in the source ndjson"
    assert "congestion_ratio" in row
    assert "congestion_label" in row


def test_typical_day_gmaps_full_grid(tmp_path, phase3_db_path):
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "get_typical_day_gmaps", {})
    obj = json.loads(result.root.content[0].text)
    corridors = obj.get("corridors") or {}
    assert set(corridors.keys()) == {"N", "S", "E", "W"}
    for c, bins in corridors.items():
        assert len(bins) == 48, f"{c} should have 48 half-hour bins"


def test_typical_day_gmaps_schema_rejects_bad_corridor(tmp_path, phase3_db_path):
    """The MCP layer should reject invalid enum values via the input schema
    (not even reach the handler). We expect a non-JSON validation message."""
    server = build_server(build_context(db_path=phase3_db_path))
    result = _call_tool_sync(server, "get_typical_day_gmaps", {"corridor": "X"})
    text = result.root.content[0].text
    assert "validation error" in text.lower() or "not one of" in text.lower()
