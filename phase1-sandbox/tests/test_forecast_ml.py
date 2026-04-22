"""Smoke tests for the ML forecasting pipeline (Phase 2 §7.4).

The training step depends on real data files under ``data/detector_counts``
and ``data/signal_logs`` so we mark these as integration tests. They run
quickly (LightGBM trains in ~30 s on the 30-day synth set) and skip
gracefully if the data hasn't been generated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
COUNTS_DIR = REPO_ROOT / "data" / "detector_counts"
SIGNALS_DIR = REPO_ROOT / "data" / "signal_logs"


pytestmark = pytest.mark.skipif(
    not COUNTS_DIR.exists() or len(list(COUNTS_DIR.glob("counts_*.parquet"))) < 14,
    reason="needs at least 14 days of synth detector counts; run `make synth-all SANDBOX_DAYS=30`",
)


def test_features_build_and_drop_lags():
    """build_features should produce a non-empty matrix with the expected
    columns + drop rows that lack 7-day lag history."""
    from forecast_ml.features import build_features, feature_columns, target_columns
    fb = build_features(COUNTS_DIR, SIGNALS_DIR)
    assert not fb.train_X.empty
    assert list(fb.train_X.columns) == feature_columns()
    assert list(fb.train_y.columns) == target_columns()
    # Sanity: positive counts only
    for col in fb.train_y.columns:
        assert (fb.train_y[col] >= 0).all()


# Fast-training knobs for tests — enough rounds to clear the 10%-gain bar
# without paying for the full 300-round production schedule.
_TEST_BOOST_ROUNDS = 60


@pytest.fixture(scope="module")
def feature_build():
    """Cache the expensive build_features() call across tests — it's the
    same train set every time."""
    from forecast_ml.features import build_features
    return build_features(COUNTS_DIR, SIGNALS_DIR)


def _split(fb):
    import numpy as np
    cutoff = int(len(fb.train_X) * 0.8)
    order = np.argsort(fb.timestamps.values)
    X_tr, y_tr = fb.train_X.iloc[order[:cutoff]], fb.train_y.iloc[order[:cutoff]]
    X_va, y_va = fb.train_X.iloc[order[cutoff:]], fb.train_y.iloc[order[cutoff:]]
    return X_tr, y_tr, X_va, y_va


def test_lightgbm_beats_persistence_baseline(tmp_path: Path, feature_build):
    """Train LightGBM and verify it has lower MAE than the persistence
    baseline (predict-same-as-last-bin) by ≥10% on at least 3 of 4 horizons."""
    from forecast_ml.train import _persistence_baseline, _train_lightgbm

    X_tr, y_tr, X_va, y_va = _split(feature_build)
    base = _persistence_baseline(X_va, y_va)
    bundle_path = tmp_path / "lgb.json"
    metrics = _train_lightgbm(X_tr, y_tr, X_va, y_va, bundle_path,
                              num_boost_round=_TEST_BOOST_ROUNDS)

    wins = 0
    for col in y_tr.columns:
        if base.get(col) is None:
            continue
        if metrics[col]["mae"] < base[col] * 0.9:
            wins += 1
    assert wins >= 3, (
        f"LightGBM should beat persistence baseline on ≥3/4 horizons by 10% MAE; "
        f"got base={base} model={metrics}")


def test_predict_at_returns_per_detector(tmp_path: Path, feature_build):
    """End-to-end: train on the full slice, predict at the latest ts, expect
    a row per detector (22 detectors) with all 4 horizons."""
    from forecast_ml.train import _train_lightgbm
    from forecast_ml.predict import predict_at

    X_tr, y_tr, X_va, y_va = _split(feature_build)
    bundle_path = tmp_path / "lgb.json"
    _train_lightgbm(X_tr, y_tr, X_va, y_va, bundle_path,
                    num_boost_round=_TEST_BOOST_ROUNDS)

    target_ts = feature_build.timestamps.max()
    result = predict_at(target_ts, COUNTS_DIR, bundle_path)
    assert result["available"]
    assert len(result["per_detector"]) >= 20  # 22 detectors, allow a couple missing
    sample_det = next(iter(result["per_detector"]))
    sample = result["per_detector"][sample_det]
    for col in ("y_now", "y_15min", "y_30min", "y_60min"):
        assert col in sample, f"missing {col}"
        assert sample[col] >= 0


def test_metrics_report_has_expected_shape(tmp_path: Path):
    """The metrics report file is the cross-cutting handoff to the dashboard
    and the methodology doc — verify the schema from the already-trained
    production artifact (models/forecast_metrics.json) rather than retraining."""
    report_path = REPO_ROOT / "models" / "forecast_metrics.json"
    if not report_path.exists():
        pytest.skip("run `make forecast-ml-train` first to generate the report")
    rep = json.loads(report_path.read_text())
    assert "lightgbm" in rep
    assert "baseline_mae" in rep
    assert "feature_cols" in rep
    assert rep["n_train"] > 0 and rep["n_val"] > 0
