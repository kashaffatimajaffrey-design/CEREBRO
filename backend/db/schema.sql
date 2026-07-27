-- =====================================================================
-- CEREBRO v2 — core schema
-- Postgres 16 + pgvector + TimescaleDB
--
-- Design principles:
--   1. Every verdict is traceable to features, a model version, and evidence.
--   2. Multi-tenant from day one — retrofitting tenancy is expensive.
--   3. Analyst corrections are first-class data, not an afterthought.
--   4. Text is stored with BOTH an embedding and a tsvector — hybrid
--      retrieval needs lexical and semantic signal.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS cerebro;
SET search_path TO cerebro, public;

-- Embedding dimension. bge-base-en-v1.5 = 768. Change here if you swap models;
-- note that changing it requires re-embedding the corpus.
-- ---------------------------------------------------------------------

-- =====================================================================
-- Tenancy & identity
-- =====================================================================

CREATE TABLE tenants (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email         citext,
    display_name  text,
    role          text NOT NULL DEFAULT 'analyst'
                  CHECK (role IN ('owner','admin','analyst','viewer')),
    password_hash text,                      -- argon2id; NULL when SSO-only
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,
    UNIQUE (tenant_id, email)
);

-- OAuth tokens live server-side, never in the browser.
-- This is the fix for v1's localStorage gmail.send token.
CREATE TABLE oauth_credentials (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider       text NOT NULL,            -- 'google'
    scopes         text[] NOT NULL,
    access_token   bytea NOT NULL,           -- encrypted at rest (app-layer AEAD)
    refresh_token  bytea,
    expires_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

CREATE TABLE api_keys (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        text NOT NULL,
    key_hash    text NOT NULL UNIQUE,        -- sha256 of the presented key
    scopes      text[] NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);

-- =====================================================================
-- Model registry — shared with the parent TFT/RoBERTa project.
-- Nothing may write a verdict without naming the model version that produced it.
-- =====================================================================

CREATE TABLE model_registry (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          text NOT NULL,             -- 'roberta-phish', 'iforest-flows', 'tft-threatvol'
    version       text NOT NULL,             -- semver or git sha
    task          text NOT NULL CHECK (task IN
                    ('classification','nli','embedding','rerank',
                     'anomaly','forecast','calibration')),
    framework     text,                      -- 'pytorch','sklearn','pytorch-forecasting'
    artifact_uri  text,                      -- s3://models/...
    artifact_sha  text,
    metrics       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {"macro_f1":0.91,"auc":0.96,"ece":0.03}
    trained_at    timestamptz,
    is_active     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE UNIQUE INDEX one_active_model_per_name
    ON model_registry (name) WHERE is_active;

-- =====================================================================
-- Documents — the unified text substrate (articles, emails, reports)
-- =====================================================================

CREATE TABLE documents (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('article','email','evidence','report')),
    external_id  text,                       -- gmail message id, GDELT id, url hash
    title        text,
    body         text NOT NULL,
    lang         text DEFAULT 'en',
    source_url   text,
    raw_ref      text,                       -- s3 key for the original .eml / html
    meta         jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding    vector(768),
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))
                 ) STORED,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, kind, external_id)
);

-- Semantic search. HNSW beats IVFFlat for our corpus size and needs no training step.
CREATE INDEX documents_embedding_hnsw
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Lexical search — the other half of hybrid retrieval.
CREATE INDEX documents_tsv_gin ON documents USING gin (tsv);
CREATE INDEX documents_tenant_kind ON documents (tenant_id, kind, ingested_at DESC);

-- =====================================================================
-- Misinformation: claims → evidence → verdicts
-- This replaces v1's single Gemini call that invented its own sources.
-- =====================================================================

