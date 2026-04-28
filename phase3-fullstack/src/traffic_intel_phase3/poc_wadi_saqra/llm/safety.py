"""SQL guardrails for the ``query_sqlite`` escape-hatch tool.

Defense in depth:
1. Lexical check — reject anything that isn't a single SELECT/WITH-SELECT.
2. Table allowlist — every FROM/JOIN target must be on the allowlist.
3. Read-only connection — opened with ``mode=ro`` so even a parser bypass
   physically cannot mutate the DB.
4. Row cap and timeout — bounded result and bounded compute.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

# Tables the LLM is allowed to read. Excludes anything user-private
# (``users``, ``llm_conversations``, ``llm_messages``) and the audit log.
ALLOWED_TABLES: frozenset[str] = frozenset({
    "detector_counts",
    "signal_events",
    "incidents",
    "forecasts",
    "recommendations",
    "system_metrics",
    "sites",
    "ingest_errors",
})

# Keywords that disqualify a query immediately. The check is lexical —
# we look for these as full-word tokens after stripping comments and
# string literals so a query like ``SELECT 'INSERT INTO foo' AS lit``
# is still allowed.
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "ATTACH", "DETACH", "PRAGMA", "REPLACE", "VACUUM", "REINDEX",
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "ANALYZE",
})

ROW_CAP = 1000
TIMEOUT_SECONDS = 5.0

# A FROM/JOIN clause may quote the table name in `backticks`, "double",
# [brackets], or leave it bare. Captures the bare identifier.
_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:`(\w+)`|\"(\w+)\"|\[(\w+)\]|(\w+))",
    re.IGNORECASE,
)

# WITH cte_name AS (...) — the cte_name is a query-local alias, not a real
# table, so we extract them and union with the allowlist for the current
# query. Comma-separated CTE chains are supported.
_CTE_NAME = re.compile(
    r"(?:^\s*WITH|,)\s+(\w+)\s+AS\s*\(",
    re.IGNORECASE,
)


class SQLValidationError(ValueError):
    """Raised when a candidate query fails the safety checks."""


def _strip_strings_and_comments(sql: str) -> str:
    """Replace string literals and SQL comments with spaces so the keyword
    scan doesn't trip on a query like ``SELECT 'INSERT' AS x``."""
    out = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" or ch == '"':
            quote = ch
            i += 1
            while i < len(sql):
                if sql[i] == quote:
                    if i + 1 < len(sql) and sql[i + 1] == quote:
                        i += 2  # escaped quote
                        continue
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        if ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            while i < len(sql) and sql[i] != "\n":
                i += 1
            out.append(" ")
            continue
        if ch == "/" and i + 1 < len(sql) and sql[i + 1] == "*":
            i += 2
            while i + 1 < len(sql) and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_tables(sanitized_sql: str) -> set[str]:
    found: set[str] = set()
    for match in _TABLE_REF.finditer(sanitized_sql):
        name = next((g for g in match.groups() if g), None)
        if name:
            found.add(name.lower())
    return found


def parse_select_only(sql: str, allowed: Iterable[str] = ALLOWED_TABLES) -> str:
    """Validate that ``sql`` is a single SELECT/WITH-SELECT statement against
    only allowlisted tables. Returns the trimmed query on success.

    Raises SQLValidationError on any violation.
    """
    if not sql or not sql.strip():
        raise SQLValidationError("empty query")
    trimmed = sql.strip().rstrip(";").strip()
    if ";" in trimmed:
        raise SQLValidationError("multiple statements not allowed")

    sanitized = _strip_strings_and_comments(trimmed)
    upper = sanitized.upper().lstrip()

    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise SQLValidationError("only SELECT or WITH ... SELECT statements are allowed")

    tokens = re.findall(r"\b\w+\b", sanitized.upper())
    forbidden = FORBIDDEN_KEYWORDS.intersection(tokens)
    if forbidden:
        raise SQLValidationError(
            f"query contains forbidden keyword(s): {', '.join(sorted(forbidden))}"
        )

    tables = _extract_tables(sanitized)
    allowed_lower = {t.lower() for t in allowed}
    cte_names = {m.group(1).lower() for m in _CTE_NAME.finditer(sanitized)}
    bad = tables - allowed_lower - cte_names
    if bad:
        raise SQLValidationError(
            f"table(s) not on allowlist: {', '.join(sorted(bad))}. "
            f"Allowed: {', '.join(sorted(allowed_lower))}"
        )
    return trimmed


def execute_readonly(
    db_path: Path | str,
    sql: str,
    *,
    row_cap: int = ROW_CAP,
    timeout_seconds: float = TIMEOUT_SECONDS,
) -> dict:
    """Run a validated SELECT against a freshly-opened read-only connection.

    Returns ``{columns, rows, row_count, truncated}``. Raises
    SQLValidationError on bad input or sqlite3.OperationalError on a runtime
    failure (timeout, syntax error caught by the engine, etc.).
    """
    validated = parse_select_only(sql)
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout_seconds, isolation_level=None)
    conn.row_factory = sqlite3.Row

    deadline = threading.Event()
    timer = threading.Timer(timeout_seconds, deadline.set)
    timer.daemon = True
    # ``set_progress_handler`` lets us interrupt a runaway query. The handler
    # fires every N VM ops; returning non-zero raises sqlite3.OperationalError.
    conn.set_progress_handler(lambda: 1 if deadline.is_set() else 0, 1000)
    timer.start()
    try:
        cur = conn.execute(validated)
        rows: list[dict] = []
        truncated = False
        for row in cur:
            if len(rows) >= row_cap:
                truncated = True
                break
            rows.append(dict(row))
        columns = [d[0] for d in (cur.description or [])]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        timer.cancel()
        conn.close()
