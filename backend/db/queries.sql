-- =====================================================================
-- CEREBRO v2 — dashboard and metrics queries
--
-- These are the queries that replace v1's hardcoded `threatData` array and
-- its `1284 + realScansCount` padding. Every number the dashboard shows comes
-- from one of these.
--
-- Kept in .sql rather than embedded in Python so they can be EXPLAIN'd,
-- profiled, and reviewed independently of the application. Each is named and
-- loaded by services/api/core/queries.py.
--
-- Convention: $1 = tenant_id, then positional params in the order listed.
-- =====================================================================


-- name: summary
-- params: $1 tenant_id, $2 window_hours
-- Replaces the padded stat cards. A new tenant genuinely gets zeros — the
-- COALESCE floors are 0, not 1284.
SELECT
    COALESCE(SUM(1)                                            , 0)::int   AS total_detections,
    COALESCE(SUM((module = 'email')::int)                      , 0)::int   AS email_detections,
    COALESCE(SUM((module = 'news')::int)                       , 0)::int   AS news_detections,
    COALESCE(SUM((module = 'network')::int)                    , 0)::int   AS network_detections,
    COALESCE(SUM((risk_score >= 0.85)::int)                    , 0)::int   AS critical_count,
    COALESCE(SUM((risk_score >= 0.55 AND risk_score < 0.85)::int), 0)::int AS suspicious_count,
    COALESCE(ROUND(AVG(risk_score)::numeric, 4)                , 0)        AS avg_risk,
    MAX(ts)                                                                AS last_detection_at
FROM cerebro.detections
WHERE tenant_id = $1
  AND ts >= now() - ($2 || ' hours')::interval;


-- name: summary_delta
-- params: $1 tenant_id, $2 window_hours
-- Real period-over-period change. v1 computed `realScansCount / 1284`, which
-- is a ratio against a fabricated constant, not a change rate.
WITH current_window AS (
    SELECT count(*)::int AS n FROM cerebro.detections
    WHERE tenant_id = $1 AND ts >= now() - ($2 || ' hours')::interval
),
previous_window AS (
    SELECT count(*)::int AS n FROM cerebro.detections
    WHERE tenant_id = $1
      AND ts >= now() - ($2 || ' hours')::interval * 2
      AND ts <  now() - ($2 || ' hours')::interval
)
SELECT c.n AS current_count,
       p.n AS previous_count,
       CASE WHEN p.n = 0 THEN NULL
            ELSE ROUND(((c.n - p.n)::numeric / p.n) * 100, 1)
       END AS pct_change
FROM current_window c CROSS JOIN previous_window p;


-- name: threat_volume
-- params: $1 tenant_id, $2 days
-- Feeds the main dashboard chart. generate_series guarantees a continuous
-- x-axis: hours with no detections come back as 0 rather than being missing,
-- which is what stops the chart from silently misrepresenting a quiet period.
WITH buckets AS (
    SELECT generate_series(
        date_trunc('hour', now()) - ($2 || ' days')::interval,
        date_trunc('hour', now()),
        '1 hour'::interval
    ) AS bucket
),
observed AS (
    SELECT date_trunc('hour', ts) AS bucket,
           module,
           count(*)::int          AS n,
           avg(risk_score)::real  AS avg_risk
    FROM cerebro.detections
    WHERE tenant_id = $1
      AND ts >= date_trunc('hour', now()) - ($2 || ' days')::interval
    GROUP BY 1, 2
)
SELECT b.bucket,
       COALESCE(SUM(o.n)                                  , 0)::int  AS total,
       COALESCE(SUM(o.n) FILTER (WHERE o.module='email')  , 0)::int  AS email,
       COALESCE(SUM(o.n) FILTER (WHERE o.module='news')   , 0)::int  AS news,
       COALESCE(SUM(o.n) FILTER (WHERE o.module='network'), 0)::int  AS network,
       COALESCE(ROUND(AVG(o.avg_risk)::numeric, 4)        , 0)       AS avg_risk
FROM buckets b
LEFT JOIN observed o ON o.bucket = b.bucket
GROUP BY b.bucket
ORDER BY b.bucket;


-- name: detection_rates
-- params: $1 tenant_id, $2 days
-- Replaces the "DETECTION EFFICIENCY RATIO" bar chart, which read from the
-- same hardcoded array as the area chart above it.
SELECT module,
       count(*)::int                                          AS total,
       COALESCE(SUM((risk_score >= 0.85)::int), 0)::int        AS critical,
       COALESCE(SUM((risk_score >= 0.55 AND risk_score < 0.85)::int), 0)::int AS suspicious,
       COALESCE(SUM((risk_score < 0.55)::int), 0)::int         AS benign,
       ROUND(AVG(risk_score)::numeric, 4)                      AS avg_risk
