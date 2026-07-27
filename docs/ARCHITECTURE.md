# CEREBRO v2 — Rebuild Blueprint

**From:** demo-grade React SPA wrapping Gemini prompts
**To:** an evidence-producing threat & misinformation intelligence service, serving as a module of the parent TFT + RoBERTa + unsupervised predictive system

---

## 0. Three honest corrections before we start

These matter because they change *what* we build.

**1. There IS a database — it's just the wrong kind.**
Firestore is a real, production database, and your Firestore rules are the single best-written artifact in the current repo (default-deny, owner-scoped, schema-validated, immutable history). The reason to leave it isn't "no database," it's that Firestore cannot do the four things v2 needs: vector similarity search, relational joins across claims/evidence/verdicts, time-series aggregation for forecasting, and analytical queries over event history. Postgres + pgvector + TimescaleDB does all four in one engine.

**2. Gemini is not a bad API — using an LLM as a classifier is the bad architecture.**
Gemini 2.5 Flash is fast, cheap, and has solid structured output. The actual failures in the current code are architectural, and swapping to Ollama fixes none of them by itself:

- No grounding → "sources" are invented (the server schema literally admits `"simulated references"`)
- LLM-as-classifier → you cannot report precision, recall, F1, or a confusion matrix. **For an FYP defence, this is fatal.** An examiner will ask "what's your accuracy?" and a prompt has no answer.
- Non-reproducible → same input, different output, no seed, no version pin
- Privacy → you are shipping people's inbox contents to a third party

The fix is to stop using a generative model for classification. **RoBERTa classifies. The LLM explains.** That single inversion is the core of this rebuild, and it happens to be exactly what your parent FYP already provides.

**3. Ollama on a laptop is right for one job, wrong for the other.**
Local models give you privacy and zero cost. They also give you ~10–30 tok/s on CPU and weaker structured-output reliability. So: use Ollama for natural-language *explanation generation* from already-computed structured results — a job where latency is tolerable and errors are cosmetic. Do **not** use it for scoring. Scoring is RoBERTa + sklearn, running locally, in milliseconds, with published metrics.

---

## 1. What CEREBRO v2 is

> A service that ingests text and network telemetry, extracts real features, scores them with versioned models, retrieves supporting evidence, and emits calibrated, citable, forecastable threat intelligence.

The word that matters is **evidence**. v1 produced opinions. v2 must produce, for every verdict: the features that drove it, the model version that computed it, the retrieved documents that support it, and a calibrated confidence — including the ability to say *"insufficient evidence."*

That is also the difference between a student project and a product. A product is auditable.

---

## 2. Target architecture

```
┌──────────────────────────────────────────────────────────┐
│  React 19 + Vite frontend  (keep the UI craft, cut lies)  │
│  REST for actions · WebSocket for live events             │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│  FastAPI gateway  ·  auth · RBAC · rate limit · OpenAPI   │
└──┬────────────┬────────────┬─────────────┬───────────────┘
   │            │            │             │
┌──▼──────┐ ┌───▼───────┐ ┌──▼─────────┐ ┌─▼──────────────┐
│ Ingest  │ │ Inference │ │ Retrieval  │ │ Forecast       │
│ workers │ │ RoBERTa   │ │ hybrid RAG │ │ TFT            │
│ RSS·IMAP│ │ IsoForest │ │ pgvector   │ │ threat volume  │
│ Zeek    │ │ AutoEnc   │ │ +BM25+rerank│ │ + intervals    │
└──┬──────┘ └───┬───────┘ └──┬─────────┘ └─┬──────────────┘
   │            │            │             │
┌──▼────────────▼────────────▼─────────────▼───────────────┐
│ Postgres 16 + pgvector + TimescaleDB                      │
│ Redis (queue · cache · pub/sub)   MinIO (raw artifacts)   │
└───────────────────────────────────────────────────────────┘
```

### Why Python replaces Express

Your parent FYP is PyTorch (RoBERTa, TFT). Serving PyTorch from Node means a subprocess bridge or a second service and a serialization boundary you'll debug for weeks. One FastAPI service that owns both the API and the models is simpler, faster, and shares the model registry with the parent project directly. **The Express server dies.**

The React frontend stays. The UI craft in this repo is genuinely good — it's the only part worth keeping wholesale.

### Runs on your laptop

