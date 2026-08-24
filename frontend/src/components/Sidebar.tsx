import React, { useState } from 'react';
import { View } from '../types';
import { useAuth } from '../context/AuthContext';
import { playCyberSFX, toggleMute, getMuteStatus } from '../utils/audio';
import { Shield, Volume2, VolumeX, Disc, Cpu, Activity, Radio } from 'lucide-react';
import { motion } from 'motion/react';

interface SidebarProps {
  currentView: View;
  setCurrentView: (view: View) => void;
  systemColor: 'blue' | 'green' | 'purple';
  setSystemColor: (color: 'blue' | 'green' | 'purple') => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  setCurrentView,
  systemColor,
  setSystemColor,
}) => {
  const { user } = useAuth();
  const [isMuted, setIsMuted] = useState(getMuteStatus());
  const [isDialRotating, setIsDialRotating] = useState(false);

  const themeColors = {
    blue: {
      text: 'text-blue-400',
      border: 'border-blue-500/20',
      activeBg:
        'bg-blue-600/10 text-blue-400 border border-blue-600/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]',
      accentGlow: 'shadow-[0_0_20px_rgba(59,130,246,0.15)]',
      brandColor: 'bg-blue-600',
      coreGlow: 'bg-blue-500 shadow-sm shadow-blue-500/50',
    },
    green: {
      text: 'text-emerald-400',
      border: 'border-emerald-500/20',
      activeBg:
        'bg-emerald-600/10 text-emerald-400 border border-emerald-600/20 shadow-[0_0_15px_rgba(16,185,129,0.1)]',
      accentGlow: 'shadow-[0_0_20px_rgba(16,185,129,0.15)]',
      brandColor: 'bg-emerald-600',
      coreGlow: 'bg-emerald-500 shadow-sm shadow-emerald-500/50',
    },
    purple: {
      text: 'text-purple-400',
      border: 'border-purple-500/20',
      activeBg:
        'bg-purple-600/10 text-purple-400 border border-purple-600/20 shadow-[0_0_15px_rgba(139,92,246,0.1)]',
      accentGlow: 'shadow-[0_0_20px_rgba(139,92,246,0.15)]',
      brandColor: 'bg-purple-600',
      coreGlow: 'bg-purple-500 shadow-sm shadow-purple-500/50',
    },
  };

  const style = themeColors[systemColor];

  const menuItems = [
    {
      id: View.DASHBOARD,
      label: 'Dashboard',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
          />
        </svg>
      ),
    },
    {
      id: View.NEWS_SCANNER,
      label: 'Fake News Detector',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"
          />
        </svg>
      ),
    },
    {
      id: View.CYBER_MONITOR,
      label: 'Cyber Threat Monitor',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
          />
        </svg>
      ),
    },
    {
      id: View.EMAIL_SCANNER,
      label: 'Gmail Intel Scanner',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
          />
        </svg>
      ),
    },
    {
      id: View.PROFILE,
      label: 'My Profile',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
          />
        </svg>
      ),
    },
  ];

  const handleMuteToggle = () => {
    const muted = toggleMute();
    setIsMuted(muted);
  };

  const handleDialClick = () => {
    setIsDialRotating(true);
    playCyberSFX('omnitrix');

    // Cycle theme colors: blue -> green -> purple -> blue
    const nextColors: Record<'blue' | 'green' | 'purple', 'blue' | 'green' | 'purple'> = {
      blue: 'green',
      green: 'purple',
      purple: 'blue',
    };
    setSystemColor(nextColors[systemColor]);

    setTimeout(() => {
      setIsDialRotating(false);
    }, 1200);
  };

  const handleMenuClick = (id: View) => {
    playCyberSFX('click');
    setCurrentView(id);
  };

  return (
    <div className="w-64 bg-slate-950 border-r border-slate-900/80 flex flex-col h-full fixed left-0 top-0 z-20 shadow-2xl relative overflow-hidden">
      {/* Background cyber grid effect */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900/40 via-slate-950 to-slate-950 pointer-events-none" />

      {/* 1. Header & Logo */}
      <div className="p-6 border-b border-slate-900/60 flex items-center justify-between relative z-10">
        <div className="flex items-center gap-2.5">
          <motion.div
            animate={{ rotate: [0, 360] }}
            transition={{ repeat: Infinity, duration: 15, ease: 'linear' }}
            className={`w-8 h-8 ${style.brandColor} rounded-lg flex items-center justify-center border border-white/10 ${style.accentGlow}`}
          >
            <Shield className="w-4 h-4 text-white" />
          </motion.div>
          <div>
            <h1 className="text-base font-extrabold text-white tracking-widest font-mono">
              CEREBRO
            </h1>
            <span className="text-[8px] text-slate-500 font-mono tracking-wider uppercase">
              [ LVL_10_CLEARANCE ]
            </span>
          </div>
        </div>

        {/* Tactical sound toggle */}
        <button
          onClick={handleMuteToggle}
          onMouseEnter={() => playCyberSFX('hover')}
          className="p-1.5 rounded-md border border-slate-800 bg-slate-950/40 text-slate-500 hover:text-white hover:border-slate-700 transition-all cursor-pointer"
          title={isMuted ? 'Unmute tactical SFX' : 'Mute tactical SFX'}
        >
          {isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* 2. Menu Navigation */}
      <nav className="flex-1 p-4 space-y-1.5 relative z-10 overflow-y-auto custom-scrollbar">
        {menuItems.map((item) => {
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => handleMenuClick(item.id)}
              onMouseEnter={() => playCyberSFX('hover')}
              className={`w-full flex items-center gap-3.5 px-4 py-3 rounded-lg transition-all duration-300 font-mono text-xs cursor-pointer group border ${
                isActive
                  ? style.activeBg
                  : 'text-slate-400 border-transparent hover:bg-slate-900/40 hover:text-slate-200 hover:border-slate-800/40'
              }`}
            >
              <div
                className={`transition-transform duration-300 group-hover:scale-110 ${isActive ? style.text : 'text-slate-500 group-hover:text-slate-300'}`}
              >
                {item.icon}
              </div>
              <span className="font-semibold tracking-wider">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* 3. Omnitrix core dial widget in the sidebar */}
      <div className="p-4 border-t border-slate-900/60 bg-slate-950/30 relative z-10 flex flex-col items-center">
        <div className="text-[8px] font-mono tracking-widest text-slate-500 uppercase mb-3 flex items-center gap-1.5 font-bold">
          <Radio className="w-2.5 h-2.5 animate-pulse text-emerald-500" />
          Omnitrix Core Dial
        </div>

        <div className="relative w-36 h-36 flex items-center justify-center">
          {/* Outer rotating holographic gear */}
          <div
            className={`absolute inset-0 border border-dashed rounded-full ${
              systemColor === 'green'
                ? 'border-emerald-500/30'
                : systemColor === 'purple'
                  ? 'border-purple-500/30'
                  : 'border-blue-500/30'
            } ${isDialRotating ? 'animate-omnitrix-spin-fast' : 'animate-omnitrix-spin-slow'}`}
          />

          {/* Secondary rotating notched ring */}
          <div
            className={`absolute inset-2 border-2 border-dotted rounded-full scale-95 opacity-50 ${
              systemColor === 'green'
                ? 'border-emerald-500/40'
                : systemColor === 'purple'
                  ? 'border-purple-500/40'
                  : 'border-blue-500/40'
            } ${isDialRotating ? 'animate-omnitrix-spin-slow' : 'animate-omnitrix-spin-fast'}`}
          />

          {/* Central clickable core glass plate */}
          <button
            onClick={handleDialClick}
            onMouseEnter={() => playCyberSFX('hover')}
            className={`w-24 h-24 rounded-full bg-slate-950 border-4 relative overflow-hidden group cursor-pointer shadow-2xl flex flex-col items-center justify-center transition-all duration-300 ${
              systemColor === 'green'
                ? 'border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.2)] hover:border-emerald-400'
                : systemColor === 'purple'
                  ? 'border-purple-500/60 shadow-[0_0_20px_rgba(139,92,246,0.2)] hover:border-purple-400'
                  : 'border-blue-500/60 shadow-[0_0_20px_rgba(59,130,246,0.2)] hover:border-blue-400'
            }`}
          >
            {/* Spinning background lines */}
            <div
              className={`absolute inset-0 opacity-20 pointer-events-none group-hover:opacity-40 transition-opacity bg-radial-lines ${
                isDialRotating
                  ? 'animate-spin [animation-duration:1s]'
                  : 'animate-spin [animation-duration:8s]'
              }`}
              style={{
                backgroundImage:
                  'repeating-conic-gradient(from 0deg, #fff 0deg 10deg, transparent 10deg 20deg)',
              }}
            />

            {/* Pulsing center green core */}
            <div
              className={`w-3.5 h-3.5 rounded-full absolute ${style.coreGlow} ${isDialRotating ? 'scale-150' : 'animate-pulse'}`}
            />

            {/* Omnitrix icon wings / overlays */}
            <div
              className={`absolute w-12 h-1 ${systemColor === 'green' ? 'bg-emerald-500/30' : systemColor === 'purple' ? 'bg-purple-500/30' : 'bg-blue-500/30'} rotate-45 pointer-events-none`}
            />
            <div
              className={`absolute w-12 h-1 ${systemColor === 'green' ? 'bg-emerald-500/30' : systemColor === 'purple' ? 'bg-purple-500/30' : 'bg-blue-500/30'} -rotate-45 pointer-events-none`}
            />

            {/* Interactive labels */}
            <span className="text-[7px] font-mono text-slate-500 font-bold uppercase tracking-widest absolute bottom-4">
              {systemColor.toUpperCase()}
            </span>
            <span className="text-[6px] font-mono text-slate-600 tracking-widest absolute top-4 uppercase">
              {isDialRotating ? 'SYNCING' : 'READY'}
            </span>
          </button>
        </div>

        <p className="text-[7px] font-mono text-slate-600 text-center uppercase tracking-wider mt-1.5 select-none max-w-[120px]">
          Click center plate to rotate dial & recalibrate interface theme
        </p>
      </div>

      {/* 4. Footer Identity */}
      <div className="p-4 border-t border-slate-900/60 bg-slate-950/40 relative z-10">
        <div className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-900/30 border border-slate-800/60">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-slate-800 to-slate-950 border border-slate-700/60 flex items-center justify-center text-xs font-bold text-slate-300">
            {user?.name?.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 overflow-hidden font-mono">
            <p className="text-xs font-bold text-white truncate">{user?.name}</p>
            <p className="text-[8px] text-slate-500 truncate">{user?.email}</p>
          </div>
        </div>
      </div>
    </div>
  );
};
