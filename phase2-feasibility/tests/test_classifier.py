"""Unit + regression tests for the rule-based event classifier.

Two layers of tests:
  - Pass A unit tests build synthetic ndjson fixtures that trigger each rule
    in isolation.
  - End-to-end regression tests run against the four Veo-3 clip ndjson files
    we have under data/events/per-clip/ (skipped if those files are absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from traffic_intel_phase2.classifier import (
    DEFAULT_THRESHOLDS,
    classify_clip,
    extract_features,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PER_CLIP_DIR = REPO_ROOT / "data/events/per-clip"


# ── helpers ────────────────────────────────────────────────────────────────

def _write_ndjson(tmp_path: Path, name: str, events: list[dict]) -> Path:
    p = tmp_path / f"{name}.ndjson"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def _run_end(**overrides) -> dict:
    base = {
        "timestamp": "2026-04-20T00:00:00.000Z",
        "intersection_id": "SITE1",
        "event_type": "run_end",
        "frames": 80,
        "detections_total": 500,
        "unique_tracks": 20,
        "latency_ms": {"mean": 30, "p50": 28, "p95": 40},
        "line_crossings": {"N": 0, "S": 0, "E": 0, "W": 0},
        "video_out": None,
        "events_out": None,
        "source": "fixture",
        "model": "models/yolo26n.pt",
        "tracker": "botsort.yaml",
        "device": "cpu",
        "conf": 0.3, "iou": 0.5,
    }
    # Nested overrides for line_crossings
    lc = overrides.pop("line_crossings", None)
    if lc is not None:
        base["line_crossings"] = {**base["line_crossings"], **lc}
    base.update(overrides)
    return base


def _zone_occ(frame: int, name: str, kind: str, count: int, prev: int = 0) -> dict:
    return {
        "timestamp": "2026-04-20T00:00:00.000Z",
        "intersection_id": "SITE1",
        "event_type": "zone_occupancy",
        "name": name, "kind": kind, "count": count, "prev": prev, "frame": frame,
    }


def _line_xing(frame: int, approach: str, delta: int = 1) -> dict:
    return {
        "timestamp": "2026-04-20T00:00:00.000Z",
        "intersection_id": "SITE1",
        "event_type": "stop_line_crossing",
        "approach": approach, "delta": delta,
        "in_count": delta, "out_count": 0, "frame": frame,
    }


# ── Pass A rule tests ──────────────────────────────────────────────────────

def test_gridlock_rule_fires(tmp_path: Path) -> None:
    # Dense scene (unique_tracks >= 35), max zone occupancy >= 5, zero crossings.
    events = [
        *[_zone_occ(i, "queue_spillback_N", "queue_spillback", count=10) for i in range(0, 80, 2)],
        _run_end(unique_tracks=42, line_crossings={"N": 0, "S": 0, "E": 0, "W": 0}),
    ]
    p = _write_ndjson(tmp_path, "grid", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "gridlock", v
    assert v.pass_used == "A"
    assert any("max_zone_occupancy" in r for r in v.reasons)
    assert any("unique_tracks" in r for r in v.reasons)


def test_queue_spillback_rule_fires(tmp_path: Path) -> None:
    # 50 consecutive zone_occupancy events with count >= 5, and ≤1 line crossing
    # (queue stays populated without draining).
    events = [_zone_occ(i, "queue_spillback_E", "queue_spillback", count=6)
              for i in range(50)]
    # Exactly one crossing (still ≤ max_line_crossings_total=1).
    events.append(_line_xing(frame=20, approach="E", delta=1))
    events.append(_run_end(line_crossings={"N": 0, "S": 0, "E": 1, "W": 0},
                           unique_tracks=20))
    p = _write_ndjson(tmp_path, "spill", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "queue_spillback", v


def test_unexpected_trajectory_by_track_churn(tmp_path: Path) -> None:
    # Track churn ratio: unique_tracks=60 / baseline 32 = 1.87
    events = [
        _zone_occ(10, "queue_spillback_N", "queue_spillback", count=2),
        _line_xing(20, "N"), _line_xing(25, "N"),
        _run_end(unique_tracks=60, line_crossings={"N": 2, "S": 0, "E": 0, "W": 0}),
    ]
    p = _write_ndjson(tmp_path, "churn", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "unexpected_trajectory", v
    assert any("churn" in r.lower() for r in v.reasons)


def test_unexpected_trajectory_by_approach_concentration(tmp_path: Path) -> None:
    # 8 crossings on N, 1 on E → 88% concentration > 70% threshold.
    events = [
        _zone_occ(10, "queue_spillback_N", "queue_spillback", count=2),
        _run_end(unique_tracks=30, line_crossings={"N": 8, "S": 0, "E": 1, "W": 0}),
    ]
    p = _write_ndjson(tmp_path, "single", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "unexpected_trajectory", v
    assert any("single-approach" in r for r in v.reasons)


def test_normal_rule_fires(tmp_path: Path) -> None:
    events = [
        _zone_occ(5, "queue_spillback_N", "queue_spillback", count=1),
        _run_end(unique_tracks=30, line_crossings={"N": 1, "S": 1, "E": 2, "W": 1}),
    ]
    p = _write_ndjson(tmp_path, "normal", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "normal", v


def test_insufficient_evidence_fallback(tmp_path: Path) -> None:
    # Zero activity: not gridlock (no occupancy), not normal (too few crossings).
    events = [_run_end(unique_tracks=5, line_crossings={"N": 0, "S": 0, "E": 0, "W": 0})]
    p = _write_ndjson(tmp_path, "empty", events)
    v = classify_clip(p, DEFAULT_THRESHOLDS)
    assert v.predicted_tag == "insufficient_evidence", v


# ── Regression tests on the four real clips ───────────────────────────────

REAL_CLIPS_EXPECTED = {
    "site1_normal_midday_01":  {"normal"},
    "site1_gridlock_01":       {"gridlock", "sudden_congestion"},
    "site1_red-runner_01":     {"unexpected_trajectory", "insufficient_evidence"},
    "site1_wrongway_01":       {"unexpected_trajectory"},
}


@pytest.mark.parametrize("stem,allowed", list(REAL_CLIPS_EXPECTED.items()))
def test_real_clip_predictions(stem: str, allowed: set[str]) -> None:
    path = PER_CLIP_DIR / f"{stem}.ndjson"
    if not path.exists():
        pytest.skip(f"{path} not present (run phase2-detect first)")
    v = classify_clip(path, DEFAULT_THRESHOLDS)
    assert v.predicted_tag in allowed, (
        f"{stem}: predicted={v.predicted_tag} (reasons={v.reasons})"
    )


def test_features_extractor_parses_all_fields(tmp_path: Path) -> None:
    events = [
        _zone_occ(0, "queue_spillback_N", "queue_spillback", count=2),
        _zone_occ(20, "queue_spillback_N", "queue_spillback", count=5),
        _line_xing(10, "E", 1),
        _run_end(unique_tracks=40, line_crossings={"N": 0, "S": 0, "E": 1, "W": 0}),
    ]
    p = _write_ndjson(tmp_path, "extract", events)
    feats = extract_features(p)
    assert feats.frames == 80
    assert feats.unique_tracks == 40
    assert feats.line_crossings_total == 1
    assert feats.line_crossings_by_approach == {"N": 0, "S": 0, "E": 1, "W": 0}
    assert feats.max_zone_occupancy == 5


def test_thresholds_file_is_valid_yaml() -> None:
    th = yaml.safe_load(Path(DEFAULT_THRESHOLDS).read_text())
    assert th["version"].startswith("v")
    assert "pass_a" in th and "pass_b" in th and "confidence" in th
    for key in ("gridlock", "queue_spillback", "sudden_congestion",
                "unexpected_trajectory", "normal"):
        assert key in th["pass_a"], f"missing Pass A rule: {key}"
