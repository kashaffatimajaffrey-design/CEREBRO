// CEREBRO API client.
//
// Renamed from geminiService.ts: it no longer talks to Gemini. Detection is
// performed by the FastAPI backend (deterministic features + fitted models);
// this module just calls it. Requests go to the `/v1` namespace, which the Vite
// dev server proxies to the API (see vite.config.ts) so httpOnly session cookies
// work the same in dev and prod. `VITE_API_BASE` overrides the origin in builds
// that call a remote API directly.
import { NewsAnalysisResult, CyberAnalysisResult, NetworkLog, ThreatLevel } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include", // send the httpOnly session cookie
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errText = await response.text();
    let detail: string | undefined;
    try {
      const parsed = JSON.parse(errText);
      // FastAPI puts human-readable errors in `detail`; our 500 handler uses `message`.
      detail = parsed?.detail || parsed?.message || parsed?.error;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `Analysis failed: ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export const analyzeNewsText = async (text: string): Promise<NewsAnalysisResult> => {
  if (!text) throw new Error("Text is required for analysis");
  return postJSON<NewsAnalysisResult>("/v1/analyze/news", { text });
};

export const analyzeNetworkLogs = async (logs: NetworkLog[]): Promise<CyberAnalysisResult> => {
  const parsed = await postJSON<any>("/v1/analyze/flows", { logs });

  // Map the backend's string threat level onto the enum the UI renders.
  let level = ThreatLevel.LOW;
  const incoming = parsed.threatLevel?.toUpperCase();
  if (incoming === "CRITICAL") level = ThreatLevel.CRITICAL;
  else if (incoming === "HIGH") level = ThreatLevel.HIGH;
  else if (incoming === "MEDIUM") level = ThreatLevel.MEDIUM;
  else if (incoming === "SAFE") level = ThreatLevel.SAFE;

  return { ...parsed, threatLevel: level } as CyberAnalysisResult;
};
