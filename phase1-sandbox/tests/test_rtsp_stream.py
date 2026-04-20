"""End-to-end RTSP healthcheck.

Only runs when an RTSP stream is actually up. Skip-by-default so
``make sandbox-verify`` still passes on a dev machine that hasn't started
the sim yet.

To run:  make stream-up && pytest -m requires_stream
"""

from __future__ import annotations

import os

import pytest

from traffic_intel_sandbox.rtsp_sim.healthcheck import evaluate, _probe


RTSP_URL = os.environ.get("RTSP_URL", "rtsp://localhost:8554/site1")


@pytest.mark.requires_stream
def test_stream_is_healthy():
    try:
        info = _probe(RTSP_URL)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RTSP stream not reachable at {RTSP_URL}: {exc}")
    report, failures = evaluate(info)
    assert not failures, f"stream unhealthy: {failures} (report={report})"
