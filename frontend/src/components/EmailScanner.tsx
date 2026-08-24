import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { authHeaders } from '../services/session';
import { playCyberSFX } from '../utils/audio';
import { motion, AnimatePresence } from 'motion/react';
import { ShieldAlert, Mail, RefreshCw, AlertTriangle, CheckCircle2, FileText } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

interface Indicator {
  code: string;
  severity: string;
  weight: number;
  detail: string;
}
interface EmailResult {
  from_display: string | null;
  from_addr: string | null;
  from_domain: string | null;
  subject: string | null;
  spf: string | null;
  dkim: string | null;
  dmarc: string | null;
  dkim_aligned: boolean | null;
  verdict: string;
  risk_score: number;
  score_source: string;
  indicators: Indicator[];
  urls: any[];
  explanation: string | null;
}

const SAMPLE = `From: "PayPal Security" <alert@paypa1.com>
Reply-To: recover@secure-paypa1.ru
To: you@example.com
Subject: Urgent: your account has been limited

Dear customer,

We detected unusual activity. Your account is suspended. Verify your
identity immediately at http://paypa1.com/login-verify or it will be
permanently closed within 24 hours.

PayPal Security Team`;

const SEV: Record<string, string> = {
  critical: 'text-red-400 border-red-500/30 bg-red-500/5',
  high: 'text-orange-400 border-orange-500/30 bg-orange-500/5',
  medium: 'text-amber-400 border-amber-500/30 bg-amber-500/5',
  low: 'text-slate-300 border-slate-700 bg-slate-800/20',
  info: 'text-slate-400 border-slate-800 bg-slate-900/20',
};

