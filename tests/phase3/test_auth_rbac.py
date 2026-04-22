"""FastAPI-level auth + RBAC checks against the real server app.

Uses the full ``server`` module so we also exercise the singleton wiring
between ``_users``, ``_jwt`` and the ``get_auth_context`` dependency.
"""
from __future__ import annotations

import os

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # TestClient transport

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(phase3_db):
    """Boot the Phase 3 FastAPI app against the session DB."""
    # Heavy optional deps — skip cleanly if missing.
    for mod in ("cv2", "ultralytics"):
        if not _can_import(mod):
            pytest.skip(f"{mod} unavailable")
    try:
        from traffic_intel_phase3.poc_wadi_saqra import server as srv
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"server module failed to import: {exc}")
    # TestClient context manager fires startup/shutdown events.
    with TestClient(srv.app) as c:
        yield c


def _can_import(name: str) -> bool:
    import importlib
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_login_viewer_issues_token(client: TestClient):
    data = _login(client, "viewer", "viewer123")
    assert data["username"] == "viewer"
    assert data["role"] == "viewer"
    assert isinstance(data["token"], str) and len(data["token"]) > 20
    assert data["expires_at"] > 0


def test_login_bad_password_rejected(client: TestClient):
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_me_returns_context(client: TestClient):
    tok = _login(client, "operator", "operator123")["token"]
    r = client.get("/api/auth/me",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"username": "operator", "role": "operator"}


def test_me_without_token_is_401(client: TestClient):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_garbage_token_is_401(client: TestClient):
    r = client.get("/api/auth/me",
                   headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_audit_log_requires_admin(client: TestClient):
    # viewer - 403
    viewer_tok = _login(client, "viewer", "viewer123")["token"]
    r = client.get("/api/audit/log",
                   headers={"Authorization": f"Bearer {viewer_tok}"})
    assert r.status_code == 403

    # operator - 403
    op_tok = _login(client, "operator", "operator123")["token"]
    r = client.get("/api/audit/log",
                   headers={"Authorization": f"Bearer {op_tok}"})
    assert r.status_code == 403

    # admin - 200
    admin_tok = _login(client, "admin", "admin123")["token"]
    r = client.get("/api/audit/log",
                   headers={"Authorization": f"Bearer {admin_tok}"})
    assert r.status_code == 200
    assert "events" in r.json()


def test_audit_log_rejects_no_token(client: TestClient):
    r = client.get("/api/audit/log")
    assert r.status_code == 401


def test_default_users_seeded(phase3_db):
    rows = phase3_db.query_all("SELECT username, role FROM users ORDER BY username")
    names = {r["username"]: r["role"] for r in rows}
    assert names.get("viewer")   == "viewer"
    assert names.get("operator") == "operator"
    assert names.get("admin")    == "admin"


def test_jwt_ttl_env_respected(monkeypatch):
    """Direct unit check that TRAFFIC_INTEL_JWT_TTL_MIN feeds make_service()."""
    from traffic_intel_phase3.auth.jwt_service import make_service
    monkeypatch.setenv("TRAFFIC_INTEL_JWT_TTL_MIN", "7")
    svc = make_service()
    token, payload = svc.issue("tmp", "viewer")
    # exp - iat == 7 min
    import jwt as _jwt
    decoded = _jwt.decode(token, options={"verify_signature": False})
    assert decoded["exp"] - decoded["iat"] == 7 * 60
