"""SQLite wrapper for Phase 3 §8.5. Thread-safe via threading.local connections.

Portable SQL dialect (works on Postgres with minor DDL tweaks). WAL mode
enabled on every open for concurrent read + single-writer performance.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_DB = Path(__file__).resolve().parents[4] / "phase3-fullstack" / "data" / "traffic_intel.db"
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


class Db:
    """Thread-safe sqlite3 wrapper with a single connection per thread."""

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(str(self.path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        self._local.conn = conn
        return conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn().execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        return self._conn().executemany(sql, rows)

    def executescript(self, script: str) -> None:
        self._conn().executescript(script)

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        rows = self._conn().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self._conn().execute(sql, params).fetchone()
        return dict(row) if row else None

    def transaction(self) -> _Txn:
        return _Txn(self._conn())

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


class _Txn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.execute("BEGIN")
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self._conn.execute("ROLLBACK")
        else:
            self._conn.execute("COMMIT")


_shared: Db | None = None
_shared_lock = threading.Lock()


def get_db(path: Path | str | None = None) -> Db:
    """Return a process-wide shared Db handle (init once, reuse)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Db(path or DEFAULT_DB)
            init_schema(_shared)
        return _shared


def init_schema(db: Db) -> None:
    """Apply schema.sql. Idempotent."""
    sql = SCHEMA_SQL.read_text()
    db.executescript(sql)


def close_shared() -> None:
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
            _shared = None


def iter_rows(cursor: sqlite3.Cursor, batch: int = 500) -> Iterator[list[dict]]:
    """Stream results in batches of dicts."""
    while True:
        rows = cursor.fetchmany(batch)
        if not rows:
            return
        yield [dict(r) for r in rows]