export const EmailScanner: React.FC = () => {
  const [raw, setRaw] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<EmailResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { addToHistory } = useAuth();

  const analyze = async () => {
    if (!raw.trim()) return;
    setLoading(true);
    setResult(null);
    setError(null);
    playCyberSFX('scan');
    try {
      const res = await fetch(`${API_BASE}/v1/analyze/email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        credentials: 'include',
        body: JSON.stringify({ raw_message: raw, generate_explanation: false }),
      });
      if (!res.ok) {
        let detail: string | undefined;
        try {
          detail = (await res.json())?.detail;
        } catch {
          /* */
        }
        throw new Error(detail || `Analysis failed (${res.status})`);
      }
      const data: EmailResult = await res.json();
      setResult(data);
      playCyberSFX('success');
      addToHistory({
        id: Math.random().toString(36).slice(2, 11),
        date: new Date().toISOString(),
        type: 'CYBER',
        summary: `${data.verdict.toUpperCase()} — ${data.from_addr || 'unknown sender'}`,
        result:
          data.verdict === 'phishing'
            ? 'Critical'
            : data.verdict === 'suspicious'
              ? 'High'
              : 'Safe',
      });
    } catch (e: any) {
      playCyberSFX('alarm');
      setError(e.message || 'Could not analyze the message.');
    } finally {
      setLoading(false);
    }
  };

  const pct = result ? Math.round(result.risk_score * 100) : 0;
  const riskColor = pct >= 85 ? 'text-red-400' : pct >= 55 ? 'text-amber-400' : 'text-emerald-400';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* header */}
      <div className="flex items-center gap-4 bg-slate-900/30 border border-slate-900 p-5 rounded-xl backdrop-blur-md">
        <div className="p-3 rounded-lg bg-cyan-950/40 border border-cyan-500/25 text-cyan-400">
          <Mail className="w-6 h-6" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white font-mono tracking-wider">
            [ EMAIL FORENSICS ]
          </h2>
          <p className="text-xs text-slate-500 font-mono">
            Paste a full raw email (headers + body). ~35 deterministic signals — SPF/DKIM/DMARC,
            lookalike domains, homographs, URL tricks — no AI guesswork.
          </p>
        </div>
      </div>

      {/* input */}
      <div className="bg-slate-950/70 border border-slate-900 p-6 rounded-xl shadow-2xl backdrop-blur-md">
        <textarea
          className="w-full h-52 bg-slate-950 border border-slate-900 focus:border-cyan-800 focus:ring-1 focus:ring-cyan-900 rounded-lg p-4 text-slate-300 font-mono text-xs outline-none resize-none custom-scrollbar"
          placeholder="Paste raw email source here (From:, Subject:, Received:, body…)"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            onClick={() => {
              setRaw(SAMPLE);
              playCyberSFX('hover');
            }}
            className="text-[10px] font-mono text-slate-500 hover:text-cyan-400 tracking-widest uppercase underline"
          >
            ↳ load sample phishing email
          </button>
          <button
            onClick={analyze}
            disabled={loading || !raw.trim()}
            className={`px-5 py-2.5 rounded-lg text-xs font-bold font-mono tracking-widest uppercase flex items-center gap-2 border transition-all ${
              loading || !raw.trim()
                ? 'bg-slate-900 border-slate-800 text-slate-600 cursor-not-allowed'
                : 'bg-cyan-600/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20 hover:border-cyan-400 cursor-pointer'
            }`}
          >
            {loading ? (
              <>
                <RefreshCw className="h-3.5 w-3.5 animate-spin" /> ANALYZING…
              </>
            ) : (
              'ANALYZE_MESSAGE'
            )}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 font-mono text-xs flex items-center gap-2"
          >
            <AlertTriangle className="w-4 h-4" /> {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* result */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-slate-950/80 border border-slate-900 rounded-xl overflow-hidden shadow-2xl backdrop-blur-md"
          >
            <div className="p-5 border-b border-slate-900/60 bg-slate-950/40 flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                {pct >= 55 ? (
                  <ShieldAlert className="w-7 h-7 text-red-400" />
                ) : (
                  <CheckCircle2 className="w-7 h-7 text-emerald-400" />
                )}
                <div className="font-mono">
                  <div className={`text-lg font-black uppercase tracking-widest ${riskColor}`}>
                    {result.verdict}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    risk {pct}% · source: {result.score_source}
                  </div>
                </div>
              </div>
              <div className="font-mono text-[10px] text-slate-400 space-y-0.5 text-right">
                <div>
                  SPF <span className="text-slate-200">{result.spf || 'n/a'}</span> · DKIM{' '}
                  <span className="text-slate-200">{result.dkim || 'n/a'}</span> · DMARC{' '}
                  <span className="text-slate-200">{result.dmarc || 'n/a'}</span>
                </div>
                <div>
                  DKIM aligned:{' '}
                  <span
                    className={result.dkim_aligned === false ? 'text-red-400' : 'text-slate-200'}
                  >
                    {String(result.dkim_aligned)}
                  </span>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-5 font-mono">
              <div className="text-xs text-slate-400 space-y-1">
                <div>
                  <span className="text-slate-600">FROM:</span> {result.from_display} &lt;
                  {result.from_addr}&gt;
                </div>
                <div>
                  <span className="text-slate-600">DOMAIN:</span> {result.from_domain}
                </div>
                <div>
                  <span className="text-slate-600">SUBJECT:</span> {result.subject}
                </div>
              </div>

              <div>
                <h4 className="text-[10px] uppercase text-slate-500 font-black tracking-widest mb-2 flex items-center gap-1.5">
                  <FileText className="w-3 h-3" /> Indicators ({result.indicators.length})
                </h4>
                {result.indicators.length === 0 ? (
                  <p className="text-xs text-emerald-400/80">No risk indicators found.</p>
                ) : (
                  <div className="space-y-2">
                    {result.indicators.map((ind, i) => (
                      <div
                        key={i}
                        className={`p-3 rounded-lg border text-xs ${SEV[ind.severity] || SEV.info}`}
                      >
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="font-bold tracking-wider">{ind.code}</span>
                          <span className="text-[9px] uppercase opacity-70">
                            {ind.severity} · +{ind.weight.toFixed(2)}
                          </span>
                        </div>
                        <p className="opacity-90 leading-relaxed">{ind.detail}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
