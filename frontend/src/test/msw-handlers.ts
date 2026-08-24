import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

// Mock the CEREBRO API for component/integration tests. Path-prefixed with `*`
// so it matches whatever origin VITE_API_BASE resolves to in the test env.
export const handlers = [
  http.post('*/v1/auth/login', () =>
    HttpResponse.json({
      user_id: 'u1',
      tenant_id: 't1',
      role: 'owner',
      display_name: 'Demo Analyst',
      access_token: 'test.jwt.token',
      token_type: 'bearer',
    }),
  ),
  http.post('*/v1/auth/register', () =>
    HttpResponse.json({
      user_id: 'u2',
      tenant_id: 't2',
      role: 'owner',
      display_name: 'New Analyst',
      access_token: 'test.jwt.token2',
      token_type: 'bearer',
    }),
  ),
  http.post('*/v1/auth/logout', () => HttpResponse.json({ status: 'logged_out' })),
  // Signed-out by default so AuthContext mount resolves to the login screen.
  http.get('*/v1/auth/me', () => new HttpResponse(null, { status: 401 })),

  http.post('*/v1/analyze/email', () =>
    HttpResponse.json({
      from_display: 'PayPal Security',
      from_addr: 'alert@paypa1.com',
      from_domain: 'paypa1.com',
      subject: 'Urgent: verify your account',
      spf: 'fail',
      dkim: 'fail',
      dmarc: 'fail',
      dkim_aligned: false,
      verdict: 'phishing',
      risk_score: 0.91,
      score_source: 'heuristic',
      indicators: [
        {
          code: 'LOOKALIKE_SENDER_DOMAIN',
          severity: 'critical',
          weight: 0.35,
          detail: "Sender domain 'paypa1.com' is 1 character from 'paypal'.",
        },
        { code: 'DMARC_FAIL', severity: 'critical', weight: 0.35, detail: 'DMARC failed.' },
      ],
      features: {},
      urls: [],
      explanation: null,
      model_version: null,
    }),
  ),
  http.post('*/v1/analyze/news', () =>
    HttpResponse.json({
      credibilityScore: 26,
      verdict: 'Misleading',
      summary: 'test claim',
      reasoning: 'heuristic reasoning',
      sources: [],
      claims_checked: 1,
      model_versions: {},
      score_source: 'heuristic',
    }),
  ),
  http.get('*/v1/flows/recent', () =>
    HttpResponse.json({ count: 0, detections: [], flows: [], flows_are_sample: true }),
  ),
  http.post('*/v1/analyze/flows', () =>
    HttpResponse.json({
      threatLevel: 'Critical',
      anomaliesDetected: ['flw-07'],
      analysisReport: 'Heuristic triage: 1 flagged.',
      recommendedAction: 'Isolate.',
      score_source: 'heuristic',
    }),
  ),
  http.get('*/v1/metrics/summary', () =>
    HttpResponse.json({
      total_detections: 0,
      email_detections: 0,
      news_detections: 0,
      network_detections: 0,
      critical_count: 0,
      suspicious_count: 0,
      avg_risk: 0,
      last_detection_at: null,
      window_hours: 168,
      pct_change: null,
    }),
  ),
  http.get('*/v1/metrics/threat-volume', () => HttpResponse.json({ days: 7, buckets: [] })),
  http.get('*/ready', () =>
    HttpResponse.json({
      status: 'ready',
      uptime_seconds: 1,
      capabilities: {
        email_forensics: true,
        database: true,
        llm_explanations: true,
        models_loaded: [],
      },
    }),
  ),
];

export const server = setupServer(...handlers);
