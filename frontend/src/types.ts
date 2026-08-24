export enum View {
  DASHBOARD = 'DASHBOARD',
  NEWS_SCANNER = 'NEWS_SCANNER',
  CYBER_MONITOR = 'CYBER_MONITOR',
  EMAIL_SCANNER = 'EMAIL_SCANNER',
  PROFILE = 'PROFILE',
}

export enum ThreatLevel {
  SAFE = 'Safe',
  LOW = 'Low',
  MEDIUM = 'Medium',
  HIGH = 'High',
  CRITICAL = 'Critical',
}

export interface NewsAnalysisResult {
  credibilityScore: number; // 0 to 100
  verdict: string; // "Credible", "Misleading", "Fake News"
  summary: string;
  reasoning: string;
  sources: string[];
}

export interface NetworkLog {
  id: string;
  timestamp: string;
  sourceIP: string;
  destIP: string;
  protocol: 'TCP' | 'UDP' | 'ICMP' | 'HTTP';
  packetSize: number;
  flags: string;
  // Sensor/interface the flow was captured on (e.g. "zeek/eth0"), when known.
  // Optional: browser-generated demo logs don't carry it.
  sensor?: string;
}

export interface CyberAnalysisResult {
  threatLevel: ThreatLevel;
  anomaliesDetected: string[]; // List of Log IDs
  analysisReport: string;
  recommendedAction: string;
}

export interface HistoryItem {
  id: string;
  date: string;
  type: 'NEWS' | 'CYBER';
  summary: string;
  result: string; // e.g., "Critical" or "85% Credible"
}

export interface User {
  id: string;
  name: string;
  email: string;
  history: HistoryItem[];
}
