# CEREBRO — What this is, in plain English

## The one-liner

**CEREBRO is a threat-and-misinformation intelligence service.** You give it an
email, a news article, or network traffic; it tells you whether it's dangerous or
false — and, crucially, it shows you *why*: the exact features it measured, the
named model that scored them, and (for misinformation) the real source documents
that back the verdict.

It's built as a module of a larger academic system (a TFT + RoBERTa predictive
project), but it stands on its own as a working product.

---

## Why it exists — the problem it fixes

The previous version (v1) asked a chatbot (Gemini) "is this credible? give it a
score." That approach has four fatal flaws for a security tool:

- the "sources" it cited were **invented** — they didn't exist;
- you **can't measure it** — a chatbot score has no precision, recall, or accuracy;
- it's **not reproducible** — same input, different answer each time;
- it **leaks privacy** — your inbox gets shipped to a third party.

CEREBRO v2 is built on one rule that fixes all four:

> **Deterministic code and trained models decide. The language model only explains.**

The AI writes the human-readable summary; it never makes the call. That means
every verdict is measurable, repeatable, auditable, and runs locally.

---

## What it actually does — four modules

| Module | What it checks | How it decides | Status |
|---|---|---|---|
| **Email forensics** | Phishing / spoofing | ~35 real features from the raw message (SPF/DKIM/DMARC, DKIM alignment, lookalike domains, Unicode homographs, URL tricks) → **trained classifier** | ✅ working, trained |
| **Misinformation (RAG)** | True / false / unverifiable claims | Retrieves real evidence documents, judges each with an entailment model, cites URLs that actually resolve | ✅ working |
| **Network anomaly** | Intrusions / attacks | Unsupervised model fit on *normal* traffic only, flags what doesn't fit; explains which features deviated | ✅ pipeline ready |
| **Forecasting (TFT)** | Predicts threat volume ahead | Time-series model over accumulated detections, with confidence bands | ⏳ validated on real data; needs live history |

Plus the plumbing that makes it a product: multi-tenant database with row-level
isolation, real-time dashboard (Postgres → WebSocket, no polling), server-side
auth (scrypt + JWT + encrypted OAuth tokens), and honest health/readiness checks.

---

## Does it actually work? The evidence

Nothing here is a claim — these were run and measured.

**Tests: 67 / 67 passing** (email forensics, security/crypto, RAG, DB queries,
anomaly detection). 23 of those are *adversarial* security tests — JWT forgery,
token tampering, cross-tenant access — all rejected.

**Email classifier, trained on 7,443 real messages** (Apache SpamAssassin), held-out test:

| Metric | Result |
|---|---|
| Precision | 0.96 |
| Recall | 0.97 |
| F1 | 0.97 |
| AUC-ROC | 0.996 |

It even **corrects the simple heuristic**: one legitimate email the heuristic
wrongly flagged at 0.99, the trained model correctly scored 0.10.

**Forecasting, backtested on 7 months of real data** (NYC-taxi counts, a public
analog for event volume), 20 rolling held-out windows:

| Metric | Result | Honest read |
|---|---|---|
| MAE (median) | ~18.5% of mean | Point forecast tracks reality well |
| Interval coverage | 44.6% (target 80%) | Confidence bands are too narrow — a known limitation, stated openly |

---

## Is it implementation-ready?

**Mostly — with the boundaries stated honestly:**

- ✅ **Ready to run and demo:** detection (email, RAG, anomaly), the trained email
  model, the full API + database + auth + real-time dashboard, and a one-click
  free deploy (Render + Vercel).
- ⚠️ **Ready but needs your step:** deployment (requires *your* account
  logins); training the network model (requires downloading CIC-IDS2017).
- ⏳ **Not yet:** production forecasting (needs ~2 weeks of live history to
  accumulate — no dataset can substitute for the system's own data); tighter
  forecast confidence bands.

It is a strong, defensible **final-year-project / prototype-grade** system: the
core is real, measured, and auditable. It is **not** yet a hardened commercial
product (no load testing at scale, forecasting still maturing).

---

## Where can this be used?

- **Security Operations (SOC) assistant** — triage suspicious emails and network
  flows with an explanation an analyst can verify, not a black-box score.
- **Anti-phishing / email gateway** — score inbound mail with real header
  forensics and a calibrated model; privacy-preserving because it runs locally.
- **Fact-checking / newsroom tooling** — verify claims against an evidence corpus
  and get citations that actually resolve, or an honest "insufficient evidence."
- **Intrusion detection** — unsupervised anomaly detection on network telemetry
  (Zeek/Suricata), turning raw alerts into explained incidents.
- **Academic / research** — a reproducible, measurable platform with published
  metrics; the intended role as a feature/data layer for a larger predictive model.
- **SMB / self-hosted deployment** — the whole stack runs on a Raspberry Pi or a
  cheap VPS with no third-party AI dependency and no data leaving your control.

The common thread: anywhere a decision about "is this a threat / is this true"
needs to be **explainable and auditable**, not just asserted.

---

*For the full engineering detail see [`ARCHITECTURE.md`](ARCHITECTURE.md); for the
exact current gaps see [`STATUS.md`](STATUS.md); to deploy see
[`../infra/DEPLOY.md`](../infra/DEPLOY.md).*
