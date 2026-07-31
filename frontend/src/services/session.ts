// Bearer-token session, stored client-side.
//
// The backend also sets an httpOnly session cookie, but cross-site cookies
// (frontend on *.vercel.app, API on *.onrender.com) are blocked by default on
// mobile Safari/Chrome and in-app browsers (WhatsApp, Instagram). So we ALSO
// keep the access token here and send it as `Authorization: Bearer …`, which
// works everywhere. The token is a short-lived JWT; on logout we clear it.
const KEY = 'cerebro_token';

export const getToken = (): string => {
  try { return localStorage.getItem(KEY) || ''; } catch { return ''; }
};

export const setToken = (t: string): void => {
  try { if (t) localStorage.setItem(KEY, t); } catch { /* storage unavailable */ }
};

export const clearToken = (): void => {
  try { localStorage.removeItem(KEY); } catch { /* */ }
};

export const authHeaders = (): Record<string, string> => {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
};
