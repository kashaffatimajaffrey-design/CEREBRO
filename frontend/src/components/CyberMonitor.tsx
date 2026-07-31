import React, { useState, useEffect } from 'react';
import { NetworkLog, ThreatLevel, CyberAnalysisResult } from '../types';
import { analyzeNetworkLogs } from '../services/apiService';
import { authHeaders } from '../services/session';
import { useAuth } from '../context/AuthContext';
import { jsPDF } from 'jspdf';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Fetch real network flows from the CEREBRO backend.
 *
 * This replaces generateMockLogs(), which fabricated 15 random flows and then
 * planted the answer into the input:
 *     logs[3].packetSize = 15000;
 *     logs[3].flags = 'SYN_FLOOD';
 * Nothing was ever detected — the anomaly was written in before analysis ran.
 *
 * Flows now come from Zeek/Suricata ingest via GET /v1/flows/recent.
 */
const fetchRecentFlows = async (limit = 25): Promise<NetworkLog[]> => {
  const res = await fetch(`${API_BASE}/v1/flows/recent?limit=${limit}`, {
    credentials: 'include',
    headers: { ...authHeaders() },
  });
  if (!res.ok) {
    throw new Error(
      res.status === 401
        ? 'Session expired. Please sign in again.'
        : `Could not load network flows (${res.status})`
    );
  }
  const data = await res.json();
  return (data.flows ?? []) as NetworkLog[];
};

