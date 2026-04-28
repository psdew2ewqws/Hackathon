"""Tests for individual LLM tool handlers, with a mocked context.

We don't boot the full FastAPI server here — we synthesise an LLMContext
with stub providers so the tool dispatch logic and SQL handlers can be
exercised in isolation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from traffic_intel_phase3.poc_wadi_saqra.llm import tools as llm_tools
from traffic_intel_phase3.poc_wadi_saqra.llm.tools import LLMContext
from traffic_intel_phase3.storage import db as _db_mod


@pytest.fixture
def ctx(tmp_path):
    db_path = tmp_path / "tools.db"
    db = _db_mod.Db(db_path)
    _db_mod.init_schema(db)
    # Seed minimal data.
    db.execute(
        "INSERT INTO detector_counts (site_id, ts, approach, count) VALUES "
        "('wadi_saqra', '2026-04-28T08:00:00+03:00', 'S', 5), "
        "('wadi_saqra', '2026-04-28T08:15:00+03:00', 'S', 7), "
        "('wadi_saqra', '2026-04-28T08:30:00+03:00', 'E', 9)"
    )
    db.execute(
        "INSERT INTO incidents (site_id, ts, event_id, event_type, approach, severity) "
        "VALUES ('wadi_saqra', '2026-04-28T08:00:00+03:00', 'evt_1', 'wrong_way', 'E', 'warning'), "
        "       ('wadi_saqra', '2026-04-28T07:30:00+03:00', 'evt_2', 'queue_spillback', 'N', 'critical')"
    )
    return LLMContext(
        db=db,
        db_path=db_path,
        site_id="wadi_saqra",
        live_state=lambda: {"local_hour": 8.0, "fused": {"S": {"in_zone": 1}}},
        forecast=lambda h, a: {"available": True, "horizon_min": h, "approach": a,
                               "predicted_veh_per_15min": {"S": 5.0, "N": 7.0, "E": 9.0, "W": 3.0}},
        recommendation=lambda scope: {"scope": scope, "recommendation": {"mode": "three_phase"}},
        signal_plan=lambda: {"mode": "three_phase", "current_plan": {"NS_green": 35}},
    )


class TestDispatch:
    def test_unknown_tool_returns_error(self, ctx):
        out = llm_tools.dispatch("nonexistent", {}, ctx)
        assert "error" in out

    def test_get_current_state(self, ctx):
        out = llm_tools.dispatch("get_current_state", {}, ctx)
        assert out["local_hour"] == 8.0

    def test_get_forecast_validates_horizon(self, ctx):
        bad = llm_tools.dispatch("get_forecast", {"horizon_min": 5}, ctx)
        assert "error" in bad
        good = llm_tools.dispatch("get_forecast", {"horizon_min": 15}, ctx)
        assert good["available"] is True

    def test_get_forecast_validates_approach(self, ctx):
        bad = llm_tools.dispatch(
            "get_forecast", {"horizon_min": 15, "approach": "X"}, ctx,
        )
        assert "error" in bad

    def test_get_history_requires_window(self, ctx):
        bad = llm_tools.dispatch("get_history", {}, ctx)
        assert "error" in bad
        good = llm_tools.dispatch(
            "get_history",
            {
                "start_iso": "2026-04-28T07:00:00+03:00",
                "end_iso": "2026-04-28T09:00:00+03:00",
                "bucket_minutes": 15,
            },
            ctx,
        )
        assert good["row_count"] >= 1
        assert "rows" in good

    def test_get_history_filters_approach(self, ctx):
        out = llm_tools.dispatch(
            "get_history",
            {
                "start_iso": "2026-04-28T00:00:00+03:00",
                "end_iso": "2026-04-28T23:59:59+03:00",
                "bucket_minutes": 60,
                "approach": "S",
            },
            ctx,
        )
        for row in out["rows"]:
            assert row["approach"] == "S"

    def test_get_recommendation_validates_scope(self, ctx):
        bad = llm_tools.dispatch("get_recommendation", {"scope": "weird"}, ctx)
        assert "error" in bad
        good = llm_tools.dispatch("get_recommendation", {"scope": "now"}, ctx)
        assert good["scope"] == "now"

    def test_list_incidents_default(self, ctx):
        out = llm_tools.dispatch("list_incidents", {}, ctx)
        assert out["row_count"] == 2
        # Newest first.
        assert out["rows"][0]["event_type"] == "wrong_way"

    def test_list_incidents_filtered_by_type(self, ctx):
        out = llm_tools.dispatch(
            "list_incidents", {"types": ["wrong_way"]}, ctx,
        )
        assert out["row_count"] == 1
        assert out["rows"][0]["event_type"] == "wrong_way"

    def test_list_incidents_caps_limit(self, ctx):
        out = llm_tools.dispatch("list_incidents", {"limit": 9999}, ctx)
        assert out["row_count"] <= 100

    def test_get_signal_plan(self, ctx):
        out = llm_tools.dispatch("get_signal_plan", {}, ctx)
        assert out["mode"] == "three_phase"

    def test_query_sqlite_select(self, ctx):
        out = llm_tools.dispatch(
            "query_sqlite",
            {"sql": "SELECT approach, count FROM detector_counts ORDER BY approach LIMIT 10"},
            ctx,
        )
        assert "error" not in out
        assert "rows" in out
        assert out["row_count"] >= 1

    def test_query_sqlite_blocks_write(self, ctx):
        out = llm_tools.dispatch(
            "query_sqlite",
            {"sql": "INSERT INTO detector_counts VALUES (1,2,3,4)"},
            ctx,
        )
        assert "error" in out
        assert "validation" in out["error"].lower() or "select" in out["error"].lower()

    def test_query_sqlite_blocks_blocklisted_table(self, ctx):
        out = llm_tools.dispatch(
            "query_sqlite",
            {"sql": "SELECT * FROM users"},
            ctx,
        )
        assert "error" in out
        assert "allowlist" in out["error"]

    def test_tool_schemas_count(self):
        names = {t["name"] for t in llm_tools.TOOL_SCHEMAS}
        assert names == {
            "get_current_state",
            "get_forecast",
            "get_history",
            "get_recommendation",
            "list_incidents",
            "get_signal_plan",
            "query_sqlite",
        }

    def test_tool_schemas_have_required_fields(self):
        for schema in llm_tools.TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema
            assert schema["input_schema"]["type"] == "object"
