#!/usr/bin/env python3
"""
Train the phishing email classifier from raw .eml corpora.

The features are the deterministic ones `analyze_email()` already extracts, so
this script does not reinvent feature engineering — it labels, splits, fits,
calibrates, evaluates on a held-out set, and saves an artifact the API can load.

Datasets (download separately — all free):
  - Nazario phishing corpus     -> label 1  (phishing)
  - SpamAssassin spam/ham       -> spam 1, ham 0
  - Enron ham sample            -> label 0  (benign)

Usage:
  python scripts/train_email_classifier.py \
      --phishing /data/nazario /data/spamassassin/spam \
      --benign   /data/enron_ham /data/spamassassin/ham \
      --out models/email_classifier.joblib

Each --phishing / --benign argument is a directory searched recursively for
message files (any extension; content is parsed as RFC 5322). Report the printed
metrics in your evaluation chapter — they are an honest held-out test because the
classifier never sees the test split during fitting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ml.email.classifier import train  # noqa: E402
from services.ml.email.forensics import analyze_email  # noqa: E402


def _load_dir(root: Path) -> list[dict]:
    """Extract features from every message file under a directory."""
    feats: list[dict] = []
    skipped = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            feats.append(analyze_email(raw).features)
        except Exception:  # noqa: BLE001 - a few corrupt messages are expected
            skipped += 1
    print(f"  {root}: {len(feats)} parsed, {skipped} skipped")
    return feats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phishing", nargs="+", required=True, help="phishing/spam dirs")
    ap.add_argument("--benign", nargs="+", required=True, help="benign/ham dirs")
    ap.add_argument("--out", default="models/email_classifier.joblib")
    ap.add_argument("--version", default="email-clf-0.1.0")
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("Extracting features…")
    phishing = [f for d in args.phishing for f in _load_dir(Path(d))]
    benign = [f for d in args.benign for f in _load_dir(Path(d))]
    if not phishing or not benign:
        print("ERROR: need at least one message in each class", file=sys.stderr)
        return 2

    X = phishing + benign
    y = [1] * len(phishing) + [0] * len(benign)
    print(f"\nTotal: {len(X)} messages ({len(phishing)} phishing, {len(benign)} benign)")

    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix,
    )

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=args.test_size, random_state=args.seed, stratify=y
    )

    print("Training…")
    clf = train(X_tr, y_tr, version=args.version, random_state=args.seed)

    # Held-out evaluation — the numbers you defend.
    scores = [clf.predict_proba(f) for f in X_te]
    preds = [int(s >= 0.5) for s in scores]
    tn, fp, fn, tp = confusion_matrix(y_te, preds, labels=[0, 1]).ravel()
    print("\n=== Held-out metrics ===")
    print(f"  backend      {clf.backend}")
    print(f"  n_test       {len(y_te)}")
    print(f"  precision    {precision_score(y_te, preds, zero_division=0):.4f}")
    print(f"  recall       {recall_score(y_te, preds, zero_division=0):.4f}")
    print(f"  f1           {f1_score(y_te, preds, zero_division=0):.4f}")
    try:
        print(f"  auc_roc      {roc_auc_score(y_te, scores):.4f}")
    except ValueError:
        pass
    print(f"  confusion    TN={tn} FP={fp} FN={fn} TP={tp}")

    clf.metrics.update({
        "held_out": {
            "precision": round(precision_score(y_te, preds, zero_division=0), 4),
            "recall": round(recall_score(y_te, preds, zero_division=0), 4),
            "f1": round(f1_score(y_te, preds, zero_division=0), 4),
            "n_test": len(y_te),
        }
    })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    clf.save(str(out))
    print(f"\nSaved -> {out}")
    print("Set EMAIL_CLASSIFIER_PATH to this file so the API loads it at startup;")
    print("the email route's score_source will then read 'model' instead of 'heuristic'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