export const CyberMonitor: React.FC = () => {
  const [logs, setLogs] = useState<NetworkLog[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<CyberAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alert, setAlert] = useState<{ level: ThreatLevel; message: string } | null>(null);
  const { addToHistory } = useAuth();

  const [loadingLogs, setLoadingLogs] = useState(true);

  const loadFlows = async () => {
    setLoadingLogs(true);
    setError(null);
    try {
      setLogs(await fetchRecentFlows());
    } catch (e: any) {
      setError(e.message ?? 'Could not load network flows.');
      setLogs([]);
    } finally {
      setLoadingLogs(false);
    }
  };

  useEffect(() => {
    loadFlows();
  }, []);

  const handleScan = async () => {
    setAnalyzing(true);
    setResult(null);
    setError(null);
    setAlert(null); // Reset alert on new scan

    try {
      const analysis = await analyzeNetworkLogs(logs);
      setResult(analysis);

      // Trigger Alert for High/Critical Threats
      if (analysis.threatLevel === ThreatLevel.CRITICAL || analysis.threatLevel === ThreatLevel.HIGH) {
        setAlert({
          level: analysis.threatLevel,
          message: `Security Breach Detected: ${analysis.threatLevel} threat level identified. Immediate mitigation recommended.`
        });
      }

      // Save to user history
      addToHistory({
        id: Math.random().toString(36).substr(2, 9),
        date: new Date().toISOString(),
        type: 'CYBER',
        summary: analysis.analysisReport.substring(0, 80) + '...',
        result: analysis.threatLevel
      });

    } catch (e: any) {
      console.error(e);
      setError(e.message || "Failed to analyze network logs. Please check the API configuration and try again.");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleExportPDF = () => {
    if (!result) return;
    const doc = new jsPDF();
    const margin = 20;
    const pageWidth = doc.internal.pageSize.getWidth();
    const maxLineWidth = pageWidth - margin * 2;

    // Header
    doc.setFontSize(22);
    doc.setTextColor(142, 68, 173); // Purple
    doc.text("CEREBRO", margin, 20);
    
    doc.setFontSize(12);
    doc.setTextColor(100);
    doc.text("Cyber Threat Analysis Report", margin, 28);
    doc.text(`Date: ${new Date().toLocaleString()}`, margin, 35);
    
    doc.setDrawColor(200);
    doc.line(margin, 40, pageWidth - margin, 40);

    // Results
    let y = 55;

    doc.setFontSize(14);
    doc.setTextColor(0);
    doc.text(`Threat Level: ${result.threatLevel.toUpperCase()}`, margin, y);
    
    if (result.threatLevel === 'Critical' || result.threatLevel === 'High') {
      doc.setTextColor(231, 76, 60); // Red for high threats
      doc.text("Action Required", pageWidth - margin - 40, y);
    }
    y += 15;

    // Analysis Report
    doc.setTextColor(0);
    doc.setFontSize(12);
    doc.setFont("helvetica", "bold");
    doc.text("AI Analysis Report", margin, y);
    y += 7;
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    const analysisLines = doc.splitTextToSize(result.analysisReport, maxLineWidth);
    doc.text(analysisLines, margin, y);
    y += (analysisLines.length * 5) + 10;

    // Recommendation
    doc.setFontSize(12);
    doc.setFont("helvetica", "bold");
    doc.text("Recommended Mitigation", margin, y);
    y += 7;
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    const actionLines = doc.splitTextToSize(result.recommendedAction, maxLineWidth);
    doc.text(actionLines, margin, y);
    y += (actionLines.length * 5) + 10;

    // Anomalies
    if (result.anomaliesDetected.length > 0) {
      doc.setFontSize(12);
      doc.setFont("helvetica", "bold");
      doc.text("Anomalous Log IDs Detected", margin, y);
      y += 7;
      doc.setFont("helvetica", "normal");
      doc.setFontSize(10);
      const anomalyText = result.anomaliesDetected.join(", ");
      const anomalyLines = doc.splitTextToSize(anomalyText, maxLineWidth);
      doc.text(anomalyLines, margin, y);
    }

    doc.save(`cerebro-cyber-scan-${Date.now()}.pdf`);
  };

  const getThreatColor = (level: ThreatLevel) => {
    switch (level) {
      case ThreatLevel.CRITICAL: return 'bg-red-500 text-white animate-pulse';
      case ThreatLevel.HIGH: return 'bg-orange-500 text-white';
      case ThreatLevel.MEDIUM: return 'bg-yellow-500 text-black';
      case ThreatLevel.LOW: return 'bg-blue-500 text-white';
      default: return 'bg-emerald-500 text-white';
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fade-in relative">
       <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold text-white">Cyber Threat Detection</h2>
          <p className="text-slate-400">Unsupervised Anomaly Detection (Isolation Forest + Autoencoder)</p>
        </div>
        <button
          onClick={handleScan}
          disabled={analyzing}
          className="bg-purple-600 hover:bg-purple-500 text-white px-6 py-2 rounded-lg font-semibold shadow-lg shadow-purple-500/20 disabled:opacity-50 transition-all"
        >
          {analyzing ? 'Scanning Network...' : 'Run AI Anomaly Check'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Network Log Table */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
          <div className="p-4 border-b border-slate-800 bg-slate-950/50 flex justify-between items-center">
             <h3 className="font-semibold text-slate-200">Live Network Traffic</h3>
             <span className="text-xs text-slate-500 font-mono">Sensor: {logs[0]?.sensor ?? 'zeek/eth0'}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-950 text-slate-400 uppercase font-medium">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Dest</th>
                  <th className="px-4 py-3">Proto</th>
                  <th className="px-4 py-3">Size</th>
                  <th className="px-4 py-3">Flags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {logs.map((log) => {
                   const isAnomalous = result?.anomaliesDetected.includes(log.id);
                   return (
                    <tr key={log.id} className={`hover:bg-slate-800/50 transition-colors ${isAnomalous ? 'bg-red-500/10' : ''}`}>
                      <td className="px-4 py-3 font-mono text-slate-400">{log.timestamp}</td>
                      <td className="px-4 py-3 text-slate-300">{log.sourceIP}</td>
                      <td className="px-4 py-3 text-slate-300">{log.destIP}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                          log.protocol === 'TCP' ? 'bg-blue-500/20 text-blue-400' :
                          log.protocol === 'UDP' ? 'bg-orange-500/20 text-orange-400' :
                          'bg-slate-700 text-slate-300'
                        }`}>
                          {log.protocol}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{log.packetSize}B</td>
                      <td className="px-4 py-3 text-xs font-mono text-slate-500">{log.flags}</td>
                    </tr>
                   );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* AI Analysis Panel */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 h-full shadow-lg flex flex-col">
            <h3 className="text-xl font-semibold mb-4 text-white">Threat Intelligence</h3>
            
            {!result && !analyzing && !error && (
               <div className="text-center py-12 text-slate-500 my-auto">
                  <svg className="w-16 h-16 mx-auto mb-4 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
                  <p>System Idle. Initiate scan to detect anomalies.</p>
               </div>
            )}

            {analyzing && (
              <div className="flex flex-col items-center justify-center py-12 space-y-4 my-auto">
                <div className="w-12 h-12 border-4 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
                <p className="text-purple-400 animate-pulse">Running Neural Networks...</p>
              </div>
            )}

            {error && (
                <div className="p-5 bg-red-500/10 border border-red-500/20 rounded-lg animate-fade-in my-auto">
                    <div className="flex items-center gap-2 text-red-400 mb-3">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                        <h4 className="font-semibold text-lg">Analysis Failed</h4>
                    </div>
                    <p className="text-sm text-slate-400 mb-4 leading-relaxed">
                      {error.includes("leaked") || error.includes("403") ? (
                        <>
                          <span className="text-red-400 font-bold block mb-1">API KEY LEAKED:</span>
                          Your server-side Gemini API key has been reported as leaked by Google. Please generate a new key and update it in the <span className="text-purple-400 underline font-bold">Settings &gt; Secrets</span> panel in AI Studio to restore full threat assessment.
                        </>
                      ) : (
                        error
                      )}
                    </p>
                    <button 
                        onClick={handleScan}
                        className="w-full py-2.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm font-medium transition-colors border border-red-500/20 flex items-center justify-center gap-2 cursor-pointer"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                        Retry Analysis
                    </button>
                </div>
            )}

            {result && !analyzing && !error && (
              <div className="space-y-6 animate-fade-in">
                <div className="flex items-center justify-between bg-slate-950 p-4 rounded-lg border border-slate-800">
                  <span className="text-slate-400 font-medium">Threat Level</span>
                  <span className={`px-3 py-1 rounded-md text-sm font-bold uppercase ${getThreatColor(result.threatLevel)}`}>
                    {result.threatLevel}
                  </span>
                </div>

                <div>
                  <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">Analysis Report</h4>
                  <p className="text-sm text-slate-300 bg-slate-950/50 p-3 rounded-lg border border-slate-800 leading-relaxed">
                    {result.analysisReport}
                  </p>
                </div>

                <div>
                  <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">Recommended Action</h4>
                  <div className="flex items-start gap-2 text-sm text-emerald-400 bg-emerald-500/10 p-3 rounded-lg border border-emerald-500/20">
                    <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                    <span>{result.recommendedAction}</span>
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-800">
                  <button 
                    onClick={handleExportPDF}
                    className="w-full py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors border border-slate-700 group"
                  >
                    <svg className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                    Download Analysis PDF
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Persistent, Non-intrusive Alert Notification */}
      {alert && (
        <div className="fixed bottom-8 right-8 z-50 animate-fade-in">
           <div className={`flex items-start gap-4 p-4 rounded-lg shadow-2xl border-l-4 max-w-sm bg-slate-900 ${
             alert.level === ThreatLevel.CRITICAL ? 'border-red-500 shadow-red-500/20' : 'border-orange-500 shadow-orange-500/20'
           }`}>
             <div className={`p-2 rounded-full ${alert.level === ThreatLevel.CRITICAL ? 'bg-red-500/20 text-red-500' : 'bg-orange-500/20 text-orange-500'}`}>
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
             </div>
             <div className="flex-1">
               <h4 className="font-bold text-white">Threat Alert</h4>
               <p className="text-sm text-slate-300 mt-1">{alert.message}</p>
             </div>
             <button onClick={() => setAlert(null)} className="text-slate-500 hover:text-white transition-colors">
               <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                 <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
               </svg>
             </button>
           </div>
        </div>
      )}
    </div>
  );
};