CREATE TABLE claims (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text         text NOT NULL,
    span_start   int,
    span_end     int,
    check_worthy real,                       -- 0..1, filters trivia before retrieval
    embedding    vector(768),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX claims_embedding_hnsw
    ON claims USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX claims_document ON claims (document_id);

-- Not all sources deserve equal weight. This is an explicit, auditable
-- input to the verdict — not a hidden constant in application code.
CREATE TABLE evidence_sources (
    id                 uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain             text NOT NULL UNIQUE,
    publisher          text,
    credibility_weight real NOT NULL DEFAULT 0.5
                       CHECK (credibility_weight BETWEEN 0 AND 1),
    rationale          text,                 -- why this weight; auditors will ask
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id      uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    document_id   uuid REFERENCES documents(id) ON DELETE SET NULL,
    source_id     uuid REFERENCES evidence_sources(id),
    url           text,
    snippet       text NOT NULL,
    -- Stance of the evidence toward the claim, from the NLI head.
    stance        text NOT NULL CHECK (stance IN ('entail','contradict','neutral')),
    nli_score     real NOT NULL,
    retrieval_score real,                    -- fused BM25 + vector, pre-rerank
    rerank_score  real,                      -- cross-encoder, post-rerank
    model_version uuid REFERENCES model_registry(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX evidence_claim ON evidence (claim_id, rerank_score DESC);

CREATE TABLE verdicts (
    id                   uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    claim_id             uuid REFERENCES claims(id) ON DELETE CASCADE,
    document_id          uuid REFERENCES documents(id) ON DELETE CASCADE,
    label                text NOT NULL CHECK (label IN
                           ('supported','refuted','insufficient_evidence','disputed')),
    -- Raw model output vs. isotonic-calibrated probability. Keep both:
    -- the gap between them is a reportable result.
    confidence           real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    calibrated_confidence real CHECK (calibrated_confidence BETWEEN 0 AND 1),
    evidence_count       int NOT NULL DEFAULT 0,
    features             jsonb NOT NULL DEFAULT '{}'::jsonb,
    explanation          text,               -- LLM-generated FROM the above, never instead of it
    model_version        uuid REFERENCES model_registry(id),
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX verdicts_tenant_time ON verdicts (tenant_id, created_at DESC);

-- =====================================================================
-- Email security — real header/URL forensics, not snippet vibes
-- =====================================================================

CREATE TABLE email_analyses (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id     uuid REFERENCES documents(id) ON DELETE CASCADE,
    message_id      text,
    from_display    text,
    from_addr       citext,
    from_domain     text,
    reply_to_addr   citext,
    return_path     citext,
    subject         text,
    -- Authentication results, parsed from real headers.
    spf             text CHECK (spf IN ('pass','fail','softfail','neutral','none','temperror','permerror')),
    dkim            text CHECK (dkim IN ('pass','fail','none','temperror','permerror')),
    dkim_domain     text,
    dmarc           text CHECK (dmarc IN ('pass','fail','none')),
    dkim_aligned    boolean,                 -- d= vs From: domain — strongest single signal
    -- Structured feature vector: hop counts, url stats, lexicon hits, domain ages.
    features        jsonb NOT NULL DEFAULT '{}'::jsonb,
    indicators      text[] NOT NULL DEFAULT '{}',
    risk_score      real CHECK (risk_score BETWEEN 0 AND 1),
    calibrated_risk real CHECK (calibrated_risk BETWEEN 0 AND 1),
    verdict         text CHECK (verdict IN ('benign','suspicious','phishing','malicious')),
    model_version   uuid REFERENCES model_registry(id),
    analyzed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX email_analyses_tenant_time ON email_analyses (tenant_id, analyzed_at DESC);
CREATE INDEX email_analyses_from_domain ON email_analyses (from_domain);

CREATE TABLE email_urls (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    analysis_id    uuid NOT NULL REFERENCES email_analyses(id) ON DELETE CASCADE,
    url            text NOT NULL,
    domain         text,
    anchor_text    text,
    anchor_mismatch boolean,                 -- link text claims one domain, href goes elsewhere
    is_punycode    boolean DEFAULT false,
    homograph_of   text,                     -- brand it visually imitates
    levenshtein_to text,                     -- nearest impersonated brand
    domain_age_days int,                     -- via RDAP; <30 is a strong signal
    is_shortener   boolean DEFAULT false,
    expanded_url   text
);

CREATE INDEX email_urls_analysis ON email_urls (analysis_id);

-- =====================================================================
-- Network telemetry — real flows, unsupervised scoring
-- Replaces generateMockLogs() and its planted SYN_FLOOD.
-- =====================================================================

CREATE TABLE network_flows (
    ts              timestamptz NOT NULL,
    id              uuid NOT NULL DEFAULT uuid_generate_v4(),
    tenant_id       uuid NOT NULL,
    sensor          text,                    -- 'zeek','suricata','pcap-import','cicids2017'
    src_ip          inet NOT NULL,
    dst_ip          inet NOT NULL,
    src_port        int,
    dst_port        int,
    protocol        text,
    duration_ms     double precision,
    fwd_packets     bigint,
    bwd_packets     bigint,
    fwd_bytes       bigint,
    bwd_bytes       bigint,
    -- CICFlowMeter-style engineered features; the model's actual input.
    features        jsonb NOT NULL DEFAULT '{}'::jsonb,
    label           text,                    -- ground truth when importing labeled datasets
    PRIMARY KEY (ts, id)
);

SELECT create_hypertable('network_flows', 'ts', if_not_exists => TRUE);
CREATE INDEX network_flows_tenant_ts ON network_flows (tenant_id, ts DESC);
CREATE INDEX network_flows_src ON network_flows (src_ip, ts DESC);

CREATE TABLE anomalies (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    flow_ts         timestamptz NOT NULL,
    flow_id         uuid NOT NULL,
    method          text NOT NULL CHECK (method IN
                      ('isolation_forest','autoencoder','dbscan','ensemble')),
    score           real NOT NULL,           -- normalized 0..1
    threshold       real NOT NULL,           -- what it was compared against, for audit
    -- Which features drove the score. Without this an anomaly is unactionable.
    feature_attribution jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_version   uuid REFERENCES model_registry(id),
    detected_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX anomalies_tenant_time ON anomalies (tenant_id, detected_at DESC);

-- Clustered anomalies become incidents. One SYN flood from 400 hosts
-- is one incident, not 400 alerts.
CREATE TABLE incidents (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind          text NOT NULL,             -- 'ddos','port_scan','exfiltration','phishing_campaign'
    severity      text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    entity_count  int NOT NULL DEFAULT 1,
    entities      jsonb NOT NULL DEFAULT '{}'::jsonb,
    narrative     text,                      -- LLM explanation, generated from the cluster
    status        text NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','investigating','resolved','false_positive')),
    opened_at     timestamptz NOT NULL DEFAULT now(),
    closed_at     timestamptz
);

CREATE INDEX incidents_tenant_status ON incidents (tenant_id, status, opened_at DESC);

-- =====================================================================
-- Unified detection stream — what the dashboard charts and the TFT consumes.
-- Every module writes here. This is the single source of truth for
-- "how many threats, of what kind, when".
-- =====================================================================

CREATE TABLE detections (
    ts            timestamptz NOT NULL DEFAULT now(),
    id            uuid NOT NULL DEFAULT uuid_generate_v4(),
    tenant_id     uuid NOT NULL,
    module        text NOT NULL CHECK (module IN ('news','email','network')),
    threat_type   text NOT NULL,
    risk_score    real NOT NULL CHECK (risk_score BETWEEN 0 AND 1),
    ref_id        uuid,                      -- verdict / email_analysis / anomaly id
    model_version uuid,
    PRIMARY KEY (ts, id)
);

SELECT create_hypertable('detections', 'ts', if_not_exists => TRUE);
CREATE INDEX detections_tenant_ts ON detections (tenant_id, ts DESC);

-- Continuous aggregate: the real replacement for the hardcoded threatData array.
-- Timescale refreshes this incrementally; queries hit precomputed buckets.
CREATE MATERIALIZED VIEW threat_volume_hourly
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', ts)          AS bucket,
       tenant_id,
       module,
       threat_type,
       count(*)                            AS n,
       avg(risk_score)                     AS avg_risk,
       max(risk_score)                     AS max_risk
FROM detections
GROUP BY bucket, tenant_id, module, threat_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('threat_volume_hourly',
    start_offset => INTERVAL '7 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE);

-- =====================================================================
-- Forecasting — TFT output. Quantiles, not point estimates:
-- a security forecast without uncertainty is not actionable.
-- =====================================================================

CREATE TABLE forecasts (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    series        text NOT NULL,             -- 'email.phishing','network.anomaly','news.refuted'
    issued_at     timestamptz NOT NULL DEFAULT now(),
    horizon_ts    timestamptz NOT NULL,
    p10           real,
    p50           real,
    p90           real,
    -- TFT's variable-selection weights — the interpretability story.
    attribution   jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_version uuid REFERENCES model_registry(id),
    UNIQUE (tenant_id, series, issued_at, horizon_ts)
);

CREATE INDEX forecasts_lookup ON forecasts (tenant_id, series, horizon_ts);

-- =====================================================================
-- The data flywheel. Commercially the most valuable table here:
-- every analyst correction is labeled training data for the next model.
-- =====================================================================

CREATE TABLE analyst_feedback (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id        uuid REFERENCES users(id) ON DELETE SET NULL,
    subject_kind   text NOT NULL CHECK (subject_kind IN ('verdict','email','anomaly','incident')),
    subject_id     uuid NOT NULL,
    model_label    text NOT NULL,            -- what the model said
    analyst_label  text NOT NULL,            -- what was actually true
    note           text,
    -- Set once this row has been folded into a training set, so we can
    -- reproduce exactly which examples trained which model version.
    used_in_training uuid REFERENCES model_registry(id),
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX feedback_untrained ON analyst_feedback (subject_kind, created_at)
    WHERE used_in_training IS NULL;

-- =====================================================================
-- Audit log — append-only. Required for any security product.
-- =====================================================================

CREATE TABLE audit_log (
    ts         timestamptz NOT NULL DEFAULT now(),
    id         uuid NOT NULL DEFAULT uuid_generate_v4(),
    tenant_id  uuid,
    user_id    uuid,
    action     text NOT NULL,
    subject    text,
    subject_id uuid,
    ip         inet,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (ts, id)
);

SELECT create_hypertable('audit_log', 'ts', if_not_exists => TRUE);

-- =====================================================================
-- Row-level security. The Firestore rules in v1 were genuinely good;
-- this is the same discipline expressed in Postgres.
-- The app sets:  SET LOCAL app.tenant_id = '<uuid>';
-- =====================================================================

ALTER TABLE documents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE verdicts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_analyses   ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomalies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecasts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyst_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON documents
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON verdicts
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON email_analyses
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON anomalies
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON incidents
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON forecasts
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
CREATE POLICY tenant_isolation ON analyst_feedback
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- =====================================================================
-- Seed: source credibility weights.
-- Explicit and auditable rather than hidden in code.
-- =====================================================================

INSERT INTO evidence_sources (domain, publisher, credibility_weight, rationale) VALUES
    ('reuters.com',    'Reuters',      0.95, 'Wire service, published corrections policy'),
    ('apnews.com',     'Associated Press', 0.95, 'Wire service, published corrections policy'),
    ('bbc.co.uk',      'BBC',          0.90, 'Public broadcaster, editorial standards published'),
    ('snopes.com',     'Snopes',       0.88, 'IFCN signatory fact-checker'),
    ('politifact.com', 'PolitiFact',   0.88, 'IFCN signatory fact-checker'),
    ('factcheck.org',  'FactCheck.org',0.88, 'IFCN signatory fact-checker'),
    ('wikipedia.org',  'Wikipedia',    0.70, 'Crowd-sourced; good coverage, variable per-article rigor')
ON CONFLICT (domain) DO NOTHING;