Everything above fits in `docker compose up` on a mid-range laptop:

| Service | RAM | Note |
|---|---|---|
| Postgres + pgvector + Timescale | ~500 MB | single container |
| Redis | ~50 MB | |
| MinIO | ~200 MB | S3-compatible, swap for real S3 later |
| FastAPI + models | ~2.5 GB | RoBERTa-base + MiniLM embedder + sklearn, CPU |
| Ollama (optional) | ~5 GB | Llama 3.1 8B Q4, or Qwen2.5 3B at ~2.5 GB |

Training happens on Colab/Kaggle free GPU; you commit the weights and serve them on CPU. Inference on CPU for RoBERTa-base is ~40–80 ms per document — fine.

---

## 3. Module-by-module: how each fake thing becomes real

### 3.1 News verification — the RAG module

**Delete:** the Gemini "credibility score" and its hallucinated source list.

**Build a real pipeline:**

```
article text
  → claim extraction (LLM, local — the one good LLM job)
  → embed each claim (BAAI/bge-base-en-v1.5, 768-dim)
  → hybrid retrieval over evidence corpus
       ├── vector kNN via pgvector HNSW
       └── BM25 via Postgres tsvector/ts_rank
       └── fused by Reciprocal Rank Fusion
  → cross-encoder rerank (ms-marco-MiniLM-L-6-v2), top 50 → top 8
  → NLI stance per (claim, evidence): ENTAIL / CONTRADICT / NEUTRAL
       └── RoBERTa-large-MNLI, optionally fine-tuned on FEVER
  → aggregate: weight each stance by source credibility × rerank score
  → verdict + calibrated confidence + REAL citations with URLs
```

**The evidence corpus** — this is the part that makes it real, and it's free:

| Source | What it gives | Access |
|---|---|---|
| **Google Fact Check Tools API** | ClaimReview records from Snopes, PolitiFact, AFP, Reuters | free API key |
| **GDELT 2.0** | global news event stream, updates every 15 min | free, no key |
| **Wikipedia/DBpedia dump** | background factual grounding | free download |
| **RSS from tier-1 outlets** | Reuters, AP, BBC — fresh ground truth | free |
| **FEVER dataset** | 185k claims with Wikipedia evidence — *for training the NLI head* | free |

**Training + evaluation** (this is what you defend):

- Fine-tune RoBERTa on **LIAR** (12.8k labeled political statements) and **FakeNewsNet** for the classifier head
- Fine-tune the NLI head on **FEVER**
- Report: accuracy, macro-F1, per-class precision/recall, confusion matrix, ROC curve, and a **calibration plot** (reliability diagram + Expected Calibration Error)
- Baseline comparison table: TF-IDF+LogReg → BERT-base → RoBERTa → RoBERTa+RAG. Showing the lift from retrieval *is* your contribution.

**Result:** every verdict now carries clickable, real URLs to documents that actually exist, plus a number you can defend.

---

### 3.2 Network monitor — the unsupervised module

**Delete:** `generateMockLogs()` entirely, including the planted `logs[3].flags = 'SYN_FLOOD'`.

**Real data, two paths:**

*Training/eval (offline):*
- **CIC-IDS2017** — 2.8M labeled flows, 14 attack types, the standard benchmark
- **UNSW-NB15** — 2.5M records, 9 attack families
- **CIC-IDS2018** for generalization testing

*Live capture (on your laptop, legitimately, on your own interface):*
- **Zeek** `conn.log` → structured flow records, or
- **Suricata** EVE JSON → alerts + flows, or
- **scapy/pyshark** direct capture for a demo

**Feature extraction** (per bidirectional flow — these are the CICFlowMeter features, reimplementable in ~200 lines):
- duration, total fwd/bwd packets, total fwd/bwd bytes
- packet length: min/max/mean/std each direction
- inter-arrival time: min/max/mean/std
- TCP flag counts: SYN, FIN, RST, PSH, ACK, URG
- flow bytes/sec, packets/sec, down-up ratio
- active/idle time statistics

**Unsupervised ensemble** — this is your FYP's unsupervised component, made concrete:

