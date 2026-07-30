import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { User, HistoryItem } from '../types';

// CEREBRO auth — backed by the FastAPI backend, not Firebase.
//
// Login/register hit /v1/auth/*, which sets an httpOnly session cookie; the token
// never touches JavaScript. Session is restored on load via /v1/auth/me. The
// per-user scan history is kept in localStorage (the backend stays the source of
// truth for detections; this is just the analyst's local log the dashboard shows).
const API_BASE = import.meta.env.VITE_API_BASE ?? '';

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
  addToHistory: (item: HistoryItem) => Promise<void>;
  removeFromHistory: (id: string) => Promise<void>;
  updateUser: (data: { name: string; email: string }) => Promise<void>;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const historyKey = (userId: string) => `cerebro_history_${userId}`;

function loadHistory(userId: string): HistoryItem[] {
  try {
    return JSON.parse(localStorage.getItem(historyKey(userId)) || '[]');
  } catch {
    return [];
  }
}

function saveHistory(userId: string, history: HistoryItem[]) {
  try {
    localStorage.setItem(historyKey(userId), JSON.stringify(history));
  } catch {
    /* storage full / unavailable — non-fatal */
  }
}

async function apiFetch(path: string, options: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include', // send/receive the httpOnly session cookie
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
}

async function extractDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return body.detail[0]?.msg; // pydantic validation
    if (typeof body?.message === 'string') return body.message;
  } catch {
    /* non-JSON */
  }
  return undefined;
}

function friendlyError(status: number, detail?: string): string {
  if (status === 0) {
    return 'NETWORK BLOCKED: could not reach the CEREBRO API. Confirm the backend is deployed and VITE_API_BASE points to it.';
  }
  if (status === 401) return 'AUTHENTICATION FAILED: invalid email or security key.';
  if (status === 409) return detail || 'An account with this email already exists — switch to [ SIGN_IN ].';
  if (status === 422) return detail || 'Invalid input: check the email format and that the key is at least 8 characters.';
  return detail || 'Secure identity handshake disrupted. Please retry.';
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const hydrate = useCallback((profile: any): User => {
    const id: string = profile.user_id || profile.id;
    return {
      id,
      name: profile.display_name || profile.email || 'Analyst',
      email: profile.email || '',
      history: loadHistory(id),
    };
  }, []);

  // Restore an existing session on load (the cookie survives reloads).
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await apiFetch('/v1/auth/me');
        if (res.ok && mounted) {
          setUser(hydrate(await res.json()));
        }
      } catch {
        /* API unreachable — treat as logged out */
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [hydrate]);

  const login = async (email: string, password: string) => {
    let res: Response;
    try {
      res = await apiFetch('/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    } catch {
      throw new Error(friendlyError(0));
    }
    if (!res.ok) throw new Error(friendlyError(res.status, await extractDetail(res)));
    setUser(hydrate(await res.json()));
  };

  const signup = async (name: string, email: string, password: string) => {
    let res: Response;
    try {
      res = await apiFetch('/v1/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, email, password }),
      });
    } catch {
      throw new Error(friendlyError(0));
    }
    if (!res.ok) throw new Error(friendlyError(res.status, await extractDetail(res)));
    setUser(hydrate(await res.json()));
  };

  const loginWithGoogle = async () => {
    throw new Error(
      'Google sign-in is not enabled on this deployment. Use email and password, or the [ SIGN_UP ] tab to register instantly.'
    );
  };

  const logout = async () => {
    try {
      await apiFetch('/v1/auth/logout', { method: 'POST' });
    } catch {
      /* clear locally regardless */
    }
    setUser(null);
  };

  const addToHistory = async (item: HistoryItem) => {
    setUser((prev) => {
      if (!prev) return prev;
      const history = [item, ...prev.history].slice(0, 200);
      saveHistory(prev.id, history);
      return { ...prev, history };
    });
  };

  const removeFromHistory = async (id: string) => {
    setUser((prev) => {
      if (!prev) return prev;
      const history = prev.history.filter((h) => h.id !== id);
      saveHistory(prev.id, history);
      return { ...prev, history };
    });
  };

  const updateUser = async (data: { name: string; email: string }) => {
    // Display name is local for now; email is the account key and is immutable here.
    setUser((prev) => (prev ? { ...prev, name: data.name } : prev));
  };

  return (
    <AuthContext.Provider
      value={{ user, login, signup, loginWithGoogle, logout, addToHistory, removeFromHistory, updateUser, loading }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
