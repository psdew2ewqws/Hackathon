"""Shared fixtures for the phase3 test suite.

Every test in this package gets:
- an isolated SQLite file under tmp_path (shared across tests in a session
  via ``tmp_path_factory``) wired through ``storage.db.get_db``.
- JWT + user env vars pinned so tokens survive across the fixture's lifetime.

Skips gracefully if a heavy optional dep (e.g. ultralytics via ``server``)
isn't importable at collection time.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


def _reset_auth_singleton() -> None:
    """The ``auth.deps._service`` singleton caches a JwtService between
    requests. When tests rebind env vars we must discard it so the next
    call to ``_svc()`` picks the new secret up."""
    try:
        from traffic_intel_phase3.auth import deps as _deps
    except Exception:
        return
    _deps._service = None  # noqa: SLF001


@pytest.fixture(scope="session")
def phase3_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped tmp DB file used by every phase3 test."""
    return tmp_path_factory.mktemp("phase3_db") / "traffic_intel.db"


@pytest.fixture(scope="session", autouse=True)
def phase3_env(phase3_db_path: Path) -> None:
    """Pin JWT + role-password env vars for the session."""
    os.environ.setdefault("TRAFFIC_INTEL_JWT_SECRET", "test-secret-phase3")
    os.environ.setdefault("TRAFFIC_INTEL_JWT_TTL_MIN", "30")
    os.environ.setdefault("TRAFFIC_INTEL_VIEWER_PW",   "viewer123")
    os.environ.setdefault("TRAFFIC_INTEL_OPERATOR_PW", "operator123")
    os.environ.setdefault("TRAFFIC_INTEL_ADMIN_PW",    "admin123")
    _reset_auth_singleton()


@pytest.fixture(scope="session")
def phase3_db(phase3_db_path: Path):
    """Reset the storage singleton so tests use the temp DB, then
    materialise it via ``get_db``."""
    try:
        from traffic_intel_phase3.storage import db as _db_mod
    except Exception as exc:  # pragma: no cover - dependency missing
        pytest.skip(f"storage module unavailable: {exc}")
    _db_mod._shared = None  # noqa: SLF001 - swap singleton
    db = _db_mod.get_db(phase3_db_path)
    yield db
    _db_mod.close_shared()
