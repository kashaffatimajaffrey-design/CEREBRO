"""
Trained phishing classifier — the learned head that replaces the heuristic prior.

`forensics.analyze_email()` already produces a stable, flat, numeric feature
vector. This module fits a gradient-boosted classifier on those features and
wraps it so the API can call it exactly the way the email router expects:

    clf = PhishingClassifier.load("models/email_classifier.joblib")
    p   = clf.predict_proba(result.features)   # -> float in [0,1]
    ver = clf.version

When such a model is present in `app.state.models['email_classifier']`, the
router's `score_source` flips from `"heuristic"` to `"model"` automatically —
no route change needed. Until then the transparent heuristic prior stands in,
labelled as such.

Two design choices worth stating:

  - **Calibration is mandatory, not optional.** An uncalibrated 0.9 means
    nothing to a security team. We wrap the estimator in isotonic calibration so
    a reported 0.9 means "≈9 of 10 emails scored this way were phishing." That
    is a claim you can defend and a number an analyst can act on.
  - **The feature order is frozen into the artifact.** Predicting requires the
    columns in the exact order training saw them; a dict is aligned to that
    saved order, and an unknown/absent feature is treated as 0. Appending a
    feature is therefore a new model version, which is the honest accounting.

Estimator backend: LightGBM when installed (per the design), otherwise
scikit-learn's HistGradientBoostingClassifier, which is always available and
performs comparably on tabular features of this size. The wrapper's interface is
identical either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_VERSION = "email-clf-0.1.0"


def _align(features: dict[str, Any], order: Sequence[str]) -> np.ndarray:
    """Turn a feature dict into a row vector in the model's frozen column order."""
    return np.array(
        [float(features.get(name, 0) or 0) for name in order], dtype=np.float64
    ).reshape(1, -1)


@dataclass
class PhishingClassifier:
    """A fitted, calibrated classifier plus the metadata that makes it auditable."""

    estimator: Any                     # calibrated sklearn/lightgbm estimator
    feature_order: list[str]
    version: str = DEFAULT_VERSION
    backend: str = "unknown"
    metrics: dict[str, Any] = field(default_factory=dict)

    def predict_proba(self, features: dict[str, Any]) -> float:
        """Probability the message is phishing, in [0,1]."""
        X = _align(features, self.feature_order)
        proba = self.estimator.predict_proba(X)[0]
        # Column 1 is the positive (phishing) class by sklearn convention.
        return float(proba[1]) if len(proba) > 1 else float(proba[0])

    def save(self, path: str) -> None:
        import joblib

        joblib.dump(
            {
                "estimator": self.estimator,
                "feature_order": self.feature_order,
                "version": self.version,
                "backend": self.backend,
                "metrics": self.metrics,
            },
            path,
        )
        log.info("saved classifier %s -> %s", self.version, path)

    @classmethod
    def load(cls, path: str) -> "PhishingClassifier":
        import joblib

        blob = joblib.load(path)
        return cls(
            estimator=blob["estimator"],
            feature_order=list(blob["feature_order"]),
            version=blob.get("version", DEFAULT_VERSION),
            backend=blob.get("backend", "unknown"),
            metrics=blob.get("metrics", {}),
        )


def _make_base_estimator(random_state: int) -> tuple[Any, str]:
    """LightGBM if available (the design default), else sklearn — same interface."""
    try:
        from lightgbm import LGBMClassifier

        return (
            LGBMClassifier(
                n_estimators=300,
                learning_rate=0.05,
                num_leaves=31,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=random_state,
                n_jobs=-1,
            ),
            "lightgbm",
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier

        log.warning("lightgbm not installed; using sklearn HistGradientBoostingClassifier")
        return (
            HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.05, random_state=random_state
            ),
            "sklearn-histgb",
        )


def train(
    feature_dicts: Sequence[dict[str, Any]],
    labels: Sequence[int],
    *,
    version: str = DEFAULT_VERSION,
    random_state: int = 42,
    calibrate: bool = True,
) -> PhishingClassifier:
    """
    Fit and calibrate on extracted features.

    Args:
        feature_dicts: `ForensicsResult.features` for each message.
        labels:        1 = phishing, 0 = benign, aligned to feature_dicts.

    The feature order is taken from the union of keys, sorted for determinism, so
    the same training set always yields the same column layout.
    """
    if len(feature_dicts) != len(labels):
        raise ValueError("feature_dicts and labels must be the same length")
    if len(set(labels)) < 2:
        raise ValueError("need both classes (phishing and benign) to train")

    feature_order = sorted({k for d in feature_dicts for k in d})
    X = np.vstack([_align(d, feature_order) for d in feature_dicts])
    y = np.asarray(labels, dtype=int)

    base, backend = _make_base_estimator(random_state)

    estimator: Any
    if calibrate and len(y) >= 20:
        from sklearn.calibration import CalibratedClassifierCV

        # Isotonic calibration via cross-validation: turns raw scores into
        # probabilities that actually mean what they say.
        estimator = CalibratedClassifierCV(base, method="isotonic", cv=3)
        estimator.fit(X, y)
    else:
        base.fit(X, y)
        estimator = base

    clf = PhishingClassifier(
        estimator=estimator,
        feature_order=feature_order,
        version=version,
        backend=backend,
        metrics={"n_train": int(len(y)), "n_phishing": int(y.sum()), "calibrated": calibrate},
    )
    log.info("trained %s (%s) on %d samples", version, backend, len(y))
    return clf
