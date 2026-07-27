# CEREBRO

Threat and misinformation intelligence. Every verdict traces to extracted
features, a named model version, and — for misinformation — retrieved evidence
with URLs that resolve to real documents.

Runs entirely on local models. No API key is required.

---

## Layout

```
cerebro/
├── frontend/                 React 19 + Vite SPA
│   ├── src/
│   │   ├── components/       Dashboard, scanners, auth
│   │   ├── context/          Auth state
│   │   ├── services/         API clients
│   │   └── utils/            Web Audio engine
│   ├── index.html
│   ├── vite.config.ts        dev proxy -> backend :8000
│   └── package.json
│
├── backend/                  FastAPI + ML
│   ├── services/
│   │   ├── api/
│   │   │   ├── core/         config, security (scrypt, JWT, AES-GCM)
│   │   │   └── routers/      email, health
│   │   └── ml/
│   │       ├── email/        RFC 5322 forensics        [11 tests]
│   │       ├── anomaly/      IsolationForest + autoencoder + DBSCAN [9 tests]
│   │       ├── rag/          hybrid retrieval + NLI verification    [17 tests]
│   │       ├── providers/    Groq / Cerebras / Ollama / template
│   │       └── forecast/     TFT  (not yet implemented)
│   ├── db/
│   │   ├── schema_portable.sql   USE THIS — plain Postgres + pgvector
│   │   ├── schema.sql            TimescaleDB variant (self-hosted only)
│   │   └── queries.sql           dashboard/metrics queries
│   ├── tests/                60 tests, no network required
│   ├── scripts/startup_check.py  refuses to boot if misconfigured
│   └── Dockerfile
│
├── docs/
│   ├── ARCHITECTURE.md       full design rationale
│   ├── STATUS.md             what works, what doesn't — read this
│   └── FRONTEND_MIGRATION.md what was removed from v1 and why
│
├── infra/                    railway.json, netlify.toml
├── .github/workflows/ci.yml
├── docker-compose.yml
└── Makefile
```

---

## Quick start

```bash
make setup          # creates .env files, prints generated secrets
# paste SECRET_KEY and TOKEN_ENCRYPTION_KEY into backend/.env

make up             # Postgres + pgvector, Redis, MinIO, API
make up PROFILE=llm # ...plus Ollama for local explanations

cd frontend && npm install && npm run dev
```

- API docs — http://localhost:8000/docs
- Frontend — http://localhost:5173
- MinIO console — http://localhost:9001

`make test` runs the backend suite and the frontend type check.

---

## The architectural rule

> **Deterministic code and trained models decide. The language model explains.**

v1 asked Gemini for a `credibilityScore` and a `riskScore`. Those numbers had no
precision, no recall, no confusion matrix, and no reproducibility — indefensible
in a viva and unsellable to a security team.

In v2 the LLM has exactly two jobs, both linguistic rather than evaluative:

1. **Claim extraction** — segment an article into checkable assertions
2. **Explanation** — write up findings that already exist

A consequence worth stating out loud: with the LLM switched off entirely, every
score is identical. `TemplateProvider` guarantees the chain cannot hard-fail. For
a tool that reads people's inboxes, keeping inference local is the point, not a
fallback.

If a `classify()` method ever appears in `services/ml/providers/llm.py`, the
architecture has regressed.

---

## What's verified

Run these yourself — none need network, GPU, or a database. Three of the four
are pure-stdlib; `test_anomaly` needs the pinned `scikit-learn`/`numpy` from
`requirements.txt` (it exercises IsolationForest and DBSCAN), so run it after
`pip install -r requirements.txt`:

```bash
cd backend
python3 tests/test_forensics.py   # 11 — SPF/DKIM/DMARC, homographs        (stdlib only)
python3 tests/test_security.py    # 23 — alg=none, tampering, cross-tenant, AEAD (stdlib only)
python3 tests/test_rag.py         # 17 — retrieval, citations, refuses to guess  (stdlib only)
python3 tests/test_queries.py     #  7 — named-query loader, router coverage (stdlib only)
python3 tests/test_anomaly.py     #  9 — fits on benign only, detects unseen attacks (needs scikit-learn)
```

**Real-time**, verified against live Postgres — a trigger calls `pg_notify` on
commit and a separate connection receives it with no polling:

```
Asynchronous notification "cerebro_events" with payload
{"event":"detection","module":"email","risk_score":0.96,
 "summary":"DKIM misaligned; lookalike sender micros0ft.com"}
```

