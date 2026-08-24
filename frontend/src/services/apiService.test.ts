import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test/msw-handlers';
import { setToken, clearToken } from './session';
import { analyzeNewsText } from './apiService';

describe('apiService', () => {
  it('returns a parsed news result', async () => {
    clearToken();
    const r = await analyzeNewsText('the earth is flat');
    expect(r.verdict).toBe('Misleading');
    expect(r.credibilityScore).toBe(26);
  });

  it('surfaces a readable error on failure', async () => {
    server.use(
      http.post('*/v1/analyze/news', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    await expect(analyzeNewsText('x')).rejects.toThrow(/boom/);
  });

  // Regression: the bearer token must be sent (the iOS/mobile cookie fix).
  it('sends the Authorization bearer header when logged in', async () => {
    let seen: string | null = 'MISSING';
    server.use(
      http.post('*/v1/analyze/news', ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json({
          credibilityScore: 50,
          verdict: 'Unverified',
          summary: '',
          reasoning: '',
          sources: [],
          claims_checked: 0,
          model_versions: {},
          score_source: 'heuristic',
        });
      }),
    );
    setToken('abc.def.ghi');
    await analyzeNewsText('anything');
    expect(seen).toBe('Bearer abc.def.ghi');
    clearToken();
  });
});
