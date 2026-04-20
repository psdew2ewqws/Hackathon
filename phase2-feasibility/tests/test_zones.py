"""Zones + lines correctly load from the Phase 1 metadata stub."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("supervision", reason="supervision not installed yet")

from traffic_intel_phase2.zones import load_stop_lines, load_zones  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "phase1-sandbox/src/traffic_intel_sandbox/metadata/site1.example.json"


def test_zones_nonempty():
    zones = load_zones(SITE)
    assert zones, "site1.example.json should define monitoring zones"
    kinds = {z.kind for z in zones}
    assert "queue_spillback" in kinds


def test_stop_lines_per_approach():
    lines = load_stop_lines(SITE)
    assert lines, "site1.example.json should define stop lines"
    approaches = {line.approach for line in lines}
    assert approaches == {"N", "S", "E", "W"}


def test_zone_has_polygon_area():
    zones = load_zones(SITE)
    for z in zones:
        # sv.PolygonZone stores the polygon internally; verify it accepted >=3 points.
        assert z.zone.polygon.shape[0] >= 3, f"zone {z.name} has fewer than 3 points"
