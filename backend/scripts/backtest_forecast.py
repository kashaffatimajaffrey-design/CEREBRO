#!/usr/bin/env python3
"""
Backtest the TFT forecasting pipeline on a REAL time series.

The point of this script is to answer, honestly: does the forecast pipeline
produce sensible quantile predictions on real data, or is it just plumbing? In
production TFT forecasts CEREBRO's own hourly detection volume — a series that
only exists once the system has been running. There is no public "detection
history" to download. So to VALIDATE the machinery we use a real, public,
week-scale traffic series as a stand-in: it has the same shape (hourly counts
with daily seasonality) that detection volume will have.

Dataset: Numenta Anomaly Benchmark (NAB) — real NYC taxi passenger *counts*,
30-min granularity, ~7 months (Jul 2014–Jan 2015), released under AGPL by
Numenta. Passenger counts are the closest public analog to detection counts:
real event volume with strong daily and weekly seasonality.
  https://github.com/numenta/NAB/tree/master/data/realKnownCause

Method (an honest held-out backtest, not a fit-and-report):
  1. Aggregate the raw readings to an hourly mean series.
  2. Train TFT on everything EXCEPT the last `--horizon` hours.
  3. Forecast those held-out hours.
  4. Score the forecast against the actuals it never saw:
       - MAE / RMSE of the p50 (median) prediction
       - interval coverage: fraction of actuals inside [p10, p90]
         (a well-calibrated 80% interval should cover ~0.80)

Usage:
  python scripts/backtest_forecast.py                 # downloads the series, runs
  python scripts/backtest_forecast.py --epochs 40 --horizon 48
"""

from __future__ import annotations

import argparse
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ml.forecast.tft import (  # noqa: E402
    ForecastConfig, ForecastUnavailable, InsufficientHistory, train_and_predict,
)

NAB_URL = (
    "https://raw.githubusercontent.com/numenta/NAB/master/"
    "data/realKnownCause/nyc_taxi.csv"
)
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "forecast"


