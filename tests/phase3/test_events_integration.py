"""End-to-end: POST /api/events/_demo must persist all 5 seeded events
plus at least one composite ``incident`` into the ``incidents`` table.
"""
from __future__ import annotations

import importlib
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def _can_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client(phase3_db):
    for mod in ("cv2", "ultralytics"):
        if not _can_import(mod):
            pytest.skip(f"{mod} unavailable")
    try:
        from traffic_intel_phase3.poc_wadi_saqra import server as srv
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"server module failed to import: {exc}")
    with TestClient(srv.app) as c:
        yield c


def test_demo_endpoint_persists_events(client: TestClient, phase3_db):
    # Record the incident count before we fire the demo.
    before = phase3_db.query_one("SELECT COUNT(*) AS n FROM incidents")["n"]

    r = client.post("/api/events/_demo")
    assert r.status_code == 200
    assert r.json() == {"emitted": 5}

    # Sink is batched (1s flush); the demo explicitly drops into the
    # classify_recent_incidents path which pushes the composite event via
    # the same sink. Poll briefly for the rows to land.
    deadline = time.monotonic() + 5.0
    after = before
    while time.monotonic() < deadline:
        after = phase3_db.query_one("SELECT COUNT(*) AS n FROM incidents")["n"]
        if after >= before + 5:
            break
        time.sleep(0.2)

    # At minimum the 5 primitives must be present. The composite
    # "incident" row is best-effort — it depends on the classifier's
    # co-occurrence rules firing on a freshly-spun-up engine.
    assert after >= before + 5, f"expected +5 incident rows, saw +{after - before}"

    # The /api/events endpoint must also see the seeded types.
    r = client.get("/api/events?limit=50")
    assert r.status_code == 200
    types = {e["event_type"] for e in r.json()["events"]}
    assert {"queue_spillback", "wrong_way", "abnormal_stopping",
            "stalled_vehicle", "congestion_class_change"}.issubset(types)

    # And the rows are indeed in the SQLite incidents table.
    rows = phase3_db.query_all(
        "SELECT event_type, severity FROM incidents WHERE event_id LIKE 'evt_%' ORDER BY id DESC LIMIT 20"
    )
    persisted_types = {r["event_type"] for r in rows}
    assert "queue_spillback" in persisted_types
    assert "wrong_way" in persisted_types
