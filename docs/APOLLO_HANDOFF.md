# APOLLO — Build Handoff & Integration Brief

*Paste this into your first Apollo session. It contains everything about CEREBRO
(the system Apollo integrates with), all the live links, the database, and the
exact how/where/why of integration — so you can start Apollo from scratch with
full context.*

---

## 0. TL;DR — start here

- **Apollo** = the predictive brain: a **TFT (Temporal Fusion Transformer) +
  RoBERTa + unsupervised** system that *forecasts and classifies* threats.
- **CEREBRO** (already built & deployed) = the **sensory / feature layer** that
  ingests text + telemetry, extracts real features, scores them, and **stores
  everything in Postgres**. It is Apollo's data source.
- Apollo's fastest start: **read CEREBRO's Postgres** (`cerebro.detections` for
  the time-series TFT forecasts on; `cerebro.email_analyses` for classifier
  training data), train models, write results back to `cerebro.forecasts` and
  `cerebro.model_registry`.
- **Do NOT rebuild what CEREBRO already does** (feature extraction, ingestion API,
  auth, storage). Apollo is the modeling layer on top.

---

## 1. Live links & credentials (CEREBRO, running now)

| What | Where |
|---|---|
| **Live app** | https://cerebro-sandy-beta.vercel.app |
| **Backend API + docs** | https://cerebro-api-nmah.onrender.com/docs |
| **Health / readiness** | `/health` · `/ready` on the API host |
| **GitHub repo (source of truth)** | https://github.com/kashaffatimajaffrey-design/CEREBRO |
| **Demo login** | `demo@cerebro.app` / `cerebro-demo-2026` (or SIGN_UP) |
| **Frontend host** | Vercel — project `cerebro`, root dir `frontend`, env `VITE_API_BASE` |
| **Backend host** | Render — service `cerebro-api` (Docker), blueprint `render.yaml` |
| **Database** | Render — `cerebro-db`, Postgres 16 + pgvector. Connection string: Render → `cerebro-db` → **Connect** |

> Free-tier note: the Render backend sleeps after ~15 min idle (first request ~50s).
> Auth uses a Bearer token (works on iOS/mobile; cross-site cookies are blocked there).