def load_hourly_series() -> list[tuple[datetime, float]]:
    """Download the NAB series (once) and aggregate to an hourly mean."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    local = DATA_DIR / "nab_nyc_taxi.csv"
    if not local.exists():
        print(f"downloading real series -> {local}")
        urllib.request.urlretrieve(NAB_URL, local)  # noqa: S310 - fixed trusted URL

    buckets: dict[datetime, list[float]] = {}
    with local.open(encoding="utf-8") as fh:
        next(fh)  # header: timestamp,value
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ts_str, val_str = line.split(",")
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            hour = ts.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(hour, []).append(float(val_str))

    series = [(h, statistics.mean(v)) for h, v in sorted(buckets.items())]
    return series


def _torch_quantile_backtest(full_series: list, train_len: int, horizon: int, epochs: int):
    """
    A torch-only probabilistic forecaster: an LSTM encoder over the past week
    plus hour-of-day / day-of-week covariates, with three quantile heads
    (p10/p50/p90) trained by the pinball (quantile) loss.

    This is a deliberately compact stand-in for the production pytorch-forecasting
    TFT — same probabilistic-forecasting idea, fewer moving parts — used to
    validate the approach on real data in environments where pandas/
    pytorch-forecasting can't load. It returns objects with .p10/.p50/.p90 so the
    scoring code downstream is identical.
    """
    import numpy as np
    import torch
    import torch.nn as nn

    torch.manual_seed(42)
    np.random.seed(42)

    # Features span the FULL series so rolling inference can read real observed
    # history in the test region — but normalization stats and training windows
    # come from the TRAINING portion only, so there is no lookahead leakage.
    values = np.array([v for _, v in full_series], dtype=np.float64)
    hours = np.array([ts.hour for ts, _ in full_series], dtype=np.float64)
    dows = np.array([ts.weekday() for ts, _ in full_series], dtype=np.float64)

    mu, sd = values[:train_len].mean(), values[:train_len].std() or 1.0
    v_norm = (values - mu) / sd

    # Cyclical time encodings — the model's "known-future" covariates.
    def feats(idx: np.ndarray) -> np.ndarray:
        return np.stack([
            np.sin(2 * np.pi * hours[idx] / 24), np.cos(2 * np.pi * hours[idx] / 24),
            np.sin(2 * np.pi * dows[idx] / 7),   np.cos(2 * np.pi * dows[idx] / 7),
        ], axis=-1)

    L = min(168, train_len - horizon - 1)   # 1-week encoder window
    quantiles = [0.1, 0.5, 0.9]

    # Build (encoder_window -> next `horizon` values) training pairs — ONLY from
    # the training region, so no target ever falls in the held-out test region.
    xs, tcov, ys = [], [], []
    for start in range(0, train_len - L - horizon):
        enc_idx = np.arange(start, start + L)
        tgt_idx = np.arange(start + L, start + L + horizon)
        xs.append(np.concatenate([v_norm[enc_idx][:, None], feats(enc_idx)], axis=-1))
        tcov.append(feats(tgt_idx))
        ys.append(v_norm[tgt_idx])
    if not xs:
        return []
    X = torch.tensor(np.array(xs), dtype=torch.float32)          # [N, L, 5]
    Tc = torch.tensor(np.array(tcov), dtype=torch.float32)       # [N, H, 4]
    Y = torch.tensor(np.array(ys), dtype=torch.float32)          # [N, H]

    class QForecaster(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.enc = nn.LSTM(input_size=5, hidden_size=48, batch_first=True)
            self.head = nn.Sequential(
                nn.Linear(48 + horizon * 4, 128), nn.ReLU(),
                nn.Linear(128, horizon * len(quantiles)),
            )

        def forward(self, x, tc):
            _, (h, _) = self.enc(x)
            z = torch.cat([h[-1], tc.flatten(1)], dim=-1)
            return self.head(z).view(-1, horizon, len(quantiles))

    model = QForecaster()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    qs = torch.tensor(quantiles).view(1, 1, -1)

    n = X.shape[0]
    for ep in range(epochs):
        perm = torch.randperm(n)
        total = 0.0
        for i in range(0, n, 128):
            b = perm[i:i + 128]
            opt.zero_grad()
            pred = model(X[b], Tc[b])                 # [B, H, Q]
            err = Y[b].unsqueeze(-1) - pred            # [B, H, Q]
            loss = torch.maximum(qs * err, (qs - 1) * err).mean()  # pinball loss
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(b)
        if ep % max(1, epochs // 5) == 0 or ep == epochs - 1:
            print(f"  epoch {ep:3d}  pinball {total / n:.4f}")

    def predict_from(enc_end: int, ts_at):
        """Forecast `horizon` steps whose encoder window ends at index enc_end."""
        with torch.no_grad():
            enc_idx = np.arange(enc_end - L, enc_end)
            x = torch.tensor(
                np.concatenate([v_norm[enc_idx][:, None], feats(enc_idx)], axis=-1)[None],
                dtype=torch.float32)
            fh = np.array([(ts_at.hour + h + 1) % 24 for h in range(horizon)], dtype=float)
            fd = np.array([(ts_at.weekday() + (ts_at.hour + h + 1) // 24) % 7
                           for h in range(horizon)], dtype=float)
            tc = torch.tensor(np.stack([
                np.sin(2 * np.pi * fh / 24), np.cos(2 * np.pi * fh / 24),
                np.sin(2 * np.pi * fd / 7),  np.cos(2 * np.pi * fd / 7),
            ], axis=-1)[None], dtype=torch.float32)
            out = model(x, tc)[0].numpy()
        out = out * sd + mu
        out.sort(axis=1)                              # enforce p10<=p50<=p90
        return out

    return predict_from, L


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon", type=int, default=24, help="hours ahead to forecast")
    ap.add_argument("--test-days", type=int, default=21, help="held-out test region")
    ap.add_argument("--step", type=int, default=12, help="hours between rolling origins")
    ap.add_argument("--epochs", type=int, default=80)
    args = ap.parse_args()

    series = load_hourly_series()
    print(f"real series: {len(series)} hourly points "
          f"({series[0][0].date()} to {series[-1][0].date()})")

    if len(series) <= args.horizon + 24:
        print("ERROR: series too short for this horizon", file=sys.stderr)
        return 2

    # Hold out a multi-week TEST REGION at the end; train only on what precedes
    # it. Then roll the forecast origin across the test region and average the
    # scores — a single 48h window is high-variance and can land on a known
    # anomaly (the NYC-taxi series famously contains the Jan-2015 blizzard, NYC
    # marathon, Thanksgiving, etc.), so one window is not a fair calibration test.
    test_hours = args.test_days * 24
    train_region = series[:-test_hours]
    vals = [v for _, v in series]
    tss = [ts for ts, _ in series]

    config = ForecastConfig(series="nab_taxi", horizon_hours=args.horizon,
                            max_epochs=args.epochs)

    print(f"training on {len(train_region)} points; rolling backtest over the "
          f"last {args.test_days} days ({args.horizon}h horizon)…")
    try:
        # Production path (normal machines): the real pytorch-forecasting TFT.
        result = train_and_predict(train_region, config)
        print("(used the production pytorch-forecasting TFT)")
        # Single-origin score for the TFT path (its retraining per origin is costly).
        origins = [len(train_region)]
        def predict_at(origin):  # noqa: E306
            return None  # handled below via `result`
        preds_by_origin = {len(train_region): result.points}
        rolling = False
    except InsufficientHistory as exc:
        print(f"\nSKIPPED — {exc}", file=sys.stderr)
        return 3
    except ForecastUnavailable as exc:
        # pandas/pytorch-forecasting can't load here → torch-only quantile model.
        print(f"(pytorch-forecasting unavailable: {exc.__class__.__name__}; "
              "using the torch-only quantile forecaster)")
        predict_from, _L = _torch_quantile_backtest(
            series, len(train_region), args.horizon, args.epochs)
        rolling = True

    # Roll the origin across the test region, one forecast every `--step` hours.
    all_abs, all_sq, all_cov, all_actual, n_windows = [], [], [], [], 0
    origins = range(len(train_region), len(series) - args.horizon, args.step)
    for origin in origins:
        actual = vals[origin:origin + args.horizon]
        if rolling:
            out = predict_from(origin, tss[origin - 1])            # [H, 3]
            rows = [(out[h][0], out[h][1], out[h][2]) for h in range(args.horizon)]
        else:
            pts = preds_by_origin[origin][: args.horizon]
            rows = [(p.p10, p.p50, p.p90) for p in pts]
        for h in range(min(len(rows), len(actual))):
            p10, p50, p90 = rows[h]
            all_abs.append(abs(p50 - actual[h]))
            all_sq.append((p50 - actual[h]) ** 2)
            all_cov.append(1 if p10 <= actual[h] <= p90 else 0)
            all_actual.append(actual[h])
        n_windows += 1
        if not rolling:
            break

    mean_actual = statistics.mean(all_actual) or 1e-9
    print("\n=== Rolling held-out backtest (forecasts vs. actuals never seen) ===")
    print(f"  windows            {n_windows}  ({len(all_abs)} forecast-hours)")
    print(f"  MAE (p50)          {statistics.mean(all_abs):.1f}")
    print(f"  RMSE (p50)         {statistics.mean(all_sq) ** 0.5:.1f}")
    print(f"  MAPE-ish (MAE/mean){statistics.mean(all_abs) / mean_actual:.1%}")
    print(f"  p10-p90 coverage   {statistics.mean(all_cov):.1%}   (target ~80%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
