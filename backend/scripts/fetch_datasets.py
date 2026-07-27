#!/usr/bin/env python3
"""
Fetch training datasets from their public sources.

What this script CAN download automatically (no login, license-clean, stdlib
only): the **Apache SpamAssassin public corpus** — real spam and ham messages in
RFC 5322 format. That is enough to train and honestly evaluate the email
classifier end to end (`scripts/train_email_classifier.py`), today, with zero
manual steps.

What it CANNOT fetch (they gate behind a form, torrent, or account) is printed
with instructions instead of failing silently:
  - Nazario phishing corpus  — phishing-specific messages (monkey.org)
  - CIC-IDS2017              — labeled network flows for the anomaly model (UNB)

Everything lands under `backend/data/` (gitignored). Nothing large is committed.

Usage:
  python scripts/fetch_datasets.py                 # SpamAssassin -> data/email/{spam,ham}
  python scripts/fetch_datasets.py --list          # just print all sources and exit
"""

from __future__ import annotations

import argparse
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
_UA = {"User-Agent": "cerebro-dataset-fetcher/1.0"}

# Apache SpamAssassin public corpus — direct HTTP, bzip2 tarballs.
# https://spamassassin.apache.org/old/publiccorpus/
SA_BASE = "https://spamassassin.apache.org/old/publiccorpus/"
SPAMASSASSIN = {
    "spam": ["20030228_spam.tar.bz2", "20030228_spam_2.tar.bz2", "20050311_spam_2.tar.bz2"],
    "ham": ["20030228_easy_ham.tar.bz2", "20030228_easy_ham_2.tar.bz2", "20030228_hard_ham.tar.bz2"],
}

# Sources that require a manual step. Printed for the operator; not fetched.
MANUAL_SOURCES = [
    ("Nazario phishing corpus (phishing-specific .eml)",
     "https://monkey.org/~jose/phishing/",
     "Download, extract to data/email/phishing/, then pass it as a --phishing dir."),
    ("CIC-IDS2017 (labeled network flows, MachineLearningCSV.zip)",
     "https://www.unb.ca/cic/datasets/ids-2017.html",
     "Fill the short form, download MachineLearningCSV.zip, extract the CSVs to "
     "data/network/cicids2017/, then run scripts/train_anomaly.py."),
    ("CIC-IDS2017 mirror (no form, pre-cleaned CSVs)",
     "https://www.kaggle.com/datasets/dhoogla/cicids2017",
     "Kaggle account required; same CSVs, already de-duplicated."),
]


def _extract_messages(archive_bytes: bytes, dest: Path) -> int:
    """Extract every message file from a SpamAssassin tarball into `dest` flat."""
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:bz2") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if name.lower() in {"cmds"}:      # SpamAssassin index files, not mail
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            # Prefix with the archive stem to avoid collisions across tarballs.
            (dest / f"{written:06d}_{name}").write_bytes(fh.read())
            written += 1
    return written


def fetch_spamassassin() -> None:
    for label, files in SPAMASSASSIN.items():
        dest = DATA_ROOT / "email" / ("spam" if label == "spam" else "ham")
        total = 0
        for fname in files:
            url = SA_BASE + fname
            print(f"  downloading {fname} …", flush=True)
            try:
                req = urllib.request.Request(url, headers=_UA)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    blob = resp.read()
            except Exception as exc:  # noqa: BLE001
                print(f"    WARN could not fetch {url}: {exc}", file=sys.stderr)
                continue
            total += _extract_messages(blob, dest)
        print(f"  {label}: {total} messages -> {dest}")


def print_manual() -> None:
    print("\nManual datasets (open the link, then point the training scripts at them):")
    for name, url, how in MANUAL_SOURCES:
        print(f"\n  • {name}\n    {url}\n    {how}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print sources and exit")
    args = ap.parse_args()

    if args.list:
        print(f"SpamAssassin (auto): {SA_BASE}")
        print_manual()
        return 0

    print("Fetching Apache SpamAssassin public corpus (spam + ham)…")
    fetch_spamassassin()
    print("\nDone. Train the email classifier with, e.g.:")
    print("  python scripts/train_email_classifier.py \\")
    print("      --phishing data/email/spam --benign data/email/ham \\")
    print("      --out models/email_classifier.joblib")
    print_manual()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
