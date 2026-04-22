"""Phase 3 §8.3 forecast bridge — wraps forecast_ml + NEMA optimizer."""
from .bridge import (
    forecast_ml_horizons,
    forecast_ml_available,
    four_phase_nema_recommendation,
    model_metrics,
)
from .holiday_calendar import is_holiday, next_holiday

__all__ = [
    "forecast_ml_horizons",
    "forecast_ml_available",
    "four_phase_nema_recommendation",
    "model_metrics",
    "is_holiday",
    "next_holiday",
]
