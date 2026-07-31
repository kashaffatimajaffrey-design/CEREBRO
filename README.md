# CEREBRO

**Threat & misinformation intelligence** — an evidence-producing security platform.
Give it an email, a news claim, or network traffic; it tells you whether it's
dangerous or false, and shows you *why*: the exact features it measured, the
named model or heuristic that scored them, and — for misinformation — real
fact-check sources you can open and read.

It's built to be the **data & feature layer** for a larger predictive system
(the *Apollo* TFT + RoBERTa project) — the eyes and ears that feed the brain.

---

## 🚀 Live demo

| | |
|---|---|
| **App** | **https://cerebro-sandy-beta.vercel.app** |
| **API docs** | https://cerebro-api-nmah.onrender.com/docs |
| **Demo login** | `demo@cerebro.app` / `cerebro-demo-2026` (or use **SIGN_UP**) |

> The backend runs on a free tier that sleeps after ~15 min idle, so the first
> request after a quiet spell takes ~50 s to wake up, then it's fast. Works on
> desktop and mobile (iOS/Android).

**Stack:** React 19 + Vite (Vercel) · FastAPI (Render) · Postgres 16 + pgvector
(Render). Frontend and API are separate services talking over HTTPS + WebSocket.

---

## The architectural rule

> **Deterministic code and trained models decide. The language model only explains.**

The previous version asked a chatbot for a "credibility score" — invented
sources, no measurable accuracy, not reproducible, and it shipped inboxes to a
third party. CEREBRO inverts that: every verdict is measurable, repeatable,
auditable, and runs locally. The LLM (optional) only writes prose about results
that already exist.

---

## What works today

| Module | What it does | How it decides |
|---|---|---|
| **Email forensics** | Phishing / spoofing | ~35 deterministic signals from the raw RFC 5322 message — SPF/DKIM/DMARC + DKIM alignment, lookalike domains, Unicode homographs, URL tricks. A trained classifier (F1 0.97 on SpamAssassin) can be loaded to replace the heuristic prior. |
| **Misinformation** | True / false / unverifiable | **Google Fact Check Tools API** returns real fact-checks (Full Fact, FactCheck.org, PolitiFact…) with ratings + **clickable source links**. Falls back to a hybrid-RAG check, then a transparent linguistic heuristic when nothing is found. |
| **Network anomaly** | Intrusions / attacks | Transparent rule-based triage (SYN floods, oversized packets, ICMP floods, scan sources) on labeled sample traffic. A real unsupervised model (IsolationForest + autoencoder, trainable on CIC-IDS2017) loads in when registered. |
| **Dashboard** | Live metrics | Real counts over the `detections` table, event-driven via Postgres `NOTIFY` → WebSocket. |
| **Auth** | Multi-tenant | scrypt + stdlib JWT (rejects `alg=none`), AES-GCM-encrypted OAuth tokens, row-level security in the database, Bearer-token sessions that work on iOS Safari. |

Every verdict carries a `score_source` (`heuristic` / `model` / `fact_check` /
`rag_evidence`) so it's never mistaken for more certainty than it has.

---

## The data it collects (and how it feeds Apollo)

Every analysis is **persisted to Postgres**, which is the whole point for the
parent project:

- `detections` — the unified stream: `(ts, tenant, module, threat_type,
  risk_score, summary)`. This is the hourly time-series the **TFT forecaster**
  consumes.
- `email_analyses` — the full forensic record (SPF/DKIM/DMARC, from-domain,
  features, indicators, verdict) → labeled **classifier training data**.
- `verdicts`, `anomalies`, `analyst_feedback` — verdicts with evidence, network
  anomalies, and the correction→retrain flywheel.

**Apollo connects to CEREBRO via any of:**
1. **Shared database** — query the tables above with plain SQL (the intended
   integration; the schema is designed for it).
2. **Realtime event stream** — `pg_notify('cerebro_events', …)` fires on every
   detection; a consumer gets it with no polling.
3. **REST API** — `/v1/analyze/*`, `/v1/metrics/*`, `/v1/flows/*`, `/v1/stream`.
4. **`model_registry`** — one shared table so both projects version models the
   same way.

