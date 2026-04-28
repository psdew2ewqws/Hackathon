"""SQL guardrail tests for the ``query_sqlite`` LLM tool."""
from __future__ import annotations

import sqlite3

import pytest

from traffic_intel_phase3.poc_wadi_saqra.llm import safety


class TestParseSelectOnly:
    def test_accepts_simple_select(self):
        out = safety.parse_select_only("SELECT * FROM detector_counts")
        assert out == "SELECT * FROM detector_counts"

    def test_accepts_with_select(self):
        sql = (
            "WITH recent AS (SELECT * FROM detector_counts WHERE ts > '2026-01-01') "
            "SELECT approach, SUM(count) FROM recent GROUP BY approach"
        )
        assert safety.parse_select_only(sql).startswith("WITH recent")

    def test_accepts_join_on_allowlisted_tables(self):
        sql = (
            "SELECT i.event_type, COUNT(*) FROM incidents i "
            "JOIN detector_counts d ON d.ts = i.ts GROUP BY i.event_type"
        )
        assert safety.parse_select_only(sql)

    def test_rejects_empty_query(self):
        with pytest.raises(safety.SQLValidationError, match="empty"):
            safety.parse_select_only("")

    def test_rejects_multiple_statements(self):
        with pytest.raises(safety.SQLValidationError, match="multiple"):
            safety.parse_select_only(
                "SELECT 1; SELECT 2"
            )

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO detector_counts VALUES (1)",
            "UPDATE detector_counts SET count = 0",
            "DELETE FROM detector_counts",
            "DROP TABLE detector_counts",
            "ALTER TABLE detector_counts ADD COLUMN x INT",
            "PRAGMA writable_schema=1",
            "ATTACH DATABASE 'foo.db' AS foo",
            "VACUUM",
        ],
    )
    def test_rejects_non_select(self, sql: str):
        with pytest.raises(safety.SQLValidationError):
            safety.parse_select_only(sql)

    def test_rejects_blocklisted_table(self):
        with pytest.raises(safety.SQLValidationError, match="not on allowlist"):
            safety.parse_select_only("SELECT * FROM users")
        with pytest.raises(safety.SQLValidationError, match="not on allowlist"):
            safety.parse_select_only("SELECT * FROM audit_log")
        with pytest.raises(safety.SQLValidationError, match="not on allowlist"):
            safety.parse_select_only(
                "SELECT * FROM llm_conversations JOIN llm_messages ON 1=1"
            )

    def test_keyword_in_string_literal_is_ok(self):
        # ``INSERT`` appears only inside a string literal — should be allowed.
        sql = "SELECT 'INSERT INTO x' AS lit FROM detector_counts LIMIT 1"
        assert safety.parse_select_only(sql)

    def test_strips_trailing_semicolon(self):
        out = safety.parse_select_only("SELECT 1 FROM detector_counts;")
        assert ";" not in out

    def test_keyword_in_comment_is_ok(self):
        sql = (
            "SELECT 1 FROM detector_counts -- DROP TABLE users\n"
            "WHERE 1 = 1"
        )
        assert safety.parse_select_only(sql)


class TestExecuteReadonly:
    @pytest.fixture
    def seeded_db(self, tmp_path):
        path = tmp_path / "ro.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            """
            CREATE TABLE detector_counts (
                site_id TEXT, ts TEXT, approach TEXT, count INTEGER
            );
            INSERT INTO detector_counts VALUES
                ('wadi_saqra', '2026-04-28T08:00:00+03:00', 'S', 5),
                ('wadi_saqra', '2026-04-28T08:00:00+03:00', 'N', 7),
                ('wadi_saqra', '2026-04-28T08:00:00+03:00', 'E', 9),
                ('wadi_saqra', '2026-04-28T08:00:00+03:00', 'W', 4);
            """
        )
        conn.commit()
        conn.close()
        return path

    def test_returns_columns_and_rows(self, seeded_db):
        out = safety.execute_readonly(
            seeded_db,
            "SELECT approach, count FROM detector_counts ORDER BY approach",
        )
        assert out["columns"] == ["approach", "count"]
        assert out["row_count"] == 4
        assert out["truncated"] is False
        assert {r["approach"] for r in out["rows"]} == {"S", "N", "E", "W"}

    def test_caps_at_row_limit(self, seeded_db):
        out = safety.execute_readonly(
            seeded_db,
            "SELECT * FROM detector_counts",
            row_cap=2,
        )
        assert out["row_count"] == 2
        assert out["truncated"] is True

    def test_blocks_validation_failure_before_open(self, seeded_db):
        with pytest.raises(safety.SQLValidationError):
            safety.execute_readonly(seeded_db, "DROP TABLE detector_counts")

    def test_readonly_connection_blocks_writes(self, seeded_db):
        # Even if validation were bypassed, the ``mode=ro`` URI prevents
        # mutation. Verify by opening with the same shape and trying a write.
        uri = f"file:{seeded_db}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO detector_counts VALUES ('x','y','S',1)")
        finally:
            conn.close()