| Model | Catches | Why include it |
|---|---|---|
| **Isolation Forest** | point anomalies, fast | strong baseline, trains in seconds |
| **Dense autoencoder** | subtle multivariate deviation via reconstruction error | catches what IF misses; PyTorch, shares infra with RoBERTa/TFT |
| **DBSCAN** on embeddings | coordinated campaigns (many hosts, one pattern) | turns individual alerts into *incidents* |

Score fusion: normalize each to [0,1], weighted average, threshold set by percentile on a clean training window.

**Evaluation:** train on benign-only traffic, test on labeled attacks. Report AUC-ROC, precision@k, and detection rate per attack family. Compare against the labeled ground truth CIC-IDS2017 provides. **These are real numbers for your thesis.**

**The LLM's role here:** given the top anomalous flows *and their feature deviations*, generate an analyst-readable incident narrative. It explains; it does not detect.

---

### 3.3 Email security — real forensics

**Delete:** the snippet-only Gemini call and the claim of "header alignment" analysis.

**Extract features that actually exist in the message:**

*Authentication (from `Authentication-Results` and `Received-SPF` headers):*
- SPF pass/fail/softfail/none
- DKIM pass/fail + signing domain
- DMARC pass/fail + policy (none/quarantine/reject)
- **DKIM d= alignment vs. From: domain** — the single strongest phishing signal

*Header forensics:*
- Received-chain hop count, timing gaps, private-IP leakage
- `Reply-To` ≠ `From` domain
- Display name contains a domain different from the actual sender domain (classic spoof)
- `Return-Path` vs `From` mismatch
- Message-ID domain mismatch

*URL analysis:*
- extract all hrefs; compare anchor text domain vs actual href domain
- domain age via **RDAP** (free, no key) — domains < 30 days old are a huge signal
- punycode / IDN homograph detection (`аpple.com` with Cyrillic а)
- Levenshtein distance to a list of commonly-impersonated brands
- URL shortener detection + expansion
- IP-literal URLs, excessive subdomain depth, credential-in-URL

*Content:*
- urgency/threat lexicon density
- attachment types + SHA-256 (hash lookup against known-bad, optional)
- HTML/text ratio, hidden-text detection, invisible tracking pixels

**Classifier:** RoBERTa fine-tuned on public phishing corpora — **Nazario phishing corpus** + **SpamAssassin** + **Enron** (ham) — with the structured features above fed alongside into a gradient-boosted head (LightGBM), then **probability calibration via isotonic regression**.

Why calibration matters: an uncalibrated 0.9 means nothing. A calibrated 0.9 means "9 out of 10 emails scored this way really were phishing." Security teams need that; it's also a strong thesis point.

**Fix the two live bugs while you're in there:**
- The advisory reply currently defaults its recipient to the suspicious sender — you mail your forensic report to the phisher. Default to the *analyst*, never the sender.
- The Gmail access token with `gmail.send` scope lives in `localStorage`. Move to httpOnly cookie or server-side session store; drop `gmail.send` unless the send feature is genuinely required, and drop `gmail.metadata` (redundant with `readonly`).

---

### 3.4 Dashboard — the TFT module

**Delete:** the hardcoded `threatData` array and the `1284 + realScansCount` padding. A new user should see zero, honestly labeled.

**Real time-series:** TimescaleDB continuous aggregates over the actual event tables:

```sql
CREATE MATERIALIZED VIEW threat_volume_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', detected_at) AS bucket,
       tenant_id, threat_type,
       count(*) AS n,
       avg(risk_score) AS avg_risk
FROM detections
GROUP BY bucket, tenant_id, threat_type;
```

**TFT forecasting** — your parent FYP's component, and the thing that makes "predictive" true:

- Input: multivariate hourly series (phishing volume, anomaly count, misinformation verdicts) + known-future covariates (hour-of-day, day-of-week, holiday flags)
- Output: 24–72h ahead forecast with **quantile prediction intervals** (p10/p50/p90)
- Library: `pytorch-forecasting`'s `TemporalFusionTransformer`, trained on ≥ a few weeks of accumulated events
- Bonus: TFT's variable-selection weights and attention give you **interpretability** — "the model weighted last week's phishing surge most heavily" — which is a genuinely strong FYP result

Cold-start honesty: until you have enough history, show "insufficient data for forecast — need N more days." That honesty is more impressive than a fake chart.

**Real-time:** Postgres `LISTEN/NOTIFY` → FastAPI → WebSocket → chart updates on actual events. Now the "REAL-TIME OVERVIEW" label is true.