FROM cerebro.detections
WHERE tenant_id = $1
  AND ts >= now() - ($2 || ' days')::interval
GROUP BY module
ORDER BY total DESC;


-- name: recent_detections
-- params: $1 tenant_id, $2 limit, $3 module_filter (NULL = all)
SELECT d.id, d.ts, d.module, d.threat_type, d.risk_score, d.ref_id, d.summary,
       m.name AS model_name, m.version AS model_version
FROM cerebro.detections d
LEFT JOIN cerebro.model_registry m ON m.id = d.model_version
WHERE d.tenant_id = $1
  AND ($3::text IS NULL OR d.module = $3)
ORDER BY d.ts DESC
LIMIT $2;


-- name: top_threat_domains
-- params: $1 tenant_id, $2 days, $3 limit
-- Operationally useful: which senders are actually attacking this tenant.
SELECT from_domain,
       count(*)::int                    AS attempts,
       ROUND(AVG(risk_score)::numeric,4) AS avg_risk,
       MAX(analyzed_at)                 AS last_seen,
       COALESCE(SUM((verdict = 'phishing')::int), 0)::int AS phishing_count
FROM cerebro.email_analyses
WHERE tenant_id = $1
  AND from_domain IS NOT NULL
  AND analyzed_at >= now() - ($2 || ' days')::interval
  AND risk_score >= 0.55
GROUP BY from_domain
ORDER BY attempts DESC, avg_risk DESC
LIMIT $3;


-- name: auth_failure_breakdown
-- params: $1 tenant_id, $2 days
-- Genuine security telemetry, only possible because v2 parses real headers.
-- v1 could not produce this at all — it never saw a header.
SELECT
    count(*)::int                                                     AS analyzed,
    COALESCE(SUM((spf  = 'pass')::int), 0)::int                       AS spf_pass,
    COALESCE(SUM((spf IN ('fail','softfail'))::int), 0)::int          AS spf_fail,
    COALESCE(SUM((dkim = 'pass')::int), 0)::int                       AS dkim_pass,
    COALESCE(SUM((dkim = 'fail')::int), 0)::int                       AS dkim_fail,
    COALESCE(SUM((dmarc = 'pass')::int), 0)::int                      AS dmarc_pass,
    COALESCE(SUM((dmarc = 'fail')::int), 0)::int                      AS dmarc_fail,
    COALESCE(SUM((dkim_aligned IS FALSE)::int), 0)::int               AS dkim_misaligned
FROM cerebro.email_analyses
WHERE tenant_id = $1
  AND analyzed_at >= now() - ($2 || ' days')::interval;


-- name: open_incidents
-- params: $1 tenant_id
SELECT i.id, i.kind, i.severity, i.entity_count, i.status, i.opened_at, i.narrative,
       count(a.id)::int AS anomaly_count
FROM cerebro.incidents i
LEFT JOIN cerebro.anomalies a ON a.incident_id = i.id
WHERE i.tenant_id = $1
  AND i.status IN ('open','investigating')
GROUP BY i.id
ORDER BY
    CASE i.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 ELSE 3 END,
    i.opened_at DESC;


-- name: forecast_series
-- params: $1 tenant_id, $2 series
-- Returns only the most recent forecast run, so the chart never mixes
-- horizons issued at different times.
SELECT horizon_ts, p10, p50, p90, attribution, issued_at
FROM cerebro.forecasts
WHERE tenant_id = $1
  AND series = $2
  AND issued_at = (
      SELECT MAX(issued_at) FROM cerebro.forecasts
      WHERE tenant_id = $1 AND series = $2
  )
ORDER BY horizon_ts;


-- name: model_versions_active
-- Every active model with its published metrics. This is what the UI shows on
-- an "about this analysis" panel, and what makes a verdict auditable.
SELECT name, version, task, framework, metrics, trained_at
FROM cerebro.model_registry
WHERE is_active
ORDER BY task, name;


-- name: feedback_training_set
-- params: $1 subject_kind, $2 limit
-- The flywheel: analyst corrections not yet folded into a training run.
SELECT f.id, f.subject_kind, f.subject_id, f.model_label, f.analyst_label,
       f.note, f.created_at
FROM cerebro.analyst_feedback f
WHERE f.subject_kind = $1
  AND f.used_in_training IS NULL
ORDER BY f.created_at
LIMIT $2;
