import { describe, it, expect, beforeEach } from 'vitest';
import { getToken, setToken, clearToken, authHeaders } from './session';

// Regression coverage for the mobile/iOS auth fix: iOS Safari blocks the
// cross-site session cookie, so auth must ride on a bearer token instead.
describe('session token (mobile-safe auth)', () => {
  beforeEach(() => clearToken());

  it('stores and returns the token', () => {
    setToken('t123');
    expect(getToken()).toBe('t123');
  });

  it('authHeaders carries the bearer token when present', () => {
    setToken('t123');
    expect(authHeaders()).toEqual({ Authorization: 'Bearer t123' });
  });

  it('authHeaders is empty when logged out', () => {
    clearToken();
    expect(authHeaders()).toEqual({});
  });

  it('clearToken removes it', () => {
    setToken('t');
    clearToken();
    expect(getToken()).toBe('');
  });
});