---

## 4. Data model (Postgres)

Core tables — full DDL in `db/schema.sql`:

```
tenants, users, api_keys                 -- multi-tenant from day one
documents(id, tenant, kind, raw_ref,     -- kind: article|email|log_batch
          text, embedding vector(768),
          tsv tsvector)                  -- hybrid retrieval needs both
claims(id, document_id, text,
       embedding vector(768))
evidence_sources(id, url, publisher,
                 credibility_weight)     -- not all sources are equal
evidence(id, claim_id, source_id,
         snippet, stance, nli_score,
         rerank_score)
verdicts(id, claim_id, label, confidence,
         calibrated_confidence,
         model_version, features jsonb)
network_flows(...)                       -- Timescale hypertable
anomalies(id, flow_id, score, method,
          feature_attribution jsonb)
incidents(id, kind, severity, entities)  -- clustered anomalies
forecasts(id, series, horizon_ts,
          p10, p50, p90, model_version)
model_registry(id, name, version, task,
               metrics jsonb, trained_at)
analyst_feedback(id, verdict_id,
                 analyst_label, note)    -- the data flywheel
audit_log(...)
```

Indexes that matter:
```sql
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
  WITH (m=16, ef_construction=64);
CREATE INDEX ON documents USING gin (tsv);
SELECT create_hypertable('network_flows','ts');
```

**`analyst_feedback` is the most commercially important table in this schema.** Every correction an analyst makes becomes labeled training data. That feedback loop — model → analyst → better model — is what separates a product from a demo, and it's cheap to build now and expensive to retrofit.

