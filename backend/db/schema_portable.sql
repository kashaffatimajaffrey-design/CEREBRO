-- =====================================================================
-- CEREBRO v2 — PORTABLE schema (Railway / Supabase / any managed Postgres)
--
-- Identical to schema.sql except it drops the TimescaleDB dependency:
--   hypertables            -> plain tables with BRIN indexes on the time column
--   continuous aggregates  -> materialized views refreshed by a job
--
-- BRIN indexes are the right call here: on append-only, time-ordered data they
-- give most of the benefit of a hypertable partition at a fraction of the index
-- size. At FYP-to-early-product data volumes (millions of rows, not billions)
-- the practical difference from Timescale is negligible.
--
-- Use this file for deployment. Use schema.sql only if you self-host Timescale.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS cerebro;
SET search_path TO cerebro, public;

-- =====================================================================
-- Tenancy & identity
-- =====================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email         citext NOT NULL,
    display_name  text,
    role          text NOT NULL DEFAULT 'analyst'
                  CHECK (role IN ('owner','admin','analyst','viewer')),
    -- scrypt, stored as  scrypt$n$r$p$<salt_b64>$<hash_b64>
    -- Never a plaintext password, unlike v1's authService.ts.
    password_hash text,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,
    UNIQUE (tenant_id, email)
);

CREATE INDEX IF NOT EXISTS users_email ON users (email);

-- Server-side OAuth storage. This table is the fix for v1 keeping a
-- gmail.send-scoped token in browser localStorage.
CREATE TABLE IF NOT EXISTS oauth_credentials (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider       text NOT NULL,
    scopes         text[] NOT NULL DEFAULT '{}',
    access_token   bytea NOT NULL,      -- AES-GCM, app-layer key
    refresh_token  bytea,
    expires_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

CREATE TABLE IF NOT EXISTS sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,   -- sha256 of the refresh token
    user_agent  text,
    ip          inet,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz
);

CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS api_keys (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        text NOT NULL,
    key_hash    text NOT NULL UNIQUE,
    scopes      text[] NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at  timestamptz
);

-- =====================================================================
-- Model registry
-- =====================================================================

CREATE TABLE IF NOT EXISTS model_registry (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name          text NOT NULL,
    version       text NOT NULL,
    task          text NOT NULL CHECK (task IN
                    ('classification','nli','embedding','rerank',
                     'anomaly','forecast','calibration')),
    framework     text,
    artifact_uri  text,
    artifact_sha  text,
    metrics       jsonb NOT NULL DEFAULT '{}'::jsonb,
    trained_at    timestamptz,
    is_active     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_model_per_name
    ON model_registry (name) WHERE is_active;

-- =====================================================================
-- Documents
-- =====================================================================

CREATE TABLE IF NOT EXISTS documents (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('article','email','evidence','report')),
    external_id  text,
    title        text,
    body         text NOT NULL,
    lang         text DEFAULT 'en',
    source_url   text,
    raw_ref      text,
    meta         jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding    vector(768),
    tsv          tsvector GENERATED ALWAYS AS (
                     to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))
                 ) STORED,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, kind, external_id)
);

CREATE INDEX IF NOT EXISTS documents_embedding_hnsw
    ON documents USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS documents_tsv_gin ON documents USING gin (tsv);
CREATE INDEX IF NOT EXISTS documents_tenant_kind ON documents (tenant_id, kind, ingested_at DESC);

-- =====================================================================
-- Misinformation: claims -> evidence -> verdicts
-- =====================================================================

