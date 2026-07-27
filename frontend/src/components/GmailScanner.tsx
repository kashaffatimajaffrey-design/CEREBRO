import { useAuth } from '../context/AuthContext';
import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { GoogleAuthProvider, signInWithPopup } from 'firebase/auth';
import { auth } from '../services/firebase';

interface GmailMessage {
  id: string;
  subject: string;
  from: string;
  date: string;
  snippet: string;
  status?: 'SAFE' | 'SUSPICIOUS' | 'HIGH_RISK' | 'UNSCANNED';
  forensics?: AlertForensics;
}

interface AlertForensics {
  riskScore: number; // 0-100
  verdict: 'SAFE' | 'SUSPICIOUS' | 'HIGH_RISK';
  summary: string;
  indicators: string[];
  reasoning: string;
  suggestedAction: string;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export const GmailScanner: React.FC = () => {
  const { user } = useAuth();
  const [accessToken, setAccessToken] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [emails, setEmails] = useState<GmailMessage[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<GmailMessage | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [scanLoading, setScanLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  
  // Custom manual client credentials config
  const [clientId, setClientId] = useState<string>(
    import.meta.env.VITE_GOOGLE_CLIENT_ID || '79601707-222e-4675-a167-4ef3a42ca57d'
  );
  const [isShowingCredentialsHelp, setIsShowingCredentialsHelp] = useState<boolean>(false);

  // Warning email draft states
  const [warningRecipient, setWarningRecipient] = useState<string>('');
  const [warningSubject, setWarningSubject] = useState<string>('');
  const [warningBody, setWarningBody] = useState<string>('');
  const [sendLoading, setSendLoading] = useState<boolean>(false);
  const [sendSuccess, setSendSuccess] = useState<boolean>(false);

  // Safety confirmation dialog modal
  const [showConfirmation, setShowConfirmation] = useState<boolean>(false);

  // Auto-load token from localStorage if present
  useEffect(() => {
    const savedToken = null; // tokens live server-side now
    if (savedToken) {
      setAccessToken(savedToken);
      setIsConnected(true);
      fetchInbox(savedToken);
    }
  }, []);

  const handleConnectWithToken = async () => {
    if (!accessToken.trim()) {
      setError('Please provide a valid OAuth Access Token.');
      return;
    }
    setError(null);
    // Token is no longer stored in the browser. It is exchanged for a
    // server-side session by POST /v1/auth/google/exchange and held
    // encrypted in oauth_credentials, keyed to the authenticated user.
    await fetch(`${API_BASE}/v1/auth/google/exchange`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ access_token: accessToken }),
    });
    setIsConnected(true);
    fetchInbox(accessToken);
  };

  const handleDisconnect = async () => {
    await fetch(`${API_BASE}/v1/auth/google/revoke`, { method: 'POST', credentials: 'include' });
    setAccessToken('');
    setIsConnected(false);
    setEmails([]);
    setSelectedEmail(null);
    setError(null);
  };