**Tenant isolation**, verified: tenant A sees its row, tenant B sees its own, a
session with no tenant set sees **zero**. Enforced by Postgres RLS, not
application code.

**RAG**, verified — and the third case is the one that matters:

```
The Boeing 737 MAX was grounded in March 2019  -> SUPPORTED    (reuters.com)
Vaccines contain tracking microchips           -> REFUTED      (snopes.com)
Zorbulon nine hyperdrive quintessence flarn    -> INSUFFICIENT_EVIDENCE
```

A test asserts every citation resolves to a document in the corpus, so a
hallucinated URL fails the build.

---

## Deployment

**Backend → Railway.** Uses `infra/railway.json`. Provision Postgres and enable
pgvector, then apply `backend/db/schema_portable.sql`. Set `SECRET_KEY`,
`TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, `CORS_ORIGINS`, and `GROQ_API_KEY`.

**Frontend → Netlify.** Uses `infra/netlify.toml` (base `frontend/`). Set
`VITE_API_BASE` to the Railway URL.

Three constraints found and worked around:

| Constraint | Resolution |
|---|---|
| TimescaleDB unavailable on Railway | `schema_portable.sql` — BRIN indexes + refreshable materialized view |
| Ollama needs ~5 GB RAM; free tiers give 512 MB | Groq is the default provider; chain is `groq → cerebras → ollama → template` |
| RoBERTa needs ~2.5 GB | ~$5/mo Railway instance, or run the ML service locally behind a Cloudflare Tunnel |

`startup_check.py` runs before uvicorn binds and **refuses to start** on a weak
`SECRET_KEY`, a dev database password, or `CORS_ORIGINS=*` in production. Missing
LLM keys are a warning, not an error.

---

## Before you deploy

1. **`frontend/firebase-applet-config.json` contains placeholders.** The
   original file held a live Firebase apiKey and OAuth client ID. Rotate both in
   the Google console, then fill this in — or drop Firebase entirely once the
   backend auth endpoints land.
2. **`git init`** — v1 was never a git repository.
3. Read **`docs/STATUS.md`** for the honest gap list before demoing.

---

## Known gaps

Stating these is what makes the rest credible.

- **API ↔ database wiring is built (asyncpg).** The session layer
  (`services/api/core/db.py`), the named-query loader (`core/queries.py`), and
  the `/v1/metrics/*`, `/v1/flows/*`, `/v1/stream`, `/v1/auth/*`,
  `/v1/analyze/news` routers are written and wired into `main.py`. Every read is
  tenant-scoped through a per-transaction `app.tenant_id`, so RLS is enforced on
  the connection, not by hand. asyncpg was chosen over the SQLAlchemy ORM because
  `db/queries.sql` uses native `$1,$2` params and the realtime path needs
  `LISTEN/NOTIFY` — both first-class in asyncpg, awkward through the ORM. What is
  *not yet* end-to-end tested is a live run against Postgres from this repo: the
  build sandbox has no PyPI access, so `fastapi`/`asyncpg` can't be installed
  here. The GitHub Actions job (`.github/workflows/ci.yml`) provisions
  `pgvector/pgvector:pg16`, applies the schema, and runs the suite against it —
  that is where the wiring is exercised.
- **Email risk: a trained classifier now exists.** `make datasets` (or
  `python scripts/fetch_datasets.py`) pulls the SpamAssassin corpus and
  `scripts/train_email_classifier.py` fits a calibrated head — held-out
  **F1 0.97, AUC-ROC 0.996**. Set `EMAIL_CLASSIFIER_PATH` and `score_source`
  flips to `"model"`. Until you do, it stays the transparent heuristic prior,
  labeled as such. See `backend/data/README.md`.
- **Anomaly: training pipeline is built** (`fit_matrix`/`score_matrix` +
  `scripts/train_anomaly.py`, a CIC-IDS2017 loader). Fits on benign only, reports
  AUC/precision/recall against labels. Only the dataset download is manual. The
  old synthetic AUC=1.0 was an artifact of easy data — run CIC-IDS2017 for real
  numbers.
- **TFT forecasting: scaffold built, blocked on history.** Pipeline and
  `/v1/forecast/{series}` route exist; training raises `InsufficientHistory`
  until ~2 weeks of hourly detections accumulate, and the API says
  `insufficient_history` rather than inventing a curve.
- **`_registrable_domain` approximates the Public Suffix List.** Install
  `tldextract` before production.
