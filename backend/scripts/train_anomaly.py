#!/usr/bin/env python3
"""
Fit and evaluate the network anomaly detector on CIC-IDS2017.

CIC-IDS2017's CSVs already contain CICFlowMeter features — the same family the
detector uses — so this maps its columns straight onto the detector's feature
vector and calls `fit_matrix` / `score_matrix`, rather than re-deriving stats
from raw packets. The model is fitted on BENIGN rows only (genuinely
unsupervised); labels are used solely for the held-out evaluation, which is what
makes the reported AUC/precision/recall honest.

Get the data (see scripts/fetch_datasets.py --list):
  https://www.unb.ca/cic/datasets/ids-2017.html   (MachineLearningCSV.zip)

Usage:
  python scripts/train_anomaly.py --csv-dir data/network/cicids2017 \
      --out models/anomaly_detector.joblib
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from services.ml.anomaly.detector import FEATURE_NAMES, NetworkAnomalyDetector  # noqa: E402

# CIC-IDS2017 column name (normalized: lowercased, single-spaced) -> our feature.
# Columns we derive (total_*, is_wellknown_port, protocol_*) are handled in code.
CIC_MAP = {
    "duration_ms": "flow duration",           # microseconds; converted below
    "fwd_packets": "total fwd packets",
    "bwd_packets": "total backward packets",
    "fwd_bytes": "total length of fwd packets",
    "bwd_bytes": "total length of bwd packets",
    "bytes_per_second": "flow bytes/s",
    "packets_per_second": "flow packets/s",
    "down_up_ratio": "down/up ratio",
    "fwd_pkt_len_mean": "fwd packet length mean",
    "fwd_pkt_len_std": "fwd packet length std",
    "fwd_pkt_len_max": "fwd packet length max",
    "bwd_pkt_len_mean": "bwd packet length mean",
    "bwd_pkt_len_std": "bwd packet length std",
    "bwd_pkt_len_max": "bwd packet length max",
    "iat_mean": "flow iat mean",
    "iat_std": "flow iat std",
    "iat_max": "flow iat max",
    "syn_count": "syn flag count",
    "fin_count": "fin flag count",
    "rst_count": "rst flag count",
    "psh_count": "psh flag count",
    "ack_count": "ack flag count",
    "urg_count": "urg flag count",
    "dst_port": "destination port",
}


def _norm_key(k: str) -> str:
    return " ".join(k.strip().lower().split())


def _num(v: str) -> float:
    try:
        f = float(v)
    except (ValueError, TypeError):
        return 0.0
    return f if np.isfinite(f) else 0.0


def _row_to_vector(row: dict[str, str]) -> np.ndarray:
    g = row.get  # normalized-key getter set up by caller
    dst_port = _num(g("destination port", "0"))
    protocol = _num(g("protocol", "0"))
    fwd_pkts = _num(g(CIC_MAP["fwd_packets"], "0"))
    bwd_pkts = _num(g(CIC_MAP["bwd_packets"], "0"))
    fwd_bytes = _num(g(CIC_MAP["fwd_bytes"], "0"))
    bwd_bytes = _num(g(CIC_MAP["bwd_bytes"], "0"))

    values: dict[str, float] = {
        "duration_ms": _num(g("flow duration", "0")) / 1000.0,  # µs -> ms
        "fwd_packets": fwd_pkts,
        "bwd_packets": bwd_pkts,
        "fwd_bytes": fwd_bytes,
        "bwd_bytes": bwd_bytes,
        "total_packets": fwd_pkts + bwd_pkts,
        "total_bytes": fwd_bytes + bwd_bytes,
        "bytes_per_second": _num(g("flow bytes/s", "0")),
        "packets_per_second": _num(g("flow packets/s", "0")),
        "down_up_ratio": _num(g("down/up ratio", "0")),
        "fwd_pkt_len_mean": _num(g(CIC_MAP["fwd_pkt_len_mean"], "0")),
        "fwd_pkt_len_std": _num(g(CIC_MAP["fwd_pkt_len_std"], "0")),
        "fwd_pkt_len_max": _num(g(CIC_MAP["fwd_pkt_len_max"], "0")),
        "bwd_pkt_len_mean": _num(g(CIC_MAP["bwd_pkt_len_mean"], "0")),
        "bwd_pkt_len_std": _num(g(CIC_MAP["bwd_pkt_len_std"], "0")),
        "bwd_pkt_len_max": _num(g(CIC_MAP["bwd_pkt_len_max"], "0")),
        "iat_mean": _num(g("flow iat mean", "0")),
        "iat_std": _num(g("flow iat std", "0")),
        "iat_max": _num(g("flow iat max", "0")),
        "syn_count": _num(g("syn flag count", "0")),
        "fin_count": _num(g("fin flag count", "0")),
        "rst_count": _num(g("rst flag count", "0")),
        "psh_count": _num(g("psh flag count", "0")),
        "ack_count": _num(g("ack flag count", "0")),
        "urg_count": _num(g("urg flag count", "0")),
        "dst_port": dst_port,
        "is_wellknown_port": 1.0 if 0 < dst_port < 1024 else 0.0,
        "protocol_tcp": 1.0 if protocol == 6 else 0.0,
        "protocol_udp": 1.0 if protocol == 17 else 0.0,
        "protocol_icmp": 1.0 if protocol == 1 else 0.0,
    }
    return np.array([values[name] for name in FEATURE_NAMES], dtype=np.float64)


def _load_csvs(csv_dir: Path) -> tuple[np.ndarray, list[str]]:
    rows: list[np.ndarray] = []
    labels: list[str] = []
    files = sorted(csv_dir.rglob("*.csv"))
    if not files:
        print(f"ERROR: no CSVs under {csv_dir}", file=sys.stderr)
        return np.empty((0, len(FEATURE_NAMES))), []
    for path in files:
        print(f"  reading {path.name} …", flush=True)
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                row = {_norm_key(k): v for k, v in raw.items() if k is not None}
                rows.append(_row_to_vector(row))
                labels.append((row.get("label", "") or "").strip().upper())
    X = np.vstack(rows) if rows else np.empty((0, len(FEATURE_NAMES)))
    return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), labels


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv-dir", required=True, help="directory of CIC-IDS2017 CSVs")
    ap.add_argument("--out", default="models/anomaly_detector.joblib")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--benign-train-frac", type=float, default=0.7)
    args = ap.parse_args()

    print("Loading CIC-IDS2017…")
    X, labels = _load_csvs(Path(args.csv_dir))
    if X.shape[0] == 0:
        return 2

    y = np.array([0 if lb in {"BENIGN", "NORMAL"} else 1 for lb in labels])
    benign_idx = np.where(y == 0)[0]
    attack_idx = np.where(y == 1)[0]
    print(f"  {X.shape[0]} flows: {len(benign_idx)} benign, {len(attack_idx)} attack")
    if len(benign_idx) < 100:
        print("ERROR: need substantially more benign flows to fit a baseline", file=sys.stderr)
        return 2

    rng = np.random.default_rng(args.seed)
    rng.shuffle(benign_idx)
    cut = int(len(benign_idx) * args.benign_train_frac)
    train_idx = benign_idx[:cut]                              # benign only — unsupervised
    test_idx = np.concatenate([benign_idx[cut:], attack_idx]) # held-out benign + all attacks

    det = NetworkAnomalyDetector(random_state=args.seed)
    print(f"Fitting on {len(train_idx)} benign flows (labels never read)…")
    det.fit_matrix(X[train_idx], n_rows=len(train_idx))

    print(f"Scoring {len(test_idx)} held-out flows…")
    meta = [{"label": labels[i]} for i in test_idx]
    results = det.score_matrix(X[test_idx], meta=meta)
    metrics = det.evaluate(results)

    print("\n=== Held-out metrics (honest: labels not used in fitting) ===")
    for k, v in metrics.items():
        print(f"  {k:20s} {v}")

    det.fit_metadata["held_out_metrics"] = metrics
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    det.save(str(out))
    print(f"\nSaved -> {out}")
    print("Set ANOMALY_MODEL_PATH to this file so /v1/analyze/flows scores live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
