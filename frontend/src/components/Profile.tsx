import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { HistoryItem } from '../types';

export const Profile: React.FC = () => {
  const { user, updateUser, logout } = useAuth();
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(user?.name || '');
  const [email, setEmail] = useState(user?.email || '');
  
  // Filter & Sort State
  const [filterType, setFilterType] = useState<'ALL' | 'NEWS' | 'CYBER'>('ALL');
  const [sortOption, setSortOption] = useState<'NEWEST' | 'OLDEST' | 'RISK_HIGH' | 'RISK_LOW'>('NEWEST');

  if (!user) return null;

  const handleSave = () => {
    updateUser({ name, email });
    setIsEditing(false);
  };

  const getHistoryColor = (type: string, result: string) => {
    if (type === 'NEWS') {
      const score = parseInt(result);
      if (score >= 80) return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10';
      if (score >= 50) return 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10';
      return 'text-red-400 border-red-500/30 bg-red-500/10';
    } else {
      // Cyber
      const lower = result.toLowerCase();
      if (lower.includes('safe') || lower.includes('low')) return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10';
      if (lower.includes('medium')) return 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10';
      return 'text-red-400 border-red-500/30 bg-red-500/10';
    }
  };

  const getRiskScore = (item: HistoryItem) => {
    if (item.type === 'NEWS') {
      // result format example: "85% Credible"
      // High credibility (85) means Low Risk (15). Low credibility (10) means High Risk (90).
      const match = item.result.match(/(\d+)%/);
      const score = match ? parseInt(match[1]) : 0;
      return 100 - score;
    } else {
      // result format example: "Critical", "High", "Medium", "Low", "Safe"
      const r = item.result.toUpperCase();
      if (r === 'CRITICAL') return 100;
      if (r === 'HIGH') return 75;
      if (r === 'MEDIUM') return 50;
      if (r === 'LOW') return 25;
      return 0; // Safe
    }
  };

  const filteredAndSortedHistory = [...user.history]
    .filter(item => filterType === 'ALL' || item.type === filterType)
    .sort((a, b) => {
      switch (sortOption) {
        case 'NEWEST':
          return new Date(b.date).getTime() - new Date(a.date).getTime();
        case 'OLDEST':
          return new Date(a.date).getTime() - new Date(b.date).getTime();
        case 'RISK_HIGH':
          return getRiskScore(b) - getRiskScore(a);
        case 'RISK_LOW':
          return getRiskScore(a) - getRiskScore(b);
        default:
          return 0;
      }
    });

  return (
    <div className="max-w-4xl mx-auto space-y-8 animate-fade-in pb-10">
      {/* Profile Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-blue-600/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2"></div>
        
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center gap-6">
          <div className="w-24 h-24 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center text-4xl font-bold text-white shadow-xl">
            {user.name.charAt(0).toUpperCase()}
          </div>
          
          <div className="flex-1">
            {isEditing ? (
              <div className="space-y-4 max-w-md">
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-white focus:border-blue-500 outline-none"
                  placeholder="Full Name"
                />
                <input
                  type="email"
                  value={email}
                  disabled
                  className="w-full bg-slate-950/60 border border-slate-850 rounded px-3 py-2 text-slate-500 cursor-not-allowed outline-none"
                  placeholder="Email"
                />
                <div className="flex gap-2">
                  <button onClick={handleSave} className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-sm font-medium">Save Changes</button>
                  <button onClick={() => setIsEditing(false)} className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded text-sm font-medium">Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <h2 className="text-2xl font-bold text-white">{user.name}</h2>
                <p className="text-slate-400">{user.email}</p>
                <div className="mt-4 flex gap-3">
                   <button onClick={() => setIsEditing(true)} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors border border-slate-700">
                     Edit Profile
                   </button>
                   <button onClick={logout} className="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg text-sm transition-colors border border-red-500/20">
                     Sign Out
                   </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
           <p className="text-xs text-slate-500 uppercase font-semibold">Total Scans</p>
           <p className="text-2xl font-bold text-white mt-1">{user.history.length}</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
           <p className="text-xs text-slate-500 uppercase font-semibold">News Verified</p>
           <p className="text-2xl font-bold text-blue-400 mt-1">{user.history.filter(h => h.type === 'NEWS').length}</p>
        </div>
        <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl">
           <p className="text-xs text-slate-500 uppercase font-semibold">Cyber Alerts</p>
           <p className="text-2xl font-bold text-purple-400 mt-1">{user.history.filter(h => h.type === 'CYBER').length}</p>
        </div>
      </div>

      {/* History List */}
      <div className="space-y-4">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <h3 className="text-xl font-bold text-white">Analysis History</h3>
          
          <div className="flex flex-col sm:flex-row gap-4 w-full md:w-auto items-center">
            {/* Filter Buttons */}
            <div className="flex bg-slate-900 p-1 rounded-lg border border-slate-800 w-full sm:w-auto">
              <button 
                onClick={() => setFilterType('ALL')} 
                className={`flex-1 px-4 py-1.5 rounded-md text-sm font-medium transition-all ${filterType === 'ALL' ? 'bg-slate-800 text-white shadow ring-1 ring-slate-700' : 'text-slate-400 hover:text-white'}`}
              >
                All
              </button>
              <button 
                onClick={() => setFilterType('NEWS')} 
                className={`flex-1 px-4 py-1.5 rounded-md text-sm font-medium transition-all ${filterType === 'NEWS' ? 'bg-slate-800 text-white shadow ring-1 ring-slate-700' : 'text-slate-400 hover:text-white'}`}
              >
                News
              </button>
              <button 
                onClick={() => setFilterType('CYBER')} 
                className={`flex-1 px-4 py-1.5 rounded-md text-sm font-medium transition-all ${filterType === 'CYBER' ? 'bg-slate-800 text-white shadow ring-1 ring-slate-700' : 'text-slate-400 hover:text-white'}`}
              >
                Cyber
              </button>
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              {/* Sort Dropdown */}
              <div className="relative flex-1 sm:flex-none">
                <select 
                  value={sortOption}
                  onChange={(e) => setSortOption(e.target.value as any)}
                  className="w-full sm:w-auto appearance-none bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 text-sm rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent block px-4 py-2 pr-8 outline-none transition-colors cursor-pointer"
                >
                  <option value="NEWEST">Date (Newest)</option>
                  <option value="OLDEST">Date (Oldest)</option>
                  <option value="RISK_HIGH">Risk (High to Low)</option>
                  <option value="RISK_LOW">Risk (Low to High)</option>
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-400">
                  <svg className="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                </div>
              </div>

              {/* Risk Calculation Tooltip */}
              <div className="relative group">
                <div className="w-9 h-9 rounded-lg bg-slate-800 hover:bg-slate-700 flex items-center justify-center cursor-help border border-slate-800 hover:border-slate-600 text-slate-400 transition-all">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                </div>
                
                <div className="absolute right-0 bottom-full mb-2 w-72 p-4 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl opacity-0 group-hover:opacity-100 transition-all duration-200 pointer-events-none z-50 text-xs text-slate-300 translate-y-2 group-hover:translate-y-0">
                  <h4 className="font-bold text-white mb-2 text-sm">Risk Score Calculation</h4>
                  <div className="space-y-2">
                    <div className="flex gap-2 items-start">
                       <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 uppercase tracking-wider mt-0.5">News</span>
                       <p>Inverted credibility score. <br/><span className="text-slate-500">Example: 10% Credible = 90% Risk</span></p>
                    </div>
                    <div className="border-t border-slate-800 my-2"></div>
                    <div className="flex gap-2 items-start">
                       <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 uppercase tracking-wider mt-0.5">Cyber</span>
                       <p>Mapped from threat level.<br/>
                       <span className="text-slate-500">Critical(100) &gt; High(75) &gt; Medium(50) &gt; Low(25) &gt; Safe(0)</span></p>
                    </div>
                  </div>
                  <div className="absolute -bottom-1.5 right-3.5 w-3 h-3 bg-slate-900 border-b border-r border-slate-700 transform rotate-45"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {filteredAndSortedHistory.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center animate-fade-in">
             <div className="w-16 h-16 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
             </div>
             <p className="text-slate-400 font-medium">No results found</p>
             <p className="text-sm text-slate-500 mt-1">Try adjusting your filters or run a new scan.</p>
          </div>
        ) : (
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden animate-fade-in shadow-sm">
            <div className="divide-y divide-slate-800/50">
              {filteredAndSortedHistory.map((item) => (
                <div key={item.id} className="p-4 hover:bg-slate-800/40 transition-colors flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center group">
                   <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-1.5">
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded tracking-wider ${item.type === 'NEWS' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'}`}>
                          {item.type === 'NEWS' ? 'FAKE NEWS' : 'CYBER SEC'}
                        </span>
                        <span className="text-xs text-slate-500 font-mono">{new Date(item.date).toLocaleString()}</span>
                      </div>
                      <p className="text-slate-200 text-sm font-medium truncate group-hover:text-white transition-colors pr-4">{item.summary}</p>
                   </div>
                   <div className={`px-3 py-1.5 rounded-lg text-xs font-bold border whitespace-nowrap shadow-sm ${getHistoryColor(item.type, item.result)}`}>
                     {item.result}
                   </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};