**Secrets currently set on Render** (`cerebro-api` → Environment): `DATABASE_URL`,
`SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `FACT_CHECK_API_KEY`, `AUTO_APPLY_SCHEMA=true`,
`SEED_DEMO_USER=true`, `SESSION_COOKIE_SAMESITE=none`, `CORS_ORIGINS`, `ENVIRONMENT=production`.

---

## 2. What CEREBRO is (and everything that was built)

**One rule:** *deterministic code and trained models decide; the LLM only explains.*
Every verdict is measurable, reproducible, auditable, and runs locally.

### Backend (FastAPI, `backend/`)
- **API layer** (`services/api/`): routers for `auth`, `email`, `news`, `network`,
  `metrics`, `flows`, `stream` (WebSocket), `forecast`, `health`.
- **DB layer** (`core/db.py`): asyncpg pool, per-request **row-level-security**
  tenant scoping (`app.tenant_id`), and a `LISTEN cerebro_events` → WebSocket
  fan-out for realtime. `core/queries.py` loads named SQL from `db/queries.sql`.
- **Auth** (`core/security.py`, `routers/auth.py`): scrypt password hashing,
  stdlib **JWT** (rejects `alg=none`), AES-GCM-encrypted OAuth tokens, login /
  register / me / logout, **Bearer-token sessions** (mobile-safe).
- **Persistence**: every analysis writes to Postgres (`emit_detection` →
  `detections`, plus `email_analyses`). **This is the data collection for Apollo.**
- **ML modules** (`services/ml/`):
  - `email/forensics.py` — ~35 deterministic signals (SPF/DKIM/DMARC + alignment,
    lookalike domains, Unicode homographs, URL analysis). `email/classifier.py` —
    trainable phishing classifier (F1 ~0.97 on SpamAssassin; `scripts/train_email_classifier.py`).
  - `rag/` — hybrid retrieval + NLI stance verification (citations resolve or it
    says "insufficient evidence"). News also uses the **Google Fact Check Tools
    API** (real sources) + a linguistic-credibility heuristic fallback.
  - `anomaly/detector.py` — unsupervised IsolationForest + numpy autoencoder +
    DBSCAN; `fit_matrix`/`score_matrix`; `scripts/train_anomaly.py` (CIC-IDS2017).
  - `forecast/tft.py` — **TFT pipeline scaffold** (this is where Apollo's forecasting
    plugs in) + `scripts/backtest_forecast.py` (validated on real NAB data).
  - `providers/llm.py` — Ollama/Groq/Cerebras/template chain; used ONLY for prose.

### Frontend (React 19 + Vite, `frontend/`)
- Dashboard (live metrics + WebSocket), News scanner (fact-check sources +
  clickable links), Email Forensics scanner, Network monitor, backend-based auth,
  and a live "global threat map" login background (`components/ThreatMap.tsx`).

### Deploy & infra
- `render.yaml` (backend + Postgres one-click), `frontend/vercel.json`,
  `infra/DEPLOY.md`, `deploy/local/Dockerfile.pgvector` (build pgvector on
  restricted networks), `docker-compose.yml` (full local stack).

### Verified
- **67 backend tests** (forensics, security/crypto, RAG, query loader, anomaly),
  incl. 23 adversarial security tests. Frontend type-checks clean. CI in `.github/`.

### Honest gaps (so Apollo doesn't assume they exist)
- No automated ingestion workers (RSS/IMAP/Zeek) — data enters via the API.
- Trained classifiers ship as scripts, not loaded in the live instance.
- TFT forecasting is scaffolded, not producing production forecasts (needs history).

---

## 3. What Apollo is (build this)

A **predictive threat-intelligence core** that consumes CEREBRO's features and:
1. **Forecasts** threat volume (per module) 24–72h ahead with quantile intervals
   (p10/p50/p90) using a **Temporal Fusion Transformer**.
2. **Classifies** with **RoBERTa** heads fine-tuned on the collected/labeled data
   (phishing, misinformation stance) — replacing CEREBRO's heuristic priors.
3. Runs the **unsupervised** anomaly models at scale and clusters incidents.
4. Publishes forecasts + model versions + metrics back to the shared database,
   which CEREBRO's dashboard already reads.

**Boundary:** CEREBRO extracts features and stores events; Apollo learns from them
and predicts. Apollo never re-implements feature extraction — it reads CEREBRO's.

---

## 4. How CEREBRO integrates into Apollo (how / where / why / what)

Apollo connects through **any (or all) of these** — the schema is designed for #1:

**1. Shared Postgres (recommended, zero ETL).**
Apollo reads CEREBRO's tables directly and writes its outputs back.
- *Reads:* `cerebro.detections` (the hourly time-series → TFT input),
  `cerebro.email_analyses` (features + labels → classifier training),
  `cerebro.verdicts`, `cerebro.anomalies`, `cerebro.analyst_feedback`.
- *Writes:* `cerebro.forecasts` (p10/p50/p90 per horizon — the dashboard already
  renders these via `/v1/forecast/{series}`), `cerebro.model_registry`
  (versioned models + metrics, shared by both projects).

**2. Realtime event stream.** `pg_notify('cerebro_events', …)` fires on every
detection. Apollo can subscribe (asyncpg `LISTEN`) for online/streaming features.

**3. REST API.** `POST /v1/analyze/*`, `GET /v1/metrics/*`, `GET /v1/flows/*`,
`WS /v1/stream`, `GET /v1/forecast/{series}`. Good for loose coupling.

**4. Shared `model_registry` table.** Both projects version models the same way
(`name, version, task, framework, artifact_uri, metrics jsonb, is_active`).

**Why this design:** it keeps a clean module boundary (features vs. prediction),
avoids duplicating logic, and means Apollo's forecasts light up CEREBRO's existing
dashboard for free.

---

## 5. The database — what / where / why

**What exists (CEREBRO's, live on Render):** Postgres 16 + pgvector, schema
`cerebro`, applied automatically (`AUTO_APPLY_SCHEMA`). Full DDL:
`backend/db/schema_portable.sql`. Key tables Apollo cares about:

| Table | Columns Apollo uses | Purpose for Apollo |
|---|---|---|
| `detections` | `ts, tenant_id, module, threat_type, risk_score, ref_id, summary` | **TFT input** — aggregate to hourly counts per module |
| `email_analyses` | `from_domain, spf, dkim, dmarc, dkim_aligned, features (jsonb), indicators (jsonb), risk_score, verdict` | **Classifier training data** |
| `verdicts` | `label, confidence, calibrated_confidence, features, model_version` | Misinformation labels + calibration |
| `anomalies` | `score, method, feature_attribution, model_version` | Network model outputs |
| `forecasts` | `series, horizon_ts, p10, p50, p90, model_version` | **Apollo WRITES here** |
| `model_registry` | `name, version, task, metrics, is_active` | **Shared model versioning** |
| `analyst_feedback` | `subject_kind, model_label, analyst_label` | The retrain flywheel (labels) |

**Where Apollo's database should live — recommendation:**
- **Use the same Postgres instance, add an `apollo` schema** (`apollo.*`) for
  Apollo-only tables (training runs, feature snapshots, artifact metadata), while
  reading `cerebro.*` and writing `cerebro.forecasts` / `cerebro.model_registry`.
- This is the original design intent: one DB, separate schemas, one embedding
  space, one model registry. Keep the DB layer vendor-neutral so Neon/Supabase/
  self-host all work.
- For heavy training you'll also want **object storage** (S3/MinIO) for model
  weights — reference them by `artifact_uri` in `model_registry`.

**Why:** no ETL, one source of truth, and CEREBRO's dashboard visualizes Apollo's
forecasts immediately.

**Getting the data now (for training):**
```bash
psql "<cerebro-db connection string from Render>" -c \
  "SELECT date_trunc('hour', ts) h, module, count(*) n, avg(risk_score) r
   FROM cerebro.detections GROUP BY 1,2 ORDER BY 1;"
```

---

## 6. How to start Apollo (concrete first steps)

1. **New repo** `apollo/`. Python (matches CEREBRO's PyTorch stack). Structure:
   `apollo/data` (loaders from cerebro.*), `apollo/models` (tft, roberta,
   anomaly), `apollo/train`, `apollo/eval`, `apollo/serve` (FastAPI or a worker),
   `apollo/registry` (writes model_registry).
2. **Connect to the DB** — reuse CEREBRO's `DATABASE_URL` (read `cerebro.*`).
   Add `CREATE SCHEMA apollo;` for your own tables.
3. **Phase 1 — data + baseline:** build a loader that pulls
   `cerebro.detections` → hourly multivariate series; write a simple baseline
   forecaster; store results in `cerebro.forecasts`. Reuse
   `backend/scripts/backtest_forecast.py` as the eval harness (it already
   backtests on real data).
4. **Phase 2 — TFT:** implement the real `pytorch-forecasting` TFT (CEREBRO's
   `services/ml/forecast/tft.py` is the scaffold/contract). Train once you have
   ≥~2 weeks of `detections` history (or bootstrap on public series to validate).
5. **Phase 3 — RoBERTa heads:** fine-tune on `email_analyses` (phishing) and a
   FEVER/LIAR corpus (misinformation stance); register in `model_registry`; point
   CEREBRO at them via `EMAIL_CLASSIFIER_PATH` so `score_source` flips to `model`.
6. **Phase 4 — unsupervised at scale + incident clustering** using CEREBRO's
   `anomaly/detector.py` fitted on CIC-IDS2017.
7. **Phase 5 — serve:** expose `/predict`, `/forecast`; write forecasts back so
   CEREBRO's dashboard shows them.

---

## 7. Environment / secrets reference (both projects)

```
DATABASE_URL=postgresql://…               # shared Postgres (Render cerebro-db)
SECRET_KEY / TOKEN_ENCRYPTION_KEY         # CEREBRO auth (generate per env)
FACT_CHECK_API_KEY=…                       # Google Fact Check Tools (free)
EMAIL_CLASSIFIER_PATH / ANOMALY_MODEL_PATH # load trained models when ready
AUTO_APPLY_SCHEMA=true  SEED_DEMO_USER=true
CORS_ORIGINS=<frontend url>  SESSION_COOKIE_SAMESITE=none
# Apollo will add: S3/MINIO creds for weights, GPU/training config
```

---

## 8. One-paragraph version (for your report)

> CEREBRO is the sensory and feature-extraction layer: it ingests text and network
> telemetry through an API, extracts real, deterministic features, scores them with
> transparent heuristics and (optionally) trained models, verifies claims against
> real fact-checks, and persists every event to a Postgres database with row-level
> multi-tenant isolation. Apollo is the predictive core built on top: a Temporal
> Fusion Transformer forecasts threat volume, RoBERTa heads classify, and
> unsupervised models detect anomalies — all trained on the features CEREBRO
> collects and all versioned in a shared model registry, with results written back
> so CEREBRO's live dashboard visualizes them. The boundary is clean: CEREBRO sees
> and records; Apollo learns and predicts.
