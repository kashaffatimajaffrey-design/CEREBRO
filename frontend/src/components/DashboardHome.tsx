import React, { useState, useEffect } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from 'recharts';
import { StatCard } from './StatCard';
import { useAuth } from '../context/AuthContext';
import { authHeaders, getToken } from '../services/session';
import { playCyberSFX } from '../utils/audio';
import {
  ShieldAlert,
  Newspaper,
  Search,
  Trash2,
  Clock,
  ChevronDown,
  ChevronUp,
  Filter,
  RefreshCw,
  FileText,
  Activity,
  Zap,
  Globe,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

// threatData removed. It was a hardcoded 7-day array rendered under the label
// "[ THREAT ANALYTICS REAL-TIME OVERVIEW ]". Chart data now comes from
// GET /v1/metrics/threat-volume, backed by a Postgres aggregate over the
// detections table.

interface DashboardHomeProps {
  systemColor?: 'blue' | 'green' | 'purple';
}

export const DashboardHome: React.FC<DashboardHomeProps> = ({ systemColor = 'blue' }) => {
  // --- live metrics ---------------------------------------------------
  // Every number below comes from the backend. There are no seeded baselines:
  // a new tenant genuinely sees zero, which is the honest thing to show.
  const [threatData, setThreatData] = useState<any[]>([]);
  const [summaryDelta, setSummaryDelta] = useState<string | undefined>(undefined);
  const [systemHealth, setSystemHealth] = useState<string>('--');
  const [metricsError, setMetricsError] = useState<string | null>(null);

  const API_BASE = import.meta.env.VITE_API_BASE ?? '';

  const loadMetrics = React.useCallback(async () => {
    try {
      const [volumeRes, summaryRes, readyRes] = await Promise.all([
        fetch(`${API_BASE}/v1/metrics/threat-volume?days=7`, {
          credentials: 'include',
          headers: { ...authHeaders() },
        }),
        fetch(`${API_BASE}/v1/metrics/summary?hours=168`, {
          credentials: 'include',
          headers: { ...authHeaders() },
        }),
        fetch(`${API_BASE}/ready`),
      ]);

      if (volumeRes.ok) {
        const v = await volumeRes.json();
        setThreatData(
          (v.buckets ?? []).map((b: any) => ({
            name: new Date(b.bucket).toLocaleDateString(undefined, {
              weekday: 'short',
              hour: '2-digit',
            }),
            fakeNews: b.news,
            cyberAttacks: b.network,
            phishing: b.email,
          })),
        );
      }

      if (summaryRes.ok) {
        const sum = await summaryRes.json();
        setSummaryDelta(
          sum.pct_change === null || sum.pct_change === undefined
            ? undefined
            : `${sum.pct_change > 0 ? '+' : ''}${sum.pct_change}%`,
        );
      }

      if (readyRes.ok) {
        const r = await readyRes.json();
        const caps = Object.values(r.capabilities ?? {}).filter(
          (c) => typeof c === 'boolean',
        ) as boolean[];
        setSystemHealth(
          caps.length ? `${Math.round((caps.filter(Boolean).length / caps.length) * 100)}%` : '--',
        );
      }
      setMetricsError(null);
    } catch (e: any) {
      setMetricsError(e?.message ?? 'Could not reach the CEREBRO API.');
    }
  }, [API_BASE]);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  // --- live event stream ----------------------------------------------
  // Postgres NOTIFY -> API -> WebSocket. The dashboard updates when a
  // detection actually commits, with no polling.
  useEffect(() => {
    const wsBase = API_BASE.replace(/^http/, 'ws');
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${wsBase}/v1/stream?token=${encodeURIComponent(getToken())}`);
      ws.onmessage = () => loadMetrics();
    } catch {
      /* stream unavailable; the periodic refresh below still applies */
    }
    const poll = setInterval(loadMetrics, 60_000); // fallback only
    return () => {
      ws?.close();
      clearInterval(poll);
    };
  }, [API_BASE, loadMetrics]);

  const { user, removeFromHistory } = useAuth();
  const history = user?.history || [];

  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<'ALL' | 'NEWS' | 'CYBER'>('ALL');
  const [filterRisk, setFilterRisk] = useState<'ALL' | 'HIGH_RISK' | 'SAFE'>('ALL');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Dynamic color palette mapping based on current Omnitrix state
  const colorPalette = {
    blue: {
      primary: '#3b82f6', // Blue-500
      secondary: '#8b5cf6', // Purple-500
      accent: '#06b6d4', // Cyan-500
      bgClass: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
      textClass: 'text-blue-400',
      borderClass: 'border-blue-500/30',
      glow: 'shadow-[0_0_20px_rgba(59,130,246,0.15)]',
      cards: ['blue', 'purple', 'green', 'blue'] as const,
    },
    green: {
      primary: '#10b981', // Emerald-500
      secondary: '#34d399', // Emerald-400
      accent: '#84cc16', // Lime-500
      bgClass: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
      textClass: 'text-emerald-400',
      borderClass: 'border-emerald-500/30',
      glow: 'shadow-[0_0_20px_rgba(16,185,129,0.25)]',
      cards: ['green', 'green', 'green', 'green'] as const,
    },
    purple: {
      primary: '#a855f7', // Purple-500
      secondary: '#ec4899', // Pink-500
      accent: '#ef4444', // Red-500
      bgClass: 'bg-purple-500/10 border-purple-500/20 text-purple-400',
      textClass: 'text-purple-400',
      borderClass: 'border-purple-500/30',
      glow: 'shadow-[0_0_20px_rgba(139,92,246,0.25)]',
      cards: ['purple', 'red', 'purple', 'purple'] as const,
    },
  };

  const palette = colorPalette[systemColor];

  // Parse custom threat level/score to determine risk styles
  const getSeverityStyle = (resultStr: string) => {
    const normalized = resultStr.toLowerCase();

    // Check if result indicates High / Critical risk
    const isHighOrCritical =
      normalized.includes('critical') ||
      normalized.includes('high') ||
      normalized.includes('fake') ||
      normalized.includes('misleading') ||
      (normalized.includes('%') && parseInt(normalized) < 50);

    // Check if result indicates medium/low risk
    const isMediumOrLow =
      normalized.includes('medium') ||
      normalized.includes('low') ||
      normalized.includes('suspicious') ||
      (normalized.includes('%') && parseInt(normalized) >= 50 && parseInt(normalized) < 75);

    if (isHighOrCritical) {
      return {
        badgeBg: 'bg-red-500/10 border-red-500/20 text-red-400',
        dotBg: 'bg-red-500 shadow-sm shadow-red-500/50',
        text: 'text-red-400',
        riskLabel: 'High Risk / Severe Threat',
      };
    } else if (isMediumOrLow) {
      return {
        badgeBg: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
        dotBg: 'bg-amber-500 shadow-sm shadow-amber-500/50',
        text: 'text-amber-400',
        riskLabel: 'Medium / Suspect Risk',
      };
    }

    // Default safe or highly credible outcomes
    return {
      badgeBg: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
      dotBg: 'bg-emerald-500 shadow-sm shadow-emerald-500/50',
      text: 'text-emerald-400',
      riskLabel: 'Low Risk / Safe Credential',
    };
  };

  // Formats UTC ISO string to customized legible forensic timezone log
  const formatTimestamp = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      });
    } catch (e) {
      return isoString;
    }
  };

  // Real-time forensic statistics calculation synced to Firestore state
  const realScansCount = history.length;
  const realFakeNewsCount = history.filter((h) => {
    const norm = h.result.toLowerCase();
    return (
      h.type === 'NEWS' &&
      (norm.includes('fake') ||
        norm.includes('misleading') ||
        (norm.includes('%') && parseInt(norm) < 50))
    );
  }).length;
  const realCyberCount = history.filter((h) => {
    const norm = h.result.toLowerCase();
    return h.type === 'CYBER' && (norm.includes('critical') || norm.includes('high'));
  }).length;

  const totalScansValue = realScansCount.toLocaleString();
  const fakeNewsValue = realFakeNewsCount.toLocaleString();
  const cyberThreatsValue = realCyberCount.toLocaleString();

  // Filters threat logs according to search terms and categories
  const filteredHistory = history.filter((item) => {
    if (filterType !== 'ALL' && item.type !== filterType) return false;

    const style = getSeverityStyle(item.result);
    if (filterRisk === 'HIGH_RISK' && !style.riskLabel.includes('High')) return false;
    if (filterRisk === 'SAFE' && !style.riskLabel.includes('Low')) return false;

    const matchesSearch =
      item.summary.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.result.toLowerCase().includes(searchTerm.toLowerCase()) ||
      item.type.toLowerCase().includes(searchTerm.toLowerCase());

    return matchesSearch;
  });

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!user) return;
    setDeletingId(id);
    playCyberSFX('click');
    try {
      await removeFromHistory(id);
    } catch (err) {
      console.error('Forensic log disruption: failed to remove record', err);
    } finally {
      setDeletingId(null);
    }
  };

  const handleRowClick = (id: string) => {
    playCyberSFX('hover');
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="space-y-6">
      {/* 1. Statistics Cards Deck */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Total Scans"
          value={totalScansValue}
          change={summaryDelta}
          isPositive={true}
          color={palette.cards[0]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
          }
        />
        <StatCard
          title="Fake News Detected"
          value={fakeNewsValue}
          // No fabricated delta. v1 padded this with `/ 142`, a change rate
          // against a made-up constant. We don't fetch a per-category delta, so
          // we show none rather than invent one.
          change={undefined}
          isPositive={false}
          color={palette.cards[1]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          }
        />
        <StatCard
          title="Cyber Threats Blocked"
          value={cyberThreatsValue}
          // Same as above: v1's `/ 89` baseline was fabricated. Show no delta.
          change={undefined}
          isPositive={true}
          color={palette.cards[2]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
              />
            </svg>
          }
        />
        <StatCard
          title="System Health"
          value={systemHealth}
          change={undefined}
          isPositive={true}
          color={palette.cards[3]}
          icon={
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
          }
        />
      </div>

      {/* 2. Graphical Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          className="bg-slate-950/60 border border-slate-900/80 rounded-xl p-6 relative overflow-hidden group shadow-xl backdrop-blur-md"
        >
          {/* Cyber accents inside cards */}
          <div
            className={`absolute top-0 right-0 w-24 h-24 bg-gradient-to-br from-transparent to-slate-900/30 translate-x-12 -translate-y-12 rounded-full blur-xl`}
          />
          <h3 className="text-sm font-bold font-mono tracking-widest text-slate-400 mb-6 flex items-center gap-2">
            <Activity className={`w-4 h-4 ${palette.textClass}`} />[ THREAT ANALYTICS REAL-TIME
            OVERVIEW ]
          </h3>

          <div className="h-80 w-full relative z-10">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={threatData}>
                <defs>
                  <linearGradient id="colorPrimary" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.primary} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={palette.primary} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorSecondary" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={palette.secondary} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={palette.secondary} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="name"
                  stroke="#64748b"
                  style={{ fontSize: 10, fontFamily: 'monospace' }}
                />
                <YAxis stroke="#64748b" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#020617',
                    borderColor: '#1e293b',
                    color: '#f8fafc',
                    borderRadius: 8,
                    fontFamily: 'monospace',
                    fontSize: 11,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11, fontFamily: 'monospace', paddingTop: 10 }} />
                <Area
                  type="monotone"
                  dataKey="fakeNews"
                  stroke={palette.primary}
                  fillOpacity={1}
                  fill="url(#colorPrimary)"
                  name="Misinformation Index"
                  strokeWidth={2}
                />
                <Area
                  type="monotone"
                  dataKey="cyberAttacks"
                  stroke={palette.secondary}
                  fillOpacity={1}
                  fill="url(#colorSecondary)"
                  name="Cyber Penetrations"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          className="bg-slate-950/60 border border-slate-900/80 rounded-xl p-6 relative overflow-hidden group shadow-xl backdrop-blur-md"
        >
          <div
            className={`absolute top-0 right-0 w-24 h-24 bg-gradient-to-br from-transparent to-slate-900/30 translate-x-12 -translate-y-12 rounded-full blur-xl`}
          />
          <h3 className="text-sm font-bold font-mono tracking-widest text-slate-400 mb-6 flex items-center gap-2">
            <Globe className={`w-4 h-4 ${palette.textClass}`} />[ DETECTION EFFICIENCY RATIO ]
          </h3>

          <div className="h-80 w-full relative z-10">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={threatData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="name"
                  stroke="#64748b"
                  style={{ fontSize: 10, fontFamily: 'monospace' }}
                />
                <YAxis stroke="#64748b" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#020617',
                    borderColor: '#1e293b',
                    color: '#f8fafc',
                    borderRadius: 8,
                    fontFamily: 'monospace',
                    fontSize: 11,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11, fontFamily: 'monospace', paddingTop: 10 }} />
                <Bar
                  dataKey="fakeNews"
                  fill={palette.primary}
                  name="Analyzed Items"
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="cyberAttacks"
                  fill={palette.accent}
                  name="Threats Mitigated"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </motion.div>
      </div>

      {/* 3. 'Threat History' Scrollable Logging Console */}
      <div
        className={`bg-slate-950/70 border border-slate-900 rounded-xl shadow-2xl overflow-hidden flex flex-col relative ${palette.glow}`}
      >
        {/* Dynamic Scanline Sweeper for the threat history box */}
        <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-red-500/30 to-transparent animate-scanline pointer-events-none" />

        {/* Header containing Filters & Inputs */}
        <div className="p-6 border-b border-slate-900 bg-slate-950/50 flex flex-col xl:flex-row xl:items-center justify-between gap-4 relative z-10">
          <div className="space-y-1.5">
            <h3 className="text-base font-black text-white flex items-center gap-2 font-mono tracking-wider">
              <ShieldAlert className="w-5 h-5 text-red-500 animate-pulse" />
              THREAT FORENSIC DECRYPTION VAULT
            </h3>
            <p className="text-[10px] text-slate-500 font-mono tracking-wide">
              Live secure cryptographic ledger syncing from network firewalls & AI scanning models
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Search Input */}
            <div className="relative min-w-[200px] flex-1 sm:flex-initial font-mono">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Query ledger..."
                className="w-full bg-slate-950 border border-slate-900 focus:border-slate-800 focus:ring-1 focus:ring-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 outline-none transition-all placeholder:text-slate-700 font-mono"
              />
            </div>

            {/* Type Filter Buttons */}
            <div className="flex items-center bg-slate-950 rounded-lg p-0.5 border border-slate-900 text-[10px] font-mono tracking-wider">
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterType('ALL');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${filterType === 'ALL' ? 'bg-slate-900 text-white font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                ALL
              </button>
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterType('NEWS');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer flex items-center gap-1 ${filterType === 'NEWS' ? 'bg-slate-900 text-blue-400 font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <Newspaper className="w-3 h-3" />
                INFO
              </button>
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterType('CYBER');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer flex items-center gap-1 ${filterType === 'CYBER' ? 'bg-slate-900 text-purple-400 font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                <ShieldAlert className="w-3 h-3" />
                CYBER
              </button>
            </div>

            {/* Severity Filter */}
            <div className="flex items-center bg-slate-950 rounded-lg p-0.5 border border-slate-900 text-[10px] font-mono tracking-wider">
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterRisk('ALL');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${filterRisk === 'ALL' ? 'bg-slate-900 text-white font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                RISK: ALL
              </button>
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterRisk('HIGH_RISK');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${filterRisk === 'HIGH_RISK' ? 'bg-slate-900 text-red-400 font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                HIGH
              </button>
              <button
                onClick={() => {
                  playCyberSFX('hover');
                  setFilterRisk('SAFE');
                }}
                className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${filterRisk === 'SAFE' ? 'bg-slate-900 text-emerald-400 font-bold border border-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
              >
                SAFE
              </button>
            </div>
          </div>
        </div>

        {/* Scrollable list container */}
        <div className="max-h-[380px] overflow-y-auto divide-y divide-slate-900/60 custom-scrollbar bg-slate-950/20 relative z-10">
          <AnimatePresence mode="popLayout">
            {filteredHistory.length === 0 ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="py-16 px-6 flex flex-col items-center justify-center text-center space-y-3"
              >
                <div className="p-4 bg-slate-900/40 border border-slate-900 rounded-full text-slate-700 animate-pulse">
                  <FileText className="w-7 h-7" />
                </div>
                <div className="space-y-1 font-mono">
                  <h4 className="text-xs font-bold text-slate-400">
                    [ CRYPTOGRAPHIC VAULT STERILE ]
                  </h4>
                  <p className="text-[10px] text-slate-600 max-w-xs mx-auto leading-relaxed">
                    No anomalies found. Run threat intelligence network diagnostics or workspace
                    checks to log forensic traces.
                  </p>
                </div>
              </motion.div>
            ) : (
              filteredHistory.map((item) => {
                const isExpanded = expandedId === item.id;
                const style = getSeverityStyle(item.result);

                return (
                  <motion.div
                    key={item.id}
                    layout="position"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.2 }}
                    className={`group hover:bg-slate-900/30 transition-all duration-300 cursor-pointer ${isExpanded ? 'bg-slate-900/20' : ''}`}
                    onClick={() => handleRowClick(item.id)}
                  >
                    {/* Primary Row Header */}
                    <div className="p-4 flex items-center justify-between gap-4">
                      <div className="flex items-center gap-4 min-w-0">
                        {/* Status Icon Indicator */}
                        <div
                          className={`p-2 rounded-lg border flex-shrink-0 bg-slate-950 transition-all group-hover:scale-105 duration-300 ${
                            item.type === 'NEWS'
                              ? 'border-blue-500/20 text-blue-400'
                              : 'border-purple-500/20 text-purple-400'
                          }`}
                        >
                          {item.type === 'NEWS' ? (
                            <Newspaper className="w-4 h-4 animate-omnitrix-pulse" />
                          ) : (
                            <ShieldAlert
                              className="w-4 h-4 animate-bounce"
                              style={{ animationDuration: '3s' }}
                            />
                          )}
                        </div>

                        {/* Title, Subtext, Timestamps */}
                        <div className="min-w-0 space-y-1">
                          <div className="flex items-center gap-2.5 flex-wrap">
                            <span
                              className={`text-[9px] font-mono font-black tracking-wider bg-slate-950 px-1.5 py-0.5 rounded border border-slate-900 ${
                                item.type === 'NEWS' ? 'text-blue-400' : 'text-purple-400'
                              }`}
                            >
                              {item.type === 'NEWS' ? 'INFO_GRID' : 'CYBER_SEC'}
                            </span>
                            <span className="text-xs font-medium text-slate-300 truncate group-hover:text-white transition-colors">
                              {item.summary.replace('...', '')}
                            </span>
                          </div>

                          <div className="flex items-center gap-3 text-[10px] text-slate-500 font-mono">
                            <span className="flex items-center gap-1 font-bold">
                              <Clock className="w-3 h-3 text-slate-600" />
                              {formatTimestamp(item.date)}
                            </span>
                            <span className="text-slate-800">|</span>
                            <span className="text-slate-600 truncate">
                              REF: {item.id.slice(0, 8).toUpperCase()}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Right actions and badges */}
                      <div
                        className="flex items-center gap-3 flex-shrink-0"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {/* Threat severity/result badge */}
                        <div
                          className={`px-2.5 py-1 rounded-full text-[9px] font-mono tracking-wider border font-bold flex items-center gap-1.5 ${style.badgeBg}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${style.dotBg}`}></span>
                          {item.result.toUpperCase()}
                        </div>

                        {/* Dropdown Chevron Toggle */}
                        <div
                          className="text-slate-600 group-hover:text-slate-400 transition-colors px-1"
                          onClick={() => handleRowClick(item.id)}
                        >
                          {isExpanded ? (
                            <ChevronUp className="w-4 h-4" />
                          ) : (
                            <ChevronDown className="w-4 h-4" />
                          )}
                        </div>

                        {/* Delete Trash Action */}
                        <button
                          onClick={(e) => handleDelete(item.id, e)}
                          disabled={deletingId === item.id}
                          className="p-1.5 rounded bg-slate-950 border border-slate-900 hover:border-red-500/40 text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
                          title="Purge record from firewalls"
                        >
                          {deletingId === item.id ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : (
                            <Trash2 className="w-3 h-3" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Expandable detailed payload drawer */}
                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="px-5 pb-5 pt-1 pl-14 border-t border-slate-900/40 bg-slate-950/40">
                            <div className="bg-slate-950/80 border border-slate-900 p-4 rounded-lg space-y-3 relative overflow-hidden">
                              <div className="absolute top-0 right-0 w-16 h-16 bg-slate-900/10 rounded-full blur-md" />
                              <div className="flex items-center justify-between border-b border-slate-900 pb-2 relative z-10">
                                <span className="text-[9px] font-mono uppercase tracking-widest text-slate-500 font-bold flex items-center gap-1.5">
                                  <Zap className="w-3 h-3 text-amber-500 animate-pulse" />
                                  Full Forensic Payload Report
                                </span>
                                <span
                                  className={`text-[9px] font-mono uppercase tracking-widest font-bold ${style.text}`}
                                >
                                  {style.riskLabel}
                                </span>
                              </div>
                              <p className="text-xs text-slate-300 leading-relaxed font-mono whitespace-pre-wrap relative z-10">
                                {item.summary}
                              </p>
                              <div className="flex items-center justify-between text-[8px] text-slate-600 font-mono pt-1.5 border-t border-slate-900 relative z-10">
                                <div>
                                  <span className="text-slate-500">INGRESS LINK:</span> users/
                                  {user?.id}/history/{item.id}
                                </div>
                                <div>[ CRYPTO_CLEARED_BY_ALGORITHM ]</div>
                              </div>
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
};
