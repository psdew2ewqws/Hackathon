"""Phase 3 §8.3 forecast bridge.

Thin wrappers around the pre-trained LightGBM (``forecast_ml.predict_at``) and
the NEMA 4-phase Webster optimizer from
``traffic_intel_sandbox.forecast.optimize``, surfaced through the Phase 3
FastAPI server as ``/api/forecast/ml`` and ``/api/recommendation/nema``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LGB_BUNDLE = _ROOT / "models" / "forecast_lgb.json"
DEFAULT_COUNTS_DIR = _ROOT / "data" / "detector_counts"
DEFAULT_METRICS = _ROOT / "models" / "forecast_metrics.json"


def forecast_ml_available(
    lgb_bundle: Path = DEFAULT_LGB_BUNDLE,
    counts_dir: Path = DEFAULT_COUNTS_DIR,
) -> tuple[bool, str]:
    """Return (available, reason) without importing heavy deps unless needed."""
    if not lgb_bundle.exists():
        return False, f"lgb bundle missing: {lgb_bundle}"
    if not counts_dir.exists() or not any(counts_dir.glob("*.parquet")):
        return False, f"no detector counts parquet under {counts_dir}"
    return True, "ok"


def model_metrics(metrics_path: Path = DEFAULT_METRICS) -> dict[str, Any]:
    if not metrics_path.exists():
        return {"available": False, "message": f"metrics missing: {metrics_path}"}
    data = json.loads(metrics_path.read_text())
    return {
        "available": True,
        "model_type": "lightgbm_multioutput",
        "trained_at": data.get("trained_at"),
        "n_train": data.get("n_train"),
        "n_val": data.get("n_val"),
        "baseline_mae": data.get("baseline_mae"),
        "lightgbm_mae": {k: v["mae"] for k, v in data.get("lightgbm", {}).items()},
        "feature_cols": data.get("feature_cols"),
        "horizons_min": [0, 15, 30, 60],
    }


def forecast_ml_horizons(
    target_ts: str | datetime | None = None,
    lgb_bundle: Path = DEFAULT_LGB_BUNDLE,
    counts_dir: Path = DEFAULT_COUNTS_DIR,
) -> dict[str, Any]:
    """Return predictions at +0, +15, +30, +60 min for ``target_ts`` using the
    pre-trained LightGBM.  ``target_ts`` defaults to now (UTC)."""
    ok, reason = forecast_ml_available(lgb_bundle, counts_dir)
    if not ok:
        return {"available": False, "message": reason}

    import pandas as pd
    from forecast_ml.predict import predict_at  # type: ignore[import-not-found]

    if target_ts is None:
        ts = pd.Timestamp.now(tz="UTC")
    elif isinstance(target_ts, datetime):
        if target_ts.tzinfo is None:
            target_ts = target_ts.replace(tzinfo=timezone.utc)
        ts = pd.Timestamp(target_ts).tz_convert("UTC")
    else:
        ts = pd.Timestamp(str(target_ts))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
    result = predict_at(ts, counts_dir=counts_dir, lgb_bundle=lgb_bundle)
    if not result.get("available", False):
        return result
    metrics = model_metrics()
    result["model_version"] = (metrics.get("trained_at") or "unknown")
    result["mae"] = metrics.get("lightgbm_mae")
    return result


def four_phase_nema_recommendation(
    fused: dict[str, dict],
    current_plan: dict | None = None,
) -> dict[str, Any]:
    """Wrap traffic_intel_sandbox.forecast.optimize.evaluate / recommend with
    the live ``fused`` per-approach snapshot from the Phase 3 fusion module.

    Signals are per NEMA convention: phase 2 = southbound main (S->N); 4 = westbound;
    6 = northbound main; 8 = eastbound.  We map our approach labels (S/N/E/W) by
    the direction vehicles COME from (i.e. S-approach vehicles head north under
    phase 2 green). ``optimize`` expects volumes per approach (vph); we convert
    demand_per_min -> vph (x60).
    """
    try:
        from traffic_intel_sandbox.forecast.optimize import (  # type: ignore[import-not-found]
            ApproachInput, evaluate, recommend,
        )
    except Exception as exc:
        return {"available": False, "message": f"optimize module unavailable: {exc}"}

    # Convert our fused state into the module's input shape (dict keyed by approach).
    # NEMA lane count per approach unknown; assume 2 through lanes per approach.
    inputs: dict = {}
    approach_phase = {"S": 2, "W": 4, "N": 6, "E": 8}
    for approach in ("S", "W", "N", "E"):
        f = fused.get(approach) or {}
        dpm = float(f.get("demand_per_min") or 0.0)
        volume_vph = dpm * 60.0
        inputs[approach] = ApproachInput(approach=approach, volume_vph=volume_vph, lanes=2)

    cycle, green = recommend(inputs)
    # Render recommended green dict keyed by approach, not NEMA phase number.
    phase_to_appr = {p: a for a, p in approach_phase.items()}
    per_approach = {
        phase_to_appr[phase]: {"phase_number": phase, "green_seconds": round(sec, 1)}
        for phase, sec in green.items()
    }

    # Evaluate against current_plan if provided.
    current_green = None
    eval_result = None
    if current_plan:
        current_green = {
            approach_phase["S"]: float(current_plan.get("S_green", current_plan.get("NS_green", 35))),
            approach_phase["N"]: float(current_plan.get("N_green", current_plan.get("NS_green", 35))),
            approach_phase["W"]: float(current_plan.get("W_green", current_plan.get("EW_green", 35))),
            approach_phase["E"]: float(current_plan.get("E_green", current_plan.get("EW_green", 35))),
        }
        try:
            eval_result = evaluate(inputs, current_green, cycle_s=sum(current_green.values()))
            eval_result = {
                "cycle_s": eval_result.cycle_s,
                "critical_y": eval_result.critical_y,
                "rows": [row.__dict__ for row in eval_result.rows],
                "summary": eval_result.summary,
            }
        except Exception as exc:
            LOG.exception("NEMA evaluate failed")
            eval_result = {"error": f"{exc}"}

    return {
        "available": True,
        "mode": "four_phase_nema",
        "cycle_seconds": round(cycle, 1),
        "per_approach": per_approach,
        "current_green_by_nema_phase": current_green,
        "evaluation": eval_result,
    }
