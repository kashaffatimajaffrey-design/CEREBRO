"""
Unsupervised network anomaly detection.

This replaces v1's `generateMockLogs()`, which fabricated 15 random flows and
then planted an anomaly at index 3 (`logs[3].flags = 'SYN_FLOOD'`) so the LLM
would reliably "discover" something impressive. Nothing was detected; the answer
was written into the input.

Here the input is real flow records — from Zeek conn.log, Suricata EVE JSON, a
pcap import, or a labeled benchmark like CIC-IDS2017 — and the detection is
genuinely unsupervised: models are fitted on benign traffic only and score
unseen flows by how poorly they fit that baseline.

This is the "unsupervised learning" component of the parent FYP, made concrete.

Ensemble rationale — the three methods fail differently, which is the point:
  IsolationForest   isolates points that are easy to separate. Fast, robust,
                    strong on univariate outliers (a 15 KB packet). Weak on
                    anomalies that are only strange in combination.
  Autoencoder       learns the benign manifold and flags high reconstruction
                    error. Catches subtle multivariate deviation. Needs more
                    data and is slower to train.
  DBSCAN            clusters the anomalies themselves, turning 400 alerts from
                    one botnet into a single incident. Not a detector so much
                    as an aggregator — but it is what makes output actionable.

Every score is accompanied by per-feature attribution. An anomaly score with no
explanation is not actionable, and an analyst will (rightly) start ignoring the
tool within a week.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import numpy as np

log = logging.getLogger(__name__)

# The feature contract. Order is significant — it is baked into fitted models,
# so appending is safe but reordering or removing is a model-version change.
FEATURE_NAMES: tuple[str, ...] = (
    "duration_ms",
    "fwd_packets", "bwd_packets",
    "fwd_bytes", "bwd_bytes",
    "total_packets", "total_bytes",
    "bytes_per_second", "packets_per_second",
    "down_up_ratio",
    "fwd_pkt_len_mean", "fwd_pkt_len_std", "fwd_pkt_len_max",
    "bwd_pkt_len_mean", "bwd_pkt_len_std", "bwd_pkt_len_max",
    "iat_mean", "iat_std", "iat_max",
    "syn_count", "fin_count", "rst_count", "psh_count", "ack_count", "urg_count",
    "dst_port", "is_wellknown_port", "protocol_tcp", "protocol_udp", "protocol_icmp",
)

N_FEATURES = len(FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Flow representation
# ---------------------------------------------------------------------------

@dataclass
class Flow:
    """
    A bidirectional network flow. Field names follow Zeek's conn.log where
    they overlap, so ingestion is close to a direct mapping.
    """
    ts: datetime
    src_ip: str
    dst_ip: str
    src_port: int = 0
    dst_port: int = 0
    protocol: str = "tcp"
    duration_ms: float = 0.0
    fwd_packets: int = 0
    bwd_packets: int = 0
    fwd_bytes: int = 0
    bwd_bytes: int = 0
    fwd_pkt_lengths: list[int] = field(default_factory=list)
    bwd_pkt_lengths: list[int] = field(default_factory=list)
    inter_arrival_times: list[float] = field(default_factory=list)
    tcp_flags: dict[str, int] = field(default_factory=dict)
    label: str | None = None          # ground truth, only for labeled datasets
    flow_id: str | None = None


def _safe_stats(values: Sequence[float]) -> tuple[float, float, float]:
    """(mean, std, max) that never returns NaN — models reject NaN."""
    if not values:
        return 0.0, 0.0, 0.0
    arr = np.asarray(values, dtype=np.float64)
    return float(arr.mean()), float(arr.std()), float(arr.max())


def extract_features(flow: Flow) -> np.ndarray:
    """
    Turn a Flow into the fixed-length numeric vector the models consume.

    These are the CICFlowMeter-family features used by the CIC-IDS and UNSW-NB15
    literature, which means results here are directly comparable to published
    baselines — important for the evaluation chapter.
    """
    total_packets = flow.fwd_packets + flow.bwd_packets
    total_bytes = flow.fwd_bytes + flow.bwd_bytes
    duration_s = max(flow.duration_ms / 1000.0, 1e-6)

    fwd_mean, fwd_std, fwd_max = _safe_stats(flow.fwd_pkt_lengths)
    bwd_mean, bwd_std, bwd_max = _safe_stats(flow.bwd_pkt_lengths)
    iat_mean, iat_std, iat_max = _safe_stats(flow.inter_arrival_times)

    flags = {k.lower(): v for k, v in (flow.tcp_flags or {}).items()}
    proto = (flow.protocol or "").lower()

    vec = np.array([
        flow.duration_ms,
        flow.fwd_packets,
        flow.bwd_packets,
        flow.fwd_bytes,
        flow.bwd_bytes,
        total_packets,
        total_bytes,
        total_bytes / duration_s,
        total_packets / duration_s,
        (flow.bwd_bytes / flow.fwd_bytes) if flow.fwd_bytes else 0.0,
        fwd_mean, fwd_std, fwd_max,
        bwd_mean, bwd_std, bwd_max,
        iat_mean, iat_std, iat_max,
        flags.get("syn", 0), flags.get("fin", 0), flags.get("rst", 0),
        flags.get("psh", 0), flags.get("ack", 0), flags.get("urg", 0),
        flow.dst_port,
        1.0 if 0 < flow.dst_port < 1024 else 0.0,
        1.0 if proto == "tcp" else 0.0,
        1.0 if proto == "udp" else 0.0,
        1.0 if proto == "icmp" else 0.0,
    ], dtype=np.float64)

    return np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)


def build_matrix(flows: Iterable[Flow]) -> np.ndarray:
    rows = [extract_features(f) for f in flows]
    if not rows:
        return np.empty((0, N_FEATURES), dtype=np.float64)
    return np.vstack(rows)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class AnomalyResult:
    flow_id: str | None
    ts: datetime
    src_ip: str
    dst_ip: str
    score: float                     # ensemble, normalized 0..1
    is_anomaly: bool
    threshold: float
    method_scores: dict[str, float] = field(default_factory=dict)
    # Which features deviated most from the benign baseline, in sigmas.
    # This is what the analyst actually reads.
    attribution: list[dict[str, Any]] = field(default_factory=list)
    label: str | None = None         # ground truth when available

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


# ---------------------------------------------------------------------------
# Autoencoder — numpy, so there is no hard torch dependency for the base path
# ---------------------------------------------------------------------------

class _NumpyAutoencoder:
    """
    Small dense autoencoder trained with Adam on reconstruction MSE.

    Implemented in numpy deliberately: the anomaly path stays dependency-light
    and runs anywhere, while the parent FYP's PyTorch stack remains free to
    swap in a larger model through the same interface. For CIC-IDS-scale data
    this trains in seconds on CPU.
    """

    def __init__(self, n_in: int, hidden: int = 16, bottleneck: int = 8,
                 seed: int = 42) -> None:
        rng = np.random.default_rng(seed)
        def init(a: int, b: int) -> np.ndarray:
            # He initialization for ReLU layers.
            return rng.normal(0, math.sqrt(2.0 / a), size=(a, b))
        self.W1, self.b1 = init(n_in, hidden), np.zeros(hidden)
        self.W2, self.b2 = init(hidden, bottleneck), np.zeros(bottleneck)
        self.W3, self.b3 = init(bottleneck, hidden), np.zeros(hidden)
        self.W4, self.b4 = init(hidden, n_in), np.zeros(n_in)

    @staticmethod
    def _relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, x)

    def forward(self, X: np.ndarray) -> tuple[np.ndarray, ...]:
        h1 = self._relu(X @ self.W1 + self.b1)
        z = self._relu(h1 @ self.W2 + self.b2)
        h3 = self._relu(z @ self.W3 + self.b3)
        out = h3 @ self.W4 + self.b4
        return h1, z, h3, out

    def fit(self, X: np.ndarray, epochs: int = 200, lr: float = 1e-3,
            batch_size: int = 64, seed: int = 42) -> "_NumpyAutoencoder":
        rng = np.random.default_rng(seed)
        params = ["W1", "b1", "W2", "b2", "W3", "b3", "W4", "b4"]
        m = {p: np.zeros_like(getattr(self, p)) for p in params}
        v = {p: np.zeros_like(getattr(self, p)) for p in params}
        b1_, b2_, eps = 0.9, 0.999, 1e-8
        step = 0

        n = X.shape[0]
        for _ in range(epochs):
            idx = rng.permutation(n)
            for start in range(0, n, batch_size):
                batch = X[idx[start:start + batch_size]]
                if batch.shape[0] == 0:
                    continue
                step += 1
                h1, z, h3, out = self.forward(batch)
                bs = batch.shape[0]

                d_out = 2.0 * (out - batch) / bs
                grads = {
                    "W4": h3.T @ d_out,
                    "b4": d_out.sum(0),
                }
                d_h3 = (d_out @ self.W4.T) * (h3 > 0)
                grads["W3"] = z.T @ d_h3
                grads["b3"] = d_h3.sum(0)
                d_z = (d_h3 @ self.W3.T) * (z > 0)
                grads["W2"] = h1.T @ d_z
                grads["b2"] = d_z.sum(0)
                d_h1 = (d_z @ self.W2.T) * (h1 > 0)
                grads["W1"] = batch.T @ d_h1
                grads["b1"] = d_h1.sum(0)

                for p in params:
                    g = grads[p]
                    m[p] = b1_ * m[p] + (1 - b1_) * g
                    v[p] = b2_ * v[p] + (1 - b2_) * (g * g)
                    m_hat = m[p] / (1 - b1_ ** step)
                    v_hat = v[p] / (1 - b2_ ** step)
                    setattr(self, p, getattr(self, p) - lr * m_hat / (np.sqrt(v_hat) + eps))
        return self

    def reconstruction_error(self, X: np.ndarray) -> np.ndarray:
        _, _, _, out = self.forward(X)
        return np.mean((X - out) ** 2, axis=1)


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------

class NetworkAnomalyDetector:
    """
    Fit on benign traffic, score anything.

    Usage:
        det = NetworkAnomalyDetector()
        det.fit(benign_flows)                  # unsupervised: no labels used
        results = det.score(new_flows)
        incidents = det.cluster_incidents(results)
    """

    def __init__(
        self,
        contamination: float = 0.02,
        threshold_percentile: float = 99.0,
        use_autoencoder: bool = True,
        random_state: int = 42,
    ) -> None:
        self.contamination = contamination
        self.threshold_percentile = threshold_percentile
        self.use_autoencoder = use_autoencoder
        self.random_state = random_state

        self._iforest: Any = None
        self._autoencoder: _NumpyAutoencoder | None = None
        self._mean: np.ndarray | None = None
        self._std: np.ndarray | None = None
        self._if_ref: tuple[float, float] | None = None   # (min, max) for normalization
        self._ae_ref: tuple[float, float] | None = None
        self.threshold: float = 0.5
        self.is_fitted: bool = False
        self.fit_metadata: dict[str, Any] = {}

    # -- scaling ------------------------------------------------------------

    def _fit_scaler(self, X: np.ndarray) -> None:
        self._mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std < 1e-9] = 1.0            # constant columns must not blow up
        self._std = std

    def _scale(self, X: np.ndarray) -> np.ndarray:
        assert self._mean is not None and self._std is not None
        # Clip after scaling: a single 15 KB packet should register as "very
        # large", not dominate every distance computation in the model.
        return np.clip((X - self._mean) / self._std, -10.0, 10.0)

    # -- fit ----------------------------------------------------------------

    def fit(self, flows: Sequence[Flow]) -> "NetworkAnomalyDetector":
        """
        Fit on traffic assumed to be predominantly benign.

        Note this is genuinely unsupervised — `flow.label` is never read here.
        Labels, when present, are used only for evaluation.
        """
        return self.fit_matrix(build_matrix(flows), n_rows=len(flows))

    def fit_matrix(self, X_raw: np.ndarray, *, n_rows: int | None = None) -> "NetworkAnomalyDetector":
        """
        Fit from a pre-extracted feature matrix whose columns are in FEATURE_NAMES
        order.

        This is the entry point for datasets that already provide CICFlowMeter
        features — CIC-IDS2017, UNSW-NB15 — where re-deriving statistics from raw
        packets is unnecessary and lossy. `fit()` is a thin wrapper that builds
        the matrix from Flow objects and calls this. Labels are never read here.
        """
        n = n_rows if n_rows is not None else int(X_raw.shape[0])
        if n < 20:
            raise ValueError(
                f"Need at least 20 flows to fit a baseline, got {n}. "
                "Fitting on less produces a model that flags everything."
            )
        if X_raw.shape[1] != N_FEATURES:
            raise ValueError(
                f"expected {N_FEATURES} feature columns (FEATURE_NAMES order), "
                f"got {X_raw.shape[1]}"
            )
        self._fit_scaler(X_raw)
        X = self._scale(X_raw)

        from sklearn.ensemble import IsolationForest  # local import: optional dep
        self._iforest = IsolationForest(
            n_estimators=200,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1,
        ).fit(X)

        # score_samples: higher = more normal. Negate so higher = more anomalous.
        if_scores = -self._iforest.score_samples(X)
        self._if_ref = (float(if_scores.min()), float(if_scores.max()))

        if self.use_autoencoder and n >= 50:
            self._autoencoder = _NumpyAutoencoder(
                n_in=X.shape[1], seed=self.random_state
            ).fit(X, epochs=200, seed=self.random_state)
            ae_err = self._autoencoder.reconstruction_error(X)
            self._ae_ref = (float(ae_err.min()), float(ae_err.max()))
        else:
            self._autoencoder = None

        combined = self._combine(X)
        self.threshold = float(np.percentile(combined, self.threshold_percentile))
        self.is_fitted = True

        self.fit_metadata = {
            "n_flows": n,
            "n_features": X.shape[1],
            "contamination": self.contamination,
            "threshold": self.threshold,
            "threshold_percentile": self.threshold_percentile,
            "autoencoder": self._autoencoder is not None,
            "fitted_at": datetime.now(timezone.utc).isoformat(),
        }
        log.info("detector fitted: %s", self.fit_metadata)
        return self

    # -- scoring ------------------------------------------------------------

    @staticmethod
    def _norm(values: np.ndarray, ref: tuple[float, float] | None) -> np.ndarray:
        if ref is None:
            return np.zeros_like(values)
        lo, hi = ref
        if hi - lo < 1e-12:
            return np.zeros_like(values)
        # Allow >1.0: a flow far outside the training range SHOULD exceed the
        # observed maximum. Clipping at 1.0 here would hide the worst cases.
        return (values - lo) / (hi - lo)

    def _combine(self, X: np.ndarray) -> np.ndarray:
        if_scores = self._norm(-self._iforest.score_samples(X), self._if_ref)
        if self._autoencoder is None:
            return np.clip(if_scores, 0.0, 1.0)
        ae_scores = self._norm(
            self._autoencoder.reconstruction_error(X), self._ae_ref
        )
        # Equal weight. Tune on a validation split if you have labels;
        # report the weighting you chose and why.
        return np.clip(0.5 * if_scores + 0.5 * ae_scores, 0.0, 1.0)

    def _attribute(self, x_scaled: np.ndarray, top_k: int = 5) -> list[dict[str, Any]]:
        """
        Per-feature deviation from the benign mean, in standard deviations.
        Simple, honest, and directly interpretable — unlike SHAP, it needs no
        extra dependency and an analyst can verify it by hand.
        """
        deviations = np.abs(x_scaled)
        order = np.argsort(-deviations)[:top_k]
        out = []
        for i in order:
            if deviations[i] < 1.0:      # within 1 sigma is not noteworthy
                continue
            out.append({
                "feature": FEATURE_NAMES[i],
                "z_score": round(float(x_scaled[i]), 3),
                "direction": "high" if x_scaled[i] > 0 else "low",
            })
        return out

    def score(self, flows: Sequence[Flow]) -> list[AnomalyResult]:
        if not flows:
            return []
        meta = [
            {"flow_id": f.flow_id, "ts": f.ts, "src_ip": f.src_ip,
             "dst_ip": f.dst_ip, "label": f.label}
            for f in flows
        ]
        return self.score_matrix(build_matrix(flows), meta=meta)

    def score_matrix(
        self, X_raw: np.ndarray, *, meta: Sequence[dict[str, Any]] | None = None,
    ) -> list[AnomalyResult]:
        """
        Score a pre-extracted matrix (FEATURE_NAMES column order).

        `meta` optionally carries per-row identity for the results — flow_id, ts,
        src_ip, dst_ip, label. It is used only to populate the result objects (and
        `label` for later evaluation); it never influences the score. This is the
        entry point CIC-IDS2017 / UNSW-NB15 evaluation uses.
        """
        if not self.is_fitted:
            raise RuntimeError("Detector must be fitted before scoring")
        if X_raw.shape[0] == 0:
            return []

        X = self._scale(X_raw)
        n = X.shape[0]
        if_raw = self._norm(-self._iforest.score_samples(X), self._if_ref)
        ae_raw = (
            self._norm(self._autoencoder.reconstruction_error(X), self._ae_ref)
            if self._autoencoder is not None else np.zeros(n)
        )
        combined = self._combine(X)

        # A placeholder timestamp for rows whose source (e.g. a CIC-IDS CSV) does
        # not carry one; AnomalyResult.as_dict() calls ts.isoformat(), so ts must
        # never be None.
        default_ts = datetime.now(timezone.utc)

        results = []
        for i in range(n):
            m = meta[i] if meta is not None and i < len(meta) else {}
            methods = {"isolation_forest": round(float(if_raw[i]), 4)}
            if self._autoencoder is not None:
                methods["autoencoder"] = round(float(ae_raw[i]), 4)
            results.append(AnomalyResult(
                flow_id=m.get("flow_id"),
                ts=m.get("ts") or default_ts,
                src_ip=m.get("src_ip", ""),
                dst_ip=m.get("dst_ip", ""),
                score=round(float(combined[i]), 4),
                is_anomaly=bool(combined[i] >= self.threshold),
                threshold=round(self.threshold, 4),
                method_scores=methods,
                attribution=self._attribute(X[i]),
                label=m.get("label"),
            ))
        return results

    # -- persistence --------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the fitted detector (arrays + IsolationForest + autoencoder)."""
        if not self.is_fitted:
            raise RuntimeError("refusing to save an unfitted detector")
        import joblib

        joblib.dump(self, path)
        log.info("saved anomaly detector -> %s", path)

    @staticmethod
    def load(path: str) -> "NetworkAnomalyDetector":
        import joblib

        det = joblib.load(path)
        if not isinstance(det, NetworkAnomalyDetector):
            raise TypeError(f"{path} did not contain a NetworkAnomalyDetector")
        return det

    # -- incident clustering ------------------------------------------------

    def cluster_incidents(
        self, results: Sequence[AnomalyResult], eps: float = 0.5, min_samples: int = 3
    ) -> list[dict[str, Any]]:
        """
        Group anomalies into incidents with DBSCAN.

        Without this, a port scan across 300 hosts becomes 300 alerts and the
        analyst stops reading. With it, it becomes one incident with 300
        entities — which is what actually happened.
        """
        anomalies = [r for r in results if r.is_anomaly]
        if len(anomalies) < min_samples:
            return []

        from sklearn.cluster import DBSCAN

        # Cluster on behaviour, not identity: score plus attribution shape.
        feature_index = {name: i for i, name in enumerate(FEATURE_NAMES)}
        vectors = []
        for r in anomalies:
            v = np.zeros(len(FEATURE_NAMES) + 1)
            v[0] = r.score
            for a in r.attribution:
                v[feature_index[a["feature"]] + 1] = a["z_score"]
            vectors.append(v)

        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms < 1e-9] = 1.0
        labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine").fit_predict(
            matrix / norms
        )

        incidents = []
        for cluster_id in sorted(set(labels)):
            if cluster_id == -1:          # DBSCAN noise: isolated anomalies
                continue
            members = [anomalies[i] for i, c in enumerate(labels) if c == cluster_id]
            srcs = sorted({m.src_ip for m in members})
            dsts = sorted({m.dst_ip for m in members})
            top_features: dict[str, int] = {}
            for m in members:
                for a in m.attribution:
                    top_features[a["feature"]] = top_features.get(a["feature"], 0) + 1
            max_score = max(m.score for m in members)
            incidents.append({
                "cluster_id": int(cluster_id),
                "member_count": len(members),
                "max_score": round(max_score, 4),
                "mean_score": round(sum(m.score for m in members) / len(members), 4),
                "source_ips": srcs[:20],
                "source_count": len(srcs),
                "dest_ips": dsts[:20],
                "dest_count": len(dsts),
                "shared_features": sorted(
                    top_features.items(), key=lambda kv: -kv[1]
                )[:5],
                "severity": (
                    "critical" if max_score > 0.9 else
                    "high" if max_score > 0.75 else
                    "medium" if max_score > 0.5 else "low"
                ),
                "first_seen": min(m.ts for m in members).isoformat(),
                "last_seen": max(m.ts for m in members).isoformat(),
            })
        return incidents

    # -- evaluation ---------------------------------------------------------

    def evaluate(self, results: Sequence[AnomalyResult]) -> dict[str, Any]:
        """
        Metrics against ground-truth labels — the numbers for your thesis.

        Only usable on labeled datasets (CIC-IDS2017, UNSW-NB15). Labels are
        never used during fitting, so this is an honest held-out evaluation.
        """
        labeled = [r for r in results if r.label is not None]
        if not labeled:
            return {"error": "no labeled flows; cannot evaluate"}

        y_true = np.array([0 if r.label.upper() in {"BENIGN", "NORMAL"} else 1
                           for r in labeled])
        y_score = np.array([r.score for r in labeled])
        y_pred = np.array([int(r.is_anomaly) for r in labeled])

        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        tn = int(((y_pred == 0) & (y_true == 0)).sum())

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        metrics: dict[str, Any] = {
            "n": len(labeled),
            "true_positives": tp, "false_positives": fp,
            "false_negatives": fn, "true_negatives": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        }

        if len(set(y_true.tolist())) > 1:
            try:
                from sklearn.metrics import roc_auc_score, average_precision_score
                metrics["auc_roc"] = round(float(roc_auc_score(y_true, y_score)), 4)
                metrics["avg_precision"] = round(
                    float(average_precision_score(y_true, y_score)), 4)
            except Exception as exc:  # noqa: BLE001
                log.warning("AUC computation failed: %s", exc)
        return metrics