CREATE TABLE IF NOT EXISTS claims (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text         text NOT NULL,
    span_start   int,
    span_end     int,
    check_worthy real,
    embedding    vector(768),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS claims_embedding_hnsw
    ON claims USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS claims_document ON claims (document_id);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain             text NOT NULL UNIQUE,
    publisher          text,
    credibility_weight real NOT NULL DEFAULT 0.5 CHECK (credibility_weight BETWEEN 0 AND 1),
    rationale          text,
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id        uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    document_id     uuid REFERENCES documents(id) ON DELETE SET NULL,
    source_id       uuid REFERENCES evidence_sources(id),
    url             text,
    snippet         text NOT NULL,
    stance          text NOT NULL CHECK (stance IN ('entail','contradict','neutral')),
    nli_score       real NOT NULL,
    retrieval_score real,
    rerank_score    real,
    model_version   uuid REFERENCES model_registry(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS evidence_claim ON evidence (claim_id, rerank_score DESC);

CREATE TABLE IF NOT EXISTS verdicts (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    claim_id              uuid REFERENCES claims(id) ON DELETE CASCADE,
    document_id           uuid REFERENCES documents(id) ON DELETE CASCADE,
    label                 text NOT NULL CHECK (label IN
                            ('supported','refuted','insufficient_evidence','disputed')),
    confidence            real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    calibrated_confidence real CHECK (calibrated_confidence BETWEEN 0 AND 1),
    evidence_count        int NOT NULL DEFAULT 0,
    features              jsonb NOT NULL DEFAULT '{}'::jsonb,
    explanation           text,
    model_version         uuid REFERENCES model_registry(id),
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS verdicts_tenant_time ON verdicts (tenant_id, created_at DESC);

-- =====================================================================
-- Email security
-- =====================================================================

CREATE TABLE IF NOT EXISTS email_analyses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id     uuid REFERENCES documents(id) ON DELETE CASCADE,
    message_id      text,
    from_display    text,
    from_addr       citext,
    from_domain     text,
    reply_to_addr   citext,
    return_path     citext,
    subject         text,
    spf             text CHECK (spf IN ('pass','fail','softfail','neutral','none','temperror','permerror')),
    dkim            text CHECK (dkim IN ('pass','fail','none','temperror','permerror')),
    dkim_domain     text,
    dmarc           text CHECK (dmarc IN ('pass','fail','none')),
    dkim_aligned    boolean,
    features        jsonb NOT NULL DEFAULT '{}'::jsonb,
    indicators      jsonb NOT NULL DEFAULT '[]'::jsonb,
    risk_score      real CHECK (risk_score BETWEEN 0 AND 1),
    calibrated_risk real CHECK (calibrated_risk BETWEEN 0 AND 1),
    -- Explicitly records whether the score came from the transparent heuristic
    -- or a trained model. An unlabeled score is an unaccountable score.
    score_source    text NOT NULL DEFAULT 'heuristic'
                    CHECK (score_source IN ('heuristic','model')),
    verdict         text CHECK (verdict IN ('benign','low_confidence','suspicious','phishing','malicious')),
    explanation     text,
    model_version   uuid REFERENCES model_registry(id),
    analyzed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS email_analyses_tenant_time ON email_analyses (tenant_id, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS email_analyses_from_domain ON email_analyses (from_domain);
CREATE INDEX IF NOT EXISTS email_analyses_verdict ON email_analyses (tenant_id, verdict);

CREATE TABLE IF NOT EXISTS email_urls (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id     uuid NOT NULL REFERENCES email_analyses(id) ON DELETE CASCADE,
    url             text NOT NULL,
    domain          text,
    anchor_text     text,
    anchor_mismatch boolean DEFAULT false,
    is_punycode     boolean DEFAULT false,
    homograph_of    text,
    lookalike_brand text,
    domain_age_days int,
    is_shortener    boolean DEFAULT false,
    expanded_url    text
);

CREATE INDEX IF NOT EXISTS email_urls_analysis ON email_urls (analysis_id);

-- =====================================================================
-- Network telemetry.  BRIN instead of a hypertable.
-- =====================================================================

CREATE TABLE IF NOT EXISTS network_flows (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts          timestamptz NOT NULL,
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sensor      text,
    src_ip      inet NOT NULL,
    dst_ip      inet NOT NULL,
    src_port    int,
    dst_port    int,
    protocol    text,
    duration_ms double precision,
    fwd_packets bigint,
    bwd_packets bigint,
    fwd_bytes   bigint,
    bwd_bytes   bigint,
    features    jsonb NOT NULL DEFAULT '{}'::jsonb,
    label       text
);

-- BRIN: tiny index, excellent on naturally time-ordered append-only data.
CREATE INDEX IF NOT EXISTS network_flows_ts_brin ON network_flows USING brin (ts);
CREATE INDEX IF NOT EXISTS network_flows_tenant_ts ON network_flows (tenant_id, ts DESC);
CREATE INDEX IF NOT EXISTS network_flows_src ON network_flows (src_ip, ts DESC);

CREATE TABLE IF NOT EXISTS anomalies (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    flow_id             uuid REFERENCES network_flows(id) ON DELETE CASCADE,
    incident_id         uuid,
    method              text NOT NULL CHECK (method IN
                          ('isolation_forest','autoencoder','dbscan','ensemble')),
    score               real NOT NULL,
    threshold           real NOT NULL,
    feature_attribution jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_version       uuid REFERENCES model_registry(id),
    detected_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS anomalies_tenant_time ON anomalies (tenant_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS anomalies_incident ON anomalies (incident_id);

CREATE TABLE IF NOT EXISTS incidents (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    kind         text NOT NULL,
    severity     text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    entity_count int NOT NULL DEFAULT 1,
    entities     jsonb NOT NULL DEFAULT '{}'::jsonb,
    narrative    text,
    status       text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open','investigating','resolved','false_positive')),
    opened_at    timestamptz NOT NULL DEFAULT now(),
    closed_at    timestamptz
);

CREATE INDEX IF NOT EXISTS incidents_tenant_status ON incidents (tenant_id, status, opened_at DESC);

-- =====================================================================
-- Unified detection stream — what the dashboard reads and TFT consumes
-- =====================================================================

CREATE TABLE IF NOT EXISTS detections (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts            timestamptz NOT NULL DEFAULT now(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    module        text NOT NULL CHECK (module IN ('news','email','network')),
    threat_type   text NOT NULL,
    risk_score    real NOT NULL CHECK (risk_score BETWEEN 0 AND 1),
    ref_id        uuid,
    summary       text,
    model_version uuid REFERENCES model_registry(id)
);

CREATE INDEX IF NOT EXISTS detections_ts_brin ON detections USING brin (ts);
CREATE INDEX IF NOT EXISTS detections_tenant_ts ON detections (tenant_id, ts DESC);
CREATE INDEX IF NOT EXISTS detections_module ON detections (tenant_id, module, ts DESC);

-- Materialized view replacing the Timescale continuous aggregate.
-- Refresh from the API worker: SELECT cerebro.refresh_threat_volume();
CREATE MATERIALIZED VIEW IF NOT EXISTS threat_volume_hourly AS
SELECT date_trunc('hour', ts)  AS bucket,
       tenant_id,
       module,
       threat_type,
       count(*)                AS n,
       avg(risk_score)::real   AS avg_risk,
       max(risk_score)::real   AS max_risk
FROM detections
GROUP BY 1, 2, 3, 4;

-- CONCURRENTLY requires a unique index; this makes refreshes non-blocking,
-- so the dashboard never reads a half-built view.
CREATE UNIQUE INDEX IF NOT EXISTS threat_volume_hourly_key
    ON threat_volume_hourly (bucket, tenant_id, module, threat_type);

CREATE OR REPLACE FUNCTION refresh_threat_volume() RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY cerebro.threat_volume_hourly;
EXCEPTION WHEN OTHERS THEN
    -- CONCURRENTLY fails if the view has never been populated. Fall back once.
    REFRESH MATERIALIZED VIEW cerebro.threat_volume_hourly;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- Forecasting
-- =====================================================================

CREATE TABLE IF NOT EXISTS forecasts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    series        text NOT NULL,
    issued_at     timestamptz NOT NULL DEFAULT now(),
    horizon_ts    timestamptz NOT NULL,
    p10 real, p50 real, p90 real,
    attribution   jsonb NOT NULL DEFAULT '{}'::jsonb,
    model_version uuid REFERENCES model_registry(id),
    UNIQUE (tenant_id, series, issued_at, horizon_ts)
);

CREATE INDEX IF NOT EXISTS forecasts_lookup ON forecasts (tenant_id, series, horizon_ts);

-- =====================================================================
-- Analyst feedback — the training data flywheel
-- =====================================================================

CREATE TABLE IF NOT EXISTS analyst_feedback (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id          uuid REFERENCES users(id) ON DELETE SET NULL,
    subject_kind     text NOT NULL CHECK (subject_kind IN ('verdict','email','anomaly','incident')),
    subject_id       uuid NOT NULL,
    model_label      text NOT NULL,
    analyst_label    text NOT NULL,
    note             text,
    used_in_training uuid REFERENCES model_registry(id),
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feedback_untrained ON analyst_feedback (subject_kind, created_at)
    WHERE used_in_training IS NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts         timestamptz NOT NULL DEFAULT now(),
    tenant_id  uuid,
    user_id    uuid,
    action     text NOT NULL,
    subject    text,
    subject_id uuid,
    ip         inet,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_log_ts_brin ON audit_log USING brin (ts);
CREATE INDEX IF NOT EXISTS audit_log_tenant ON audit_log (tenant_id, ts DESC);

-- =====================================================================
-- REAL-TIME.  Postgres NOTIFY on every detection.
--
-- This is what makes the dashboard live rather than polled. The API holds one
-- LISTEN connection, receives the payload the instant a row commits, and fans
-- it out to browsers over WebSocket.
--
-- NOTIFY payloads are capped at 8000 bytes, so we send identifiers and let the
-- client fetch detail if it needs it — never the full record.
-- =====================================================================

CREATE OR REPLACE FUNCTION notify_detection() RETURNS trigger AS $$
DECLARE
    payload json;
BEGIN
    payload := json_build_object(
        'event',       'detection',
        'id',          NEW.id,
        'tenant_id',   NEW.tenant_id,
        'module',      NEW.module,
        'threat_type', NEW.threat_type,
        'risk_score',  NEW.risk_score,
        'ref_id',      NEW.ref_id,
        'summary',     left(coalesce(NEW.summary, ''), 200),
        'ts',          NEW.ts
    );
    PERFORM pg_notify('cerebro_events', payload::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS detections_notify ON detections;
CREATE TRIGGER detections_notify
    AFTER INSERT ON detections
    FOR EACH ROW EXECUTE FUNCTION notify_detection();

CREATE OR REPLACE FUNCTION notify_incident() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('cerebro_events', json_build_object(
        'event',        'incident',
        'id',           NEW.id,
        'tenant_id',    NEW.tenant_id,
        'kind',         NEW.kind,
        'severity',     NEW.severity,
        'entity_count', NEW.entity_count,
        'status',       NEW.status
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS incidents_notify ON incidents;
CREATE TRIGGER incidents_notify
    AFTER INSERT OR UPDATE OF status, severity ON incidents
    FOR EACH ROW EXECUTE FUNCTION notify_incident();

-- =====================================================================
-- Row-level security
-- =====================================================================

ALTER TABLE documents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE verdicts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_analyses   ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomalies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecasts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyst_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE detections       ENABLE ROW LEVEL SECURITY;
ALTER TABLE network_flows    ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['documents','verdicts','email_analyses','anomalies',
                             'incidents','forecasts','analyst_feedback',
                             'detections','network_flows']
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON cerebro.%I; '
            'CREATE POLICY tenant_isolation ON cerebro.%I '
            'USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', t, t);
    END LOOP;
END $$;

-- =====================================================================
-- Seed
-- =====================================================================

INSERT INTO evidence_sources (domain, publisher, credibility_weight, rationale) VALUES
    ('reuters.com',    'Reuters',          0.95, 'Wire service, published corrections policy'),
    ('apnews.com',     'Associated Press', 0.95, 'Wire service, published corrections policy'),
    ('bbc.co.uk',      'BBC',              0.90, 'Public broadcaster, published editorial standards'),
    ('snopes.com',     'Snopes',           0.88, 'IFCN signatory fact-checker'),
    ('politifact.com', 'PolitiFact',       0.88, 'IFCN signatory fact-checker'),
    ('factcheck.org',  'FactCheck.org',    0.88, 'IFCN signatory fact-checker'),
    ('wikipedia.org',  'Wikipedia',        0.70, 'Crowd-sourced; broad coverage, variable per-article rigor')
ON CONFLICT (domain) DO NOTHING;
