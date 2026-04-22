"""ML traffic forecasting (Phase 2 §7.4 deliverable).

Two models trained side-by-side on the synthetic detector + signal history:
    * LightGBM regression (production model — fast, tabular features)
    * LSTM baseline (handbook-mentioned algo, kept for completeness)

Both predict per-detector vehicle counts at +15 min, +30 min, +60 min
horizons.

Modules:
    features.py — assemble training matrix from data/detector_counts +
                  data/signal_logs + calendar features
    train.py    — fit both models, save artifacts under models/
    predict.py  — load model + emit predictions for a given timestamp
"""
