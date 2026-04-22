"""Train forecast models.

Two models trained on the same train/val split:
    1. **LightGBM regression** — one model per horizon (4 models, one each for
       y_now, y_15min, y_30min, y_60min). Multi-output handled by training
       four LGBMRegressor instances. Fast, interpretable, ships as primary.
    2. **LSTM baseline** — small PyTorch sequence-to-one model. Uses the same
       features but treats the lag values as a 5-step sequence. Slower,
       included for handbook completeness (handbook mentions LSTM by name).

Both are evaluated on a held-out final 20% (chronologically) and compared
against a persistence baseline (predict-same-as-last-bin) — the persistence
baseline is what an unsophisticated caller would do, so beating it shows the
ML adds value.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .features import (
    BIN_MIN,
    HORIZONS_BINS,
    build_features,
    feature_columns,
    target_columns,
)


def _train_lightgbm(X_tr: pd.DataFrame, y_tr: pd.DataFrame,
                    X_va: pd.DataFrame, y_va: pd.DataFrame,
                    out_path: Path,
                    num_boost_round: int = 300,
                    early_stop: int = 30) -> dict:
    """Train one LightGBM model per target column. Save all to a single
    JSON-of-strings file (one model_str entry per column)."""
    import lightgbm as lgb
    feat_cols = list(X_tr.columns)
    cat_cols = ["detector_code"]
    bundle: dict[str, str] = {"feature_cols": json.dumps(feat_cols)}
    metrics: dict[str, dict[str, float]] = {}
    for col in y_tr.columns:
        train_set = lgb.Dataset(X_tr, label=y_tr[col],
                                categorical_feature=cat_cols,
                                free_raw_data=False)
        val_set = lgb.Dataset(X_va, label=y_va[col],
                              categorical_feature=cat_cols,
                              reference=train_set,
                              free_raw_data=False)
        params = {
            "objective":   "regression",
            "metric":      "mae",
            "learning_rate": 0.05,
            "num_leaves":  31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 5,
            "verbose":     -1,
        }
        model = lgb.train(
            params, train_set,
            num_boost_round=num_boost_round,
            valid_sets=[train_set, val_set],
            valid_names=["train", "val"],
            callbacks=[lgb.early_stopping(early_stop, verbose=False)],
        )
        bundle[col] = model.model_to_string()
        # Score on val
        pred = model.predict(X_va)
        mae = float(np.mean(np.abs(pred - y_va[col].to_numpy())))
        metrics[col] = {"mae": round(mae, 3),
                        "best_iteration": int(model.best_iteration or 0)}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle))
    return metrics


def _train_lstm(X_tr: pd.DataFrame, y_tr: pd.DataFrame,
                X_va: pd.DataFrame, y_va: pd.DataFrame,
                out_path: Path,
                epochs: int = 8) -> dict:
    """Tiny PyTorch LSTM baseline. Uses the 5 lag values as a sequence;
    predicts all 4 horizons (multi-output regression head)."""
    import torch
    import torch.nn as nn

    lag_cols = [c for c in X_tr.columns if c.startswith("lag_")]
    other_cols = [c for c in X_tr.columns if c not in lag_cols]
    n_targets = y_tr.shape[1]

    def _to_tensors(X: pd.DataFrame, y: pd.DataFrame):
        # Sequence: shape (N, len(lag_cols), 1) — one feature per timestep
        seq = torch.tensor(X[lag_cols].to_numpy(dtype=np.float32))
        seq = seq.unsqueeze(-1)
        ctx = torch.tensor(X[other_cols].to_numpy(dtype=np.float32))
        tgt = torch.tensor(y.to_numpy(dtype=np.float32))
        return seq, ctx, tgt

    seq_tr, ctx_tr, y_tr_t = _to_tensors(X_tr, y_tr)
    seq_va, ctx_va, y_va_t = _to_tensors(X_va, y_va)

    class Net(nn.Module):
        def __init__(self, n_ctx: int, hidden: int = 32) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden,
                                num_layers=1, batch_first=True)
            self.head = nn.Sequential(
                nn.Linear(hidden + n_ctx, 32),
                nn.ReLU(),
                nn.Linear(32, n_targets),
            )
        def forward(self, seq: torch.Tensor, ctx: torch.Tensor) -> torch.Tensor:
            _, (h, _) = self.lstm(seq)
            h = h[-1]                            # (N, hidden)
            x = torch.cat([h, ctx], dim=1)
            return self.head(x)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = Net(n_ctx=ctx_tr.shape[1]).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    loss_fn = nn.L1Loss()  # MAE — comparable to LightGBM metric

    seq_tr_d, ctx_tr_d, y_tr_d = seq_tr.to(device), ctx_tr.to(device), y_tr_t.to(device)
    seq_va_d, ctx_va_d, y_va_d = seq_va.to(device), ctx_va.to(device), y_va_t.to(device)

    batch = 4096
    n = len(seq_tr_d)
    history: list[float] = []
    # Net only has Linear + ReLU + LSTM — no Dropout / BatchNorm — so we
    # don't need to toggle .train()/.eval() modes. We just gate gradient
    # tracking with torch.no_grad() during validation.
    for ep in range(epochs):
        idx = torch.randperm(n, device=device)
        ep_loss = 0.0
        for i in range(0, n, batch):
            sl = idx[i:i+batch]
            opt.zero_grad()
            pred = net(seq_tr_d[sl], ctx_tr_d[sl])
            loss = loss_fn(pred, y_tr_d[sl])
            loss.backward()
            opt.step()
            ep_loss += loss.item() * sl.numel()
        ep_loss /= n
        with torch.no_grad():
            val_pred = net(seq_va_d, ctx_va_d)
            val_mae = loss_fn(val_pred, y_va_d).item()
        history.append(val_mae)
        print(f"  [lstm] epoch {ep+1}/{epochs}  train_mae={ep_loss:.3f}  val_mae={val_mae:.3f}",
              file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict":  net.state_dict(),
        "n_ctx":       int(ctx_tr.shape[1]),
        "n_targets":   int(n_targets),
        "lag_cols":    lag_cols,
        "other_cols":  other_cols,
    }, out_path)
    return {
        "final_val_mae":   round(history[-1], 3),
        "best_val_mae":    round(min(history), 3),
        "epochs":          epochs,
        "device":          device,
    }


def _persistence_baseline(X_va: pd.DataFrame, y_va: pd.DataFrame) -> dict:
    """Predict every horizon = y_now's lag_1 (last 15-min count)."""
    if "lag_1" not in X_va.columns:
        return {col: None for col in y_va.columns}
    pred = X_va["lag_1"].to_numpy()
    out: dict[str, float] = {}
    for col in y_va.columns:
        mae = float(np.mean(np.abs(pred - y_va[col].to_numpy())))
        out[col] = round(mae, 3)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--counts-dir",  type=Path, default=Path("data/detector_counts"))
    p.add_argument("--signals-dir", type=Path, default=Path("data/signal_logs"))
    p.add_argument("--lgb-out",     type=Path, default=Path("models/forecast_lgb.json"))
    p.add_argument("--lstm-out",    type=Path, default=Path("models/forecast_lstm.pt"))
    p.add_argument("--report-out",  type=Path, default=Path("models/forecast_metrics.json"))
    p.add_argument("--val-frac",    type=float, default=0.2,
                   help="Fraction of timeline used for the held-out validation set")
    p.add_argument("--lstm-epochs", type=int, default=8)
    p.add_argument("--skip-lstm",   action="store_true")
    args = p.parse_args(argv)

    print(f"[train] loading features from {args.counts_dir} + {args.signals_dir}",
          file=sys.stderr)
    t0 = time.monotonic()
    fb = build_features(args.counts_dir, args.signals_dir)
    print(f"[train] feature matrix: {fb.train_X.shape}  targets: {list(fb.train_y.columns)}",
          file=sys.stderr)

    cutoff = int(len(fb.train_X) * (1 - args.val_frac))
    order = np.argsort(fb.timestamps.values)
    train_idx = order[:cutoff]
    val_idx   = order[cutoff:]
    X_tr, y_tr = fb.train_X.iloc[train_idx], fb.train_y.iloc[train_idx]
    X_va, y_va = fb.train_X.iloc[val_idx],   fb.train_y.iloc[val_idx]
    print(f"[train] split  train={len(X_tr):,}  val={len(X_va):,}", file=sys.stderr)

    print("[train] persistence baseline", file=sys.stderr)
    base = _persistence_baseline(X_va, y_va)
    for col, mae in base.items():
        print(f"  baseline {col:>10s}  MAE={mae}", file=sys.stderr)

    print("[train] LightGBM", file=sys.stderr)
    lgb_metrics = _train_lightgbm(X_tr, y_tr, X_va, y_va, args.lgb_out)
    for col, m in lgb_metrics.items():
        delta = base.get(col, 0) - m["mae"] if base.get(col) else 0
        print(f"  lgb      {col:>10s}  MAE={m['mae']}  iters={m['best_iteration']}  Δvs.baseline={delta:+.2f}",
              file=sys.stderr)

    if args.skip_lstm:
        lstm_metrics = {"skipped": True}
    else:
        print("[train] LSTM baseline", file=sys.stderr)
        lstm_metrics = _train_lstm(X_tr, y_tr, X_va, y_va,
                                   args.lstm_out, epochs=args.lstm_epochs)

    elapsed = time.monotonic() - t0
    report = {
        "elapsed_s":      round(elapsed, 1),
        "n_train":        len(X_tr),
        "n_val":          len(X_va),
        "n_features":     len(fb.train_X.columns),
        "feature_cols":   list(fb.train_X.columns),
        "target_cols":    list(fb.train_y.columns),
        "baseline_mae":   base,
        "lightgbm":       lgb_metrics,
        "lstm":           lstm_metrics,
        "lgb_path":       str(args.lgb_out),
        "lstm_path":      str(args.lstm_out),
        "trained_at":     pd.Timestamp.utcnow().isoformat(),
    }
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2))
    print(f"[train] done in {elapsed:.1f}s  report → {args.report_out}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