# ---------------------------------------------------------------------------
# Ingestion from real sources
# ---------------------------------------------------------------------------

def from_zeek_conn_log(lines: Iterable[str]) -> list[Flow]:
    """
    Parse Zeek conn.log (TSV or JSON lines).

    Zeek is the realistic live-capture path: run it against your own interface,
    point this at conn.log, and the pipeline is operating on real traffic.
    """
    flows: list[Flow] = []
    tsv_fields: list[str] | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#"):
            if line.startswith("#fields"):
                tsv_fields = line.split("\t")[1:]
            continue

        rec: dict[str, Any]
        if line.startswith("{"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
        elif tsv_fields:
            parts = line.split("\t")
            if len(parts) != len(tsv_fields):
                continue
            rec = dict(zip(tsv_fields, parts))
        else:
            continue

        def num(key: str, default: float = 0.0) -> float:
            val = rec.get(key, default)
            if val in ("-", "", None):
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        try:
            ts = datetime.fromtimestamp(num("ts"), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            ts = datetime.now(timezone.utc)

        history = str(rec.get("history", "") or "")
        flows.append(Flow(
            ts=ts,
            src_ip=str(rec.get("id.orig_h", rec.get("id_orig_h", "0.0.0.0"))),
            dst_ip=str(rec.get("id.resp_h", rec.get("id_resp_h", "0.0.0.0"))),
            src_port=int(num("id.orig_p") or num("id_orig_p")),
            dst_port=int(num("id.resp_p") or num("id_resp_p")),
            protocol=str(rec.get("proto", "tcp")),
            duration_ms=num("duration") * 1000.0,
            fwd_packets=int(num("orig_pkts")),
            bwd_packets=int(num("resp_pkts")),
            fwd_bytes=int(num("orig_ip_bytes") or num("orig_bytes")),
            bwd_bytes=int(num("resp_ip_bytes") or num("resp_bytes")),
            # Zeek's history string encodes flags: S=SYN, F=FIN, R=RST, etc.
            tcp_flags={
                "syn": history.lower().count("s"),
                "fin": history.lower().count("f"),
                "rst": history.lower().count("r"),
                "ack": history.lower().count("a"),
                "psh": history.lower().count("p"),
            },
            flow_id=str(rec.get("uid")) if rec.get("uid") else None,
        ))
    return flows
