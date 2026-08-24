import React from 'react';
import { motion } from 'motion/react';

interface StatCardProps {
  title: string;
  value: string | number;
  change?: string;
  isPositive?: boolean;
  icon: React.ReactNode;
  color: 'blue' | 'red' | 'green' | 'purple';
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  change,
  isPositive,
  icon,
  color,
}) => {
  // Map standard colors to amazing cyber glow configurations
  const themeClasses = {
    blue: {
      border: 'border-blue-500/20 hover:border-blue-500/50',
      text: 'text-blue-400',
      iconBg:
        'bg-blue-950/80 text-blue-400 border border-blue-500/30 shadow-[0_0_15px_rgba(59,130,246,0.1)]',
      glow: 'shadow-[0_0_20px_rgba(59,130,246,0.05)] hover:shadow-[0_0_30px_rgba(59,130,246,0.25)]',
      accent: 'bg-blue-500/40',
      line: 'bg-gradient-to-r from-transparent via-blue-500 to-transparent',
    },
    red: {
      border: 'border-red-500/20 hover:border-red-500/50',
      text: 'text-red-400',
      iconBg:
        'bg-red-950/80 text-red-400 border border-red-500/30 shadow-[0_0_15px_rgba(239,68,68,0.1)]',
      glow: 'shadow-[0_0_20px_rgba(239,68,68,0.05)] hover:shadow-[0_0_30px_rgba(239,68,68,0.25)]',
      accent: 'bg-red-500/40',
      line: 'bg-gradient-to-r from-transparent via-red-500 to-transparent',
    },
    green: {
      border: 'border-emerald-500/20 hover:border-emerald-500/50',
      text: 'text-emerald-400',
      iconBg:
        'bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.1)]',
      glow: 'shadow-[0_0_20px_rgba(16,185,129,0.05)] hover:shadow-[0_0_30px_rgba(16,185,129,0.25)]',
      accent: 'bg-emerald-500/40',
      line: 'bg-gradient-to-r from-transparent via-emerald-500 to-transparent',
    },
    purple: {
      border: 'border-purple-500/20 hover:border-purple-500/50',
      text: 'text-purple-400',
      iconBg:
        'bg-purple-950/80 text-purple-400 border border-purple-500/30 shadow-[0_0_15px_rgba(139,92,246,0.1)]',
      glow: 'shadow-[0_0_20px_rgba(139,92,246,0.05)] hover:shadow-[0_0_30px_rgba(139,92,246,0.25)]',
      accent: 'bg-purple-500/40',
      line: 'bg-gradient-to-r from-transparent via-purple-500 to-transparent',
    },
  };

  const config = themeClasses[color];

  return (
    <motion.div
      whileHover={{ y: -6, scale: 1.02 }}
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className={`p-6 rounded-xl border bg-slate-950/70 backdrop-blur-md relative overflow-hidden transition-all duration-300 group cursor-pointer ${config.border} ${config.glow}`}
    >
      {/* Dynamic Scanline Sweeper inside the card */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-slate-500/5 to-transparent opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-300">
        <div className={`w-full h-[1px] ${config.accent} absolute top-0 animate-scanline`} />
      </div>

      {/* Futuristic floating coordinate marker */}
      <div className="absolute top-2 right-3 text-[7px] font-mono text-slate-600 tracking-widest select-none pointer-events-none opacity-40 group-hover:opacity-80 transition-opacity"></div>

      <div className="flex justify-between items-start relative z-10">
        <div className="space-y-1">
          <p className="text-slate-500 text-[10px] font-mono uppercase tracking-widest flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full ${color === 'green' ? 'bg-emerald-500' : color === 'red' ? 'bg-red-500' : color === 'purple' ? 'bg-purple-500' : 'bg-blue-500'} animate-ping`}
            ></span>
            {title}
          </p>
          <h3 className="text-3xl font-extrabold text-white tracking-tight font-mono mt-1 group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-white group-hover:to-slate-300 transition-colors duration-300">
            {value}
          </h3>
        </div>

        {/* Rotating Radar Rings behind the Icon */}
        <div className="relative">
          <div className="absolute -inset-1 rounded-full bg-slate-800/20 blur opacity-40 group-hover:opacity-100 group-hover:bg-slate-700/30 transition-all duration-300" />
          <div className="absolute inset-0 border border-dashed border-slate-700 rounded-full animate-spin [animation-duration:12s] scale-125 opacity-0 group-hover:opacity-100 transition-opacity" />
          <div
            className={`p-3.5 rounded-lg relative ${config.iconBg} transition-transform duration-300 group-hover:scale-110`}
          >
            {icon}
          </div>
        </div>
      </div>

      {change && (
        <div className="mt-4 flex items-center justify-between text-[11px] relative z-10 border-t border-slate-900/60 pt-3">
          <div className="flex items-center gap-1.5 font-mono">
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                isPositive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-red-500/10 text-red-400 border border-red-500/20'
              }`}
            >
              {isPositive ? '▲' : '▼'} {change}
            </span>
            <span className="text-slate-500">variance index</span>
          </div>

          <span className="text-[9px] font-mono text-slate-600 tracking-wider"></span>
        </div>
      )}

      {/* Cyber edge glow slider line at the bottom */}
      <div
        className={`absolute bottom-0 left-0 right-0 h-[2px] w-full ${config.line} opacity-40 group-hover:opacity-100 transition-opacity`}
      />
    </motion.div>
  );
};