  // Initiate Google OAuth Flow via Firebase Popup
  const handleOAuthLogin = async () => {
    try {
      setError(null);
      setLoading(true);
      const provider = new GoogleAuthProvider();
      provider.addScope('https://www.googleapis.com/auth/gmail.readonly');
      provider.addScope('https://www.googleapis.com/auth/gmail.send');
      provider.addScope('https://www.googleapis.com/auth/gmail.labels');

      const result = await signInWithPopup(auth, provider);
      const credential = GoogleAuthProvider.credentialFromResult(result);
      if (!credential?.accessToken) {
        throw new Error('Could not retrieve access token from Google sign in.');
      }
      const token = credential.accessToken;
      setAccessToken(token);
      setIsConnected(true);
      await fetchInbox(token);
    } catch (err: any) {
      console.error('Google OAuth Error:', err);
      if (err?.code === 'auth/popup-closed-by-user') {
        setError('Google Sign-in popup was closed before completing authentication. Please try again or use manual token fallback.');
      } else if (err?.code === 'auth/cancelled-popup-request') {
        setError('Previous sign-in request was cancelled. Please try again.');
      } else {
        setError(err.message || 'Failed to authenticate with Google. You can also paste an OAuth Access Token directly below.');
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchInbox = async (token: string) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/gmail-fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accessToken: token }),
      });

      if (!response.ok) {
        const errDetail = await response.json();
        throw new Error(errDetail.error || 'Failed to list emails');
      }

      const data = await response.json();
      const mappedEmails = data.emails.map((e: any) => ({
        ...e,
        status: 'UNSCANNED'
      }));
      setEmails(mappedEmails);
    } catch (err: any) {
      console.error(err);
      setError(`Google Workspace Access Denied: ${err.message || 'Check your permissions/token scope.'}`);
      // If token expired, clear connection
      if (err.message?.includes('401') || err.message?.includes('Unauthorized')) {
        handleDisconnect();
      }
    } finally {
      setLoading(false);
    }
  };

  const scanEmail = async (email: GmailMessage) => {
    setScanLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/gmail-analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: email.id,
          subject: email.subject,
          from: email.from,
          date: email.date,
          snippet: email.snippet
        }),
      });

      if (!response.ok) {
        throw new Error('AI digital risk assessment failed. Try again.');
      }

      const forensicsResult: AlertForensics = await response.json();
      
      // Update email in grid
      const updated = emails.map(e => e.id === email.id ? { 
        ...e, 
        status: forensicsResult.verdict, 
        forensics: forensicsResult 
      } : e);
      
      setEmails(updated);
      setSelectedEmail({
        ...email,
        status: forensicsResult.verdict,
        forensics: forensicsResult
      });

      // Draft a warning reply template for the analyst
      const cleanSender = email.from.replace(/<.*?>/g, '').trim();
      setWarningRecipient(user?.email ?? '');
      setWarningSubject(`[CEREBRO Security Alert] Warning regarding message: ${email.subject}`);
      setWarningBody(
        `Dear user,\n\nOur CEREBRO Forensic Threat Intelligence Core scanned your email with the subject: "${email.subject}" from "${cleanSender}".\n\nAI Risk Analysis Result:\n- Danger assessment score: ${forensicsResult.riskScore}/100\n- Primary verdict: ${forensicsResult.verdict}\n- Threat Indicators identified: ${forensicsResult.indicators.join(', ')}\n\nForensic Details: ${forensicsResult.summary}\n\nSecurity Recommendation: ${forensicsResult.suggestedAction}\n\nThis is a standard quarantine warning alert from the CEREBRO console.\n\nRespectfully,\nCEREBRO Security Operations Center (SOC)`
      );
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to scan the specified email');
    } finally {
      setScanLoading(false);
    }
  };

  // Safe mutations via implicit confirmation check!
  const triggerSendWarning = () => {
    if (!warningRecipient) {
      setError('Please specify a valid warning alert recipient.');
      return;
    }
    setError(null);
    setShowConfirmation(true); // Open the verification dialog
  };

  const executeSendWarning = async () => {
    setShowConfirmation(false);
    setSendLoading(true);
    setSendSuccess(false);
    try {
      const response = await fetch('/api/gmail-send-alert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accessToken,
          to: warningRecipient,
          subject: warningSubject,
          body: warningBody
        })
      });

      if (!response.ok) {
        const details = await response.json();
        throw new Error(details.error || 'Failed to transmit email warning alert.');
      }

      setSendSuccess(true);
      setTimeout(() => setSendSuccess(false), 5000); // Clear after 5s
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to dispatch the security alert.');
    } finally {
      setSendLoading(false);
    }
  };

  return (
    <div id="gmail-scanner-container" className="space-y-6 animate-fade-in text-slate-100">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h3 className="text-xl font-bold text-white flex items-center gap-2">
              <svg className="w-6 h-6 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Gmail Security Threat Center
            </h3>
            <p className="text-sm text-slate-400 mt-1">
              Search real-time corporate workspace communications, flag spoofing links, phishing attempts, and forward fake news.
            </p>
          </div>
          
          {isConnected && (
            <button
              onClick={handleDisconnect}
              className="px-4 py-2 text-xs font-semibold uppercase tracking-wider bg-red-950/40 hover:bg-red-900/60 text-red-400 border border-red-800/50 rounded-lg transition-colors flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
              Disconnect Gmail API
            </button>
          )}
        </div>

        {error && (
          <div className="mt-4 p-4 bg-red-950/50 border border-red-900 text-red-200 text-sm rounded-lg flex items-start gap-2 font-mono">
            <svg className="w-5 h-5 flex-shrink-0 text-red-500 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <div className="space-y-1">
              {error.includes("leaked") || error.includes("403") ? (
                <>
                  <span className="text-red-400 font-bold block">[ API KEY LEAKED ]</span>
                  <span>Your server-side Gemini API key has been reported as leaked by Google. Please generate a new key and update it in the <strong>Settings &gt; Secrets</strong> panel in AI Studio to restore full email threat assessment.</span>
                </>
              ) : (
                <span>{error}</span>
              )}
            </div>
          </div>
        )}

        {!isConnected && (
          <div className="mt-6 border border-slate-800 bg-slate-950/60 rounded-xl p-8 text-center max-w-2xl mx-auto space-y-6">
            <div className="w-16 h-16 bg-blue-900/20 text-blue-500 rounded-full flex items-center justify-center mx-auto border border-blue-500/20">
              <svg className="w-8 h-8 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
            </div>
            
            <div className="space-y-2">
              <h4 className="text-lg font-bold text-white">Establish Secure Authentication Handshake</h4>
              <p className="text-sm text-slate-400">
                To run AI analytics on inbox threats, authorize the CEREBRO workspace to contact your Gmail Workspace logs securely.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row gap-4 justify-center items-center">
              <button
                onClick={handleOAuthLogin}
                className="gsi-material-button text-black bg-white hover:bg-slate-100 font-medium px-4 py-2.5 rounded-lg flex items-center gap-3 transition-colors text-sm border border-slate-300 shadow-sm cursor-pointer"
                style={{ fontFamily: 'Inter, sans-serif' }}
              >
                <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center">
                  <svg version="1.1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" style={{ display: "block" }}>
                    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"></path>
                    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"></path>
                    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"></path>
                    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"></path>
                  </svg>
                </div>
                <span>Sign in with Google</span>
              </button>

              <span className="text-slate-600 text-xs font-semibold">OR</span>

              <button
                onClick={() => setIsShowingCredentialsHelp(!isShowingCredentialsHelp)}
                className="px-4 py-2.5 text-sm bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors border border-slate-700"
              >
                Configure Manual Credentials
              </button>
            </div>

            {isShowingCredentialsHelp && (
              <motion.div 
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-slate-900 border border-slate-800 rounded-lg p-6 text-left space-y-4 text-xs"
              >
                <div className="space-y-1">
                  <label className="block text-slate-400 font-medium">Custom Google Client ID (Optional):</label>
                  <input
                    type="text"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    placeholder="Enter Client ID for Popups"
                    className="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded text-white focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">
                    CEREBRO has a preconfigured core Client ID, but you can override with your own.
                  </p>
                </div>

                <div className="space-y-1 pt-2 border-t border-slate-800">
                  <label className="block text-slate-400 font-medium font-bold text-slate-300">Direct Access Token Override (Best Sandbox Fallback):</label>
                  <textarea
                    rows={3}
                    value={accessToken}
                    onChange={(e) => setAccessToken(e.target.value)}
                    placeholder="Paste a Google OAuth Access Token with gmail.readonly & gmail.send scopes"
                    className="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded text-white focus:outline-none focus:border-blue-500 font-mono"
                  />
                  <div className="flex justify-between items-center mt-2">
                    <p className="text-[10px] text-slate-500">
                      Perfect if third-party popup authorization limits are blocked inside the AI Studio iframe. Get a quick key at Google OAuth Playground.
                    </p>
                    <button
                      onClick={handleConnectWithToken}
                      className="bg-blue-600 hover:bg-blue-500 text-white font-bold px-4 py-1.5 rounded transition-colors"
                    >
                      Use Manual Token
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </div>
        )}
      </div>

      {isConnected && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Inbox messages list panel */}
          <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden flex flex-col h-[650px]">
            <div className="p-4 bg-slate-900/80 border-b border-slate-800 flex justify-between items-center">
              <h4 className="text-sm font-bold text-white uppercase tracking-wider">Workspace Inbox Feed</h4>
              <button
                onClick={() => fetchInbox(accessToken)}
                disabled={loading}
                className="p-1.5 text-slate-400 hover:text-white rounded-md bg-slate-800 hover:bg-slate-700 transition-colors disabled:opacity-50"
                title="Refresh Inbox"
              >
                <svg className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 15H15.82a8.001 8.001 0 0113.83-6h.582M4 4a8.001 8.001 0 018-8v8h8" />
                </svg>
              </button>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-slate-800">
              {loading ? (
                <div className="flex flex-col items-center justify-center h-full space-y-2">
                  <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                  <span className="text-slate-500 text-xs">Querying Workspace Endpoints...</span>
                </div>
              ) : emails.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-8 text-center h-full text-slate-500">
                  <svg className="w-12 h-12 mb-2 stroke-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0a2 2 0 01-2 2H6a2 2 0 01-2-2m16 0V9a2 2 0 00-2-2H6a2 2 0 00-2 2v4h16z" />
                  </svg>
                  <p className="text-sm">Inbox is completely clean.</p>
                  <p className="text-xs text-slate-600 mt-1">No corporate emails returned or lack of permission.</p>
                </div>
              ) : (
                emails.map((email) => {
                  const isSelected = selectedEmail?.id === email.id;
                  let badge = <span className="bg-slate-800 text-slate-400 text-[10px] uppercase font-bold px-1.5 py-0.5 rounded">Unscanned</span>;
                  if (email.status === 'SAFE') {
                    badge = <span className="bg-emerald-950/60 text-emerald-400 border border-emerald-800/40 text-[10px] uppercase font-bold px-1.5 py-0.5 rounded">Safe</span>;
                  } else if (email.status === 'SUSPICIOUS') {
                    badge = <span className="bg-amber-950/60 text-amber-400 border border-amber-800/40 text-[10px] uppercase font-bold px-1.5 py-0.5 rounded">Suspicious</span>;
                  } else if (email.status === 'HIGH_RISK') {
                    badge = <span className="bg-red-950/60 text-red-400 border border-red-800/40 text-[10px] uppercase font-bold px-1.5 py-0.5 rounded">High Risk</span>;
                  }

                  return (
                    <div
                      key={email.id}
                      onClick={() => {
                        setSelectedEmail(email);
                        setSendSuccess(false);
                      }}
                      className={`p-4 text-left cursor-pointer transition-colors relative hover:bg-slate-850 ${
                        isSelected ? 'bg-slate-800/50 border-l-2 border-blue-500' : 'bg-transparent'
                      }`}
                    >
                      <div className="flex justify-between items-start gap-2 mb-1">
                        <span className="text-xs font-bold text-slate-350 truncate max-w-[150px]">{email.from}</span>
                        <span className="text-[10px] text-slate-500 flex-shrink-0">{new Date(email.date).toLocaleDateString([], { month: 'short', day: 'numeric' })}</span>
                      </div>
                      <h5 className="text-sm font-semibold text-white truncate mb-1">{email.subject}</h5>
                      <p className="text-xs text-slate-400 line-clamp-2 mb-2">{email.snippet}</p>
                      <div className="flex justify-between items-center pt-1">
                        {badge}
                        <span className="text-[10px] text-slate-600 font-mono">ID: {email.id.substring(0, 8)}...</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Forensic Panel and Actions Panel */}
          <div className="lg:col-span-7 space-y-6">
            {selectedEmail ? (
              <div className="space-y-6">
                {/* Email details card */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-left space-y-4">
                  <div className="border-b border-slate-800 pb-4 space-y-2">
                    <div className="flex justify-between items-start">
                      <span className="text-xs text-slate-400">Security Audit Focus Node</span>
                      <span className="text-xs font-mono text-slate-500">ID: {selectedEmail.id}</span>
                    </div>
                    <h4 className="text-lg font-bold text-white">{selectedEmail.subject}</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-300">
                      <div><span className="text-slate-550 font-medium">From:</span> {selectedEmail.from}</div>
                      <div><span className="text-slate-550 font-medium">Date:</span> {selectedEmail.date}</div>
                    </div>
                  </div>

                  {/* Body / Snippet preview */}
                  <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 max-h-[150px] overflow-y-auto">
                    <p className="text-xs text-slate-300 font-mono leading-relaxed whitespace-pre-wrap">
                      {selectedEmail.snippet || '(No text content)'}
                    </p>
                  </div>

                  {/* Risk Analysis Display */}
                  {selectedEmail.forensics ? (
                    <div className="p-5 bg-slate-950 rounded-xl border border-slate-800 space-y-4">
                      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        <div className="flex items-center gap-4">
                          {/* Radial / Circle meter */}
                          <div className="relative w-16 h-16 flex items-center justify-center flex-shrink-0">
                            <svg className="w-full h-full rotate-[-95deg]">
                              <circle cx="32" cy="32" r="28" stroke="#1e293b" strokeWidth="4" fill="transparent" />
                              <circle 
                                cx="32" 
                                cy="32" 
                                r="28" 
                                stroke={selectedEmail.forensics.riskScore > 75 ? '#ef4444' : selectedEmail.forensics.riskScore > 35 ? '#f59e0b' : '#10b981'} 
                                strokeWidth="4" 
                                fill="transparent" 
                                strokeDasharray="175"
                                strokeDashoffset={175 - (175 * selectedEmail.forensics.riskScore) / 100}
                              />
                            </svg>
                            <span className="absolute text-sm font-bold text-white font-mono">{selectedEmail.forensics.riskScore}%</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block">AI Forensic Verdict</span>
                            <span className={`text-base font-bold ${
                              selectedEmail.forensics.verdict === 'HIGH_RISK' ? 'text-red-500' : selectedEmail.forensics.verdict === 'SUSPICIOUS' ? 'text-amber-500' : 'text-emerald-500'
                            }`}>
                              {selectedEmail.forensics.verdict === 'HIGH_RISK' && 'CRITICAL PHISHING / SECURITY THREAT'}
                              {selectedEmail.forensics.verdict === 'SUSPICIOUS' && 'SUSPICIOUS LINK / METADATA FLAG'}
                              {selectedEmail.forensics.verdict === 'SAFE' && 'VERIFIED SECURE COMMUNICATIONS'}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <h5 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Analysis Reasoning</h5>
                        <p className="text-xs text-slate-350 leading-relaxed font-sans">{selectedEmail.forensics.reasoning}</p>
                      </div>

                      <div className="space-y-2 pt-2 border-t border-slate-800">
                        <h5 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Identified Threat Indicators</h5>
                        <div className="flex flex-wrap gap-2">
                          {selectedEmail.forensics.indicators.map((ind, i) => (
                            <span key={i} className="bg-slate-900 border border-slate-800 text-slate-300 px-2 py-0.5 rounded text-[10px] font-mono">
                              ▲ {ind}
                            </span>
                          ))}
                          {selectedEmail.forensics.indicators.length === 0 && (
                            <span className="text-xs text-slate-500">None detected. Header alignment aligns with safe origin.</span>
                          )}
                        </div>
                      </div>

                      <div className="p-3 bg-blue-950/20 border border-blue-900/30 rounded-lg text-xs flex gap-2">
                        <svg className="w-5 h-5 flex-shrink-0 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <div>
                          <strong className="text-blue-400">Security Team Protocol:</strong> {selectedEmail.forensics.suggestedAction}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center p-8 bg-slate-950 rounded-xl border border-slate-800/60">
                      <p className="text-sm text-slate-400 mb-4">No risk analysis has been carried out on this message. Execute the forensics engine below.</p>
                      <button
                        onClick={() => scanEmail(selectedEmail)}
                        disabled={scanLoading}
                        className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold px-6 py-2.5 rounded-lg text-sm transition-all flex items-center justify-center gap-2 mx-auto"
                      >
                        {scanLoading ? (
                          <>
                            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                            Running threat forensics model...
                          </>
                        ) : (
                          <>
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364.364l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                            </svg>
                            Execute AI Forensic Threat Scan
                          </>
                        )}
                      </button>
                    </div>
                  )}
                </div>

                {/* Threat Mitigation alerts composer */}
                {selectedEmail.forensics && (
                  <motion.div 
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-left space-y-4"
                  >
                    <div className="flex items-center gap-2">
                      <svg className="w-5 h-5 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                      </svg>
                      <h4 className="text-base font-bold text-white">Digital Risk Countermeasure Suite</h4>
                    </div>
                    <p className="text-xs text-slate-400">
                      Draft and send quarantine notices or security indicators to original senders or network users utilizing Google Workspace dispatch.
                    </p>

                    <div className="space-y-3">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div className="space-y-1">
                          <label className="block text-[11px] text-slate-400 font-semibold uppercase">Recipient Address</label>
                          <input
                            type="text"
                            value={warningRecipient}
                            onChange={(e) => setWarningRecipient(e.target.value)}
                            className="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded text-xs text-white focus:outline-none focus:border-amber-500 font-mono"
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="block text-[11px] text-slate-400 font-semibold uppercase">Alert Subject</label>
                          <input
                            type="text"
                            value={warningSubject}
                            onChange={(e) => setWarningSubject(e.target.value)}
                            className="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded text-xs text-white focus:outline-none focus:border-amber-500 font-mono"
                          />
                        </div>
                      </div>

                      <div className="space-y-1">
                        <label className="block text-[11px] text-slate-400 font-semibold uppercase">Security Advisory Content</label>
                        <textarea
                          rows={6}
                          value={warningBody}
                          onChange={(e) => setWarningBody(e.target.value)}
                          className="w-full bg-slate-950 border border-slate-700 px-3 py-2 rounded text-xs text-white focus:outline-none focus:border-amber-500 font-mono leading-relaxed"
                        />
                      </div>

                      {sendSuccess && (
                        <div className="p-3 bg-emerald-950/60 border border-emerald-800 text-emerald-250 text-xs rounded-lg flex items-center gap-2">
                          <svg className="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          <span>Warning alert email successfully dispatched via Gmail API!</span>
                        </div>
                      )}

                      <button
                        onClick={triggerSendWarning}
                        disabled={sendLoading}
                        className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-slate-950 font-bold py-2.5 rounded-lg text-xs uppercase tracking-wider transition-colors flex items-center justify-center gap-2"
                      >
                        {sendLoading ? 'Transmitting Warning Alert...' : 'Dispatch Cyber Advisory Reply'}
                      </button>
                    </div>
                  </motion.div>
                )}
              </div>
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center flex flex-col items-center justify-center h-[400px] text-slate-500">
                <svg className="w-16 h-16 mb-4 text-slate-700 stroke-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 4H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-2m-4-1v8m0 0l3-3m-3 3L9 8m-5 5h2.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293h3.172a1 1 0 00.707-.293l2.414-2.414a1 1 0 01.707-.293H20" />
                </svg>
                <h4 className="text-white font-bold text-base mb-1">Select an email to audit</h4>
                <p className="text-xs text-slate-400">Scan details of Workspace traffic nodes for vulnerabilities.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* COMPLIANCY: Explicit User confirmation dialog before workspace database mutation */}
      <AnimatePresence>
        {showConfirmation && (
          <div className="fixed inset-0 bg-black/80 z-55 flex items-center justify-center p-4">
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 p-6 rounded-xl max-w-md w-full space-y-4 text-left shadow-2xl relative"
            >
              <h5 className="text-lg font-bold text-white flex items-center gap-2 text-amber-500">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                Confirm Gmail Alert Transmission
              </h5>
              <p className="text-xs text-slate-300 leading-relaxed">
                You are about to transmit an official cybersecurity advisory email on your personal workspace behalf.
              </p>
              
              <div className="bg-slate-950 p-3 rounded border border-slate-850 space-y-1 text-xs font-mono text-slate-400">
                <div><span className="text-slate-650">Sender:</span> Your Connected Google Account</div>
                <div><span className="text-slate-650">Recipient:</span> {warningRecipient}</div>
                <div><span className="text-slate-650">Subject:</span> {warningSubject}</div>
              </div>

              <div className="flex gap-3 justify-end pt-2">
                <button
                  onClick={() => setShowConfirmation(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-lg transition-colors border border-slate-700"
                >
                  Cancel
                </button>
                <button
                  onClick={executeSendWarning}
                  className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-slate-950 text-xs font-bold rounded-lg transition-colors"
                >
                  Confirm & Send
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};