**Supabase vs. self-hosted Postgres:** Supabase gives you Postgres + pgvector + auth + storage + realtime in one, with a free tier, and would replace Firebase wholesale with less code. Self-hosted docker-compose gives you TimescaleDB (Supabase doesn't offer it) which you want for the TFT feature pipeline. **Recommendation: self-hosted compose for development, since Timescale matters more than managed convenience here.** Keep the DB layer vendor-neutral (SQLAlchemy) so Supabase remains a one-config-change deployment option.

---

## 5. Model serving strategy

```python
# One interface, three backends. Swap by env var, not by rewrite.
class LLMProvider(Protocol):
    async def complete(self, prompt, schema=None) -> dict: ...

OllamaProvider   # local, private, free, slow      — default
GeminiProvider   # fast, cheap, needs network      — fallback
OpenAIProvider   # if you get credits
```

**Recommended laptop config:**
- Classification: RoBERTa-base, local, CPU, ~50 ms
- Embeddings: `bge-base-en-v1.5`, local, CPU, ~20 ms
- Reranking: `ms-marco-MiniLM-L-6-v2`, local, CPU
- Anomaly: IsolationForest + autoencoder, local, sub-ms
- Forecasting: TFT, local, batch job
- **Explanation only:** Ollama `qwen2.5:7b-instruct` (or `llama3.1:8b`; drop to `qwen2.5:3b` if RAM is tight)

Note what this means: **the product works fully offline with no API key.** That's a real selling point for a security tool — no customer's inbox leaves their infrastructure. Make that a headline feature, not an afterthought.

---

## 6. Integration contract with the parent FYP

Since the parent is a TFT + RoBERTa + unsupervised predictive system, CEREBRO should not be a sibling app — it should be the **data and feature layer** that feeds it.

**Shared:**
- One Postgres instance, separate schemas (`cerebro.*`, `core.*`)
- One `model_registry` table — both projects version models the same way
- One embedding space — text from any module is directly comparable
- One event bus (Redis Streams) — `cerebro.detections` stream consumed by the parent's forecaster

**CEREBRO exposes (versioned, OpenAPI-documented):**

```
POST /v1/analyze/text      → {verdict, confidence, evidence[], model_version}
POST /v1/analyze/email     → {risk, features{}, indicators[], model_version}
POST /v1/analyze/flows     → {anomalies[], incident_id?, model_version}
GET  /v1/forecast/{series} → {horizon[], p10[], p50[], p90[]}
GET  /v1/features/{entity} → feature vector for the parent model
WS   /v1/stream            → live detection events
```

That last one — `/v1/features` — is the real integration point. CEREBRO becomes a **feature store** for the parent predictive system: it turns raw text and telemetry into the engineered features TFT consumes. Frame it that way in your FYP report and the module boundary is clean and defensible.

---

## 7. What gets deleted

| File / code | Why |
|---|---|
| `components/Team.tsx` | Registration numbers + personal Gmails = classroom tell. Also leaks PII into the client bundle. |
| `services/authService.ts` | Dead code storing **plaintext passwords**. One import away from being live. |
| `generateMockLogs()` | Fabricated data with a planted anomaly |
| `const threatData = [...]` | Hardcoded chart data under a "REAL-TIME" label |
| `1284 +`, `142 +`, `89 +` baselines | Inflated vanity metrics |
| `triggerDecryptionSim()` | 5-second fake "quantum decryption" that runs *before* credentials are checked |
| `loadingLogs` fake step logs | "Injecting NLP lexical model tokens…" — unrelated to any request |
| `System Health 98%` | Hardcoded string |
| `SYS_N{random}_SEC` badges | Random fake IDs re-rolled every render |
| `SHA256: {item.id.slice(0,10)}` | Not a hash, it's a doc ID |
| Auth.tsx fake telemetry panel | Static JSX pretending to be a live feed |
| `server.ts` (Express) | Replaced by FastAPI |

**Keep:** the dark tactical aesthetic, the animation quality, the Firestore rules (as a reference for writing RLS policies), the Gmail OAuth flow, the jsPDF export (fix pagination).

**Branding judgement call:** the Omnitrix dial (Ben 10) and the name CEREBRO (X-Men) are charming but they're the loudest "student project" signal after the Team page. The dark SOC aesthetic is genuinely professional — the cartoon references are what undercut it. My recommendation: keep the visual language, drop the franchise references, and either rename or backronym it (e.g. **C**ontextual **E**vidence & **R**isk **E**valuation for **B**ehavioural **R**econnaissance **O**perations — clunky, but you get the idea). Your call; it's cosmetic, and it's the cheapest credibility win available.

---

## 8. Engineering practices that make it a product

The current repo has **no `.git` directory at all** — that's step zero.

| Gap | Fix |
|---|---|
| No version control | `git init`, conventional commits, protected main |
| No tests | pytest + coverage; target 70%+ on the scoring paths |
| No CI | GitHub Actions: lint → typecheck → test → build on every push |
| No migrations | Alembic, versioned, reversible |
| No reproducibility | Docker Compose, pinned deps, seeded RNG |
| No model versioning | MLflow or a plain `model_registry` table + artifact hashes |
| No eval harness | `make eval` → metrics table regenerated from held-out sets |
| No observability | structlog JSON logs + OpenTelemetry traces + Prometheus metrics |
| Secrets in repo | `.env` (gitignored) + a secrets manager for deployment |
| No rate limiting | slowapi / Redis token bucket |
| No API docs | free with FastAPI (`/docs`) |
| No auth on Gmail endpoints | **currently an open mail relay** — session-bind every token |

---

## 9. Build order

Roughly two weeks of focused work each, adjustable:

**Phase 1 — Foundation.** Docker compose, Postgres schema + pgvector, FastAPI skeleton, provider abstraction, `git init`, CI. *Nothing user-visible; everything depends on it.*

**Phase 2 — Email forensics.** Highest real-signal-per-hour: the features are deterministic, need no training data to start, and immediately outperform the current snippet-only call. Ship it, then add the RoBERTa head.

**Phase 3 — RAG verification.** Corpus ingestion (GDELT + Fact Check API), embedding pipeline, hybrid retrieval, reranker, NLI stance. The biggest credibility jump — real citations replace invented ones.

**Phase 4 — Unsupervised anomaly detection.** CIC-IDS2017 offline training + Zeek live ingest. Publishable metrics.

**Phase 5 — TFT forecasting + real-time dashboard.** Needs accumulated history from phases 2–4, so it goes last by necessity, not by priority.

**Phase 6 — Hardening.** Calibration, analyst feedback loop, observability, load testing, docs.

Start with Phase 1 and 2 — they're what I'm scaffolding now.

---

## 10. The one-sentence version

Stop asking a language model what it thinks, start extracting features that exist, scoring them with models you can measure, retrieving evidence you can cite, and forecasting from history you actually recorded — and the same code becomes both a defensible FYP and a product with no API key required.