Grab the data for Apollo:
```bash
psql "<cerebro-db connection string>" \
  -c "SELECT ts, module, threat_type, risk_score, summary FROM cerebro.detections ORDER BY ts DESC;"
```

CEREBRO turns raw text and telemetry into the engineered features Apollo's
predictive core consumes — a clean, defensible module boundary.

---

## Run it locally

Everything runs in Docker on a laptop — no accounts, no keys required.

```bash
git clone https://github.com/kashaffatimajaffrey-design/CEREBRO.git
cd CEREBRO
docker compose up -d          # Postgres + pgvector, Redis, API (seeds a demo login)
cd frontend && npm install && npm run dev
```

- App: http://localhost:5173  ·  API docs: http://localhost:8000/docs
- Login: `demo@cerebro.app` / `cerebro-demo-2026`

> On a restricted network that can't pull the `pgvector` image, build it from
> the cached base first: `docker build -f deploy/local/Dockerfile.pgvector -t
> cerebro-pgvector:pg16 .` (a compose override wires it in automatically).

### Optional: better results
```bash
cd backend
python scripts/fetch_datasets.py                                  # SpamAssassin corpus
python scripts/train_email_classifier.py --phishing data/email/spam --benign data/email/ham \
    --out models/email_classifier.joblib                          # F1 ~0.97 → set EMAIL_CLASSIFIER_PATH
```
Set `FACT_CHECK_API_KEY` (free from Google) for real news sources with citations.

---

## Deploy your own

See [`infra/DEPLOY.md`](infra/DEPLOY.md). The live instance uses **Render**
(backend + Postgres, one-click via [`render.yaml`](render.yaml)) + **Vercel**
(frontend). Set `VITE_API_BASE` to the API URL, and `CORS_ORIGINS` /
`SESSION_COOKIE_SAMESITE=none` for the cross-site setup.

---

## Project layout

```
frontend/     React 19 + Vite SPA — dashboard, scanners, auth, live threat-map UI
backend/
  services/api/     FastAPI: routers (auth, email, news, network, metrics, flows,
                    stream, forecast), core (db/asyncpg, queries, security, deps)
  services/ml/      email forensics · RAG verify · anomaly detector · TFT · LLM providers
  db/               schema_portable.sql · queries.sql
  scripts/          dataset fetch, model training, backtest
docs/         ARCHITECTURE · STATUS · OVERVIEW · FRONTEND_MIGRATION
infra/        render.yaml · netlify.toml · DEPLOY.md
deploy/       huggingface/ · local/ (pgvector build)
```

---

## Honest gaps / roadmap

Stating these is what makes the rest credible.

- **Automated ingestion** (RSS/IMAP/Zeek workers) isn't built — data currently
  enters through the API. This is the next step to a self-feeding pipeline.
- **Trained classifiers** ship as scripts, not loaded in the live instance
  (email/anomaly run on the heuristic + rule-based paths until a model is set).
- **TFT forecasting** is scaffolded and validated on real data (see
  [`docs/STATUS.md`](docs/STATUS.md)) but needs ~2 weeks of accumulated
  `detections` history before it produces production forecasts.
- The evidence-corpus RAG path is thin on the hosted instance; the Google Fact
  Check API covers well-known claims, and the heuristic covers the rest.

---

## Tests

```bash
cd backend
python tests/test_forensics.py   # 11 — SPF/DKIM/DMARC, homographs
python tests/test_security.py    # 23 — alg=none, tampering, cross-tenant, AEAD
python tests/test_rag.py         # 17 — retrieval, citations, refuses to guess
python tests/test_queries.py     #  7 — named-query loader
python tests/test_anomaly.py     #  9 — fits on benign only (needs scikit-learn)
```

**67 backend tests**, including 23 adversarial security tests. Frontend
type-checks clean (`npm run typecheck`). CI (`.github/workflows/ci.yml`) runs it
all against Postgres 16 + pgvector.

---

*Full design rationale in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · current
status in [`docs/STATUS.md`](docs/STATUS.md) · plain-English overview in
[`docs/OVERVIEW.md`](docs/OVERVIEW.md).*
