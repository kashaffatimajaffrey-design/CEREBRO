import React, { useState, useEffect } from 'react';
import { View } from './types';
import { Sidebar } from './components/Sidebar';
import { DashboardHome } from './components/DashboardHome';
import { NewsScanner } from './components/NewsScanner';
import { CyberMonitor } from './components/CyberMonitor';
import { EmailScanner } from './components/EmailScanner';
import { Auth } from './components/Auth';
import { Profile } from './components/Profile';
import { useAuth } from './context/AuthContext';
import { playCyberSFX } from './utils/audio';
import { Shield, Radio, Terminal, AlertTriangle, Play, RefreshCw } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>(View.DASHBOARD);
  const [systemColor, setSystemColor] = useState<'blue' | 'green' | 'purple'>('blue');
  const { user, loading } = useAuth();

  // Active theme classes for main HUD elements
  const themeClasses = {
    blue: {
      text: 'text-blue-400',
      border: 'border-blue-500/20',
      bgGlow: 'from-blue-950/20 via-slate-950 to-slate-950',
      gridColor: 'rgba(59, 130, 246, 0.04)',
      badge: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
      indicator: 'bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]',
    },
    green: {
      text: 'text-emerald-400',
      border: 'border-emerald-500/20',
      bgGlow: 'from-emerald-950/20 via-slate-950 to-slate-950',
      gridColor: 'rgba(16, 185, 129, 0.04)',
      badge: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
      indicator: 'bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]',
    },
    purple: {
      text: 'text-purple-400',
      border: 'border-purple-500/20',
      bgGlow: 'from-purple-950/20 via-slate-950 to-slate-950',
      gridColor: 'rgba(139, 92, 246, 0.04)',
      badge: 'bg-purple-500/10 text-purple-400 border border-purple-500/20',
      indicator: 'bg-purple-500 shadow-[0_0_10px_rgba(139,92,246,0.5)]',
    }
  };

  const style = themeClasses[systemColor];
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);

  // High-performance cyber grid and particle animation inside main dashboard
  useEffect(() => {
    if (!user) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    // Nodes definition
    const particleCount = 35;
    const particles: Array<{ x: number; y: number; vx: number; vy: number; radius: number }> = [];

    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        radius: Math.random() * 2 + 0.5,
      });
    }

    // Color mapper
    const getThemeRGB = () => {
      if (systemColor === 'green') return '16, 185, 129';
      if (systemColor === 'purple') return '139, 92, 246';
      return '59, 130, 246'; // default blue
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      const colorRGB = getThemeRGB();

      // 1. Draw connecting lines between close particles (constellation grid)
      ctx.lineWidth = 0.5;
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 140) {
            const opacity = (140 - dist) / 140 * 0.12;
            ctx.strokeStyle = `rgba(${colorRGB}, ${opacity})`;
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }
        }
      }

      // 2. Render and update particles
      particles.forEach((p) => {
        p.x += p.vx;
        p.y += p.vy;

        // Bounce on boundaries
        if (p.x < 0 || p.x > width) p.vx *= -1;
        if (p.y < 0 || p.y > height) p.vy *= -1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${colorRGB}, 0.35)`;
        ctx.fill();
      });

      animId = requestAnimationFrame(draw);
    };

    draw();

    const handleResize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
    };
  }, [user, systemColor]);

  // Trigger brief holographic sweep sounds on view navigation
  useEffect(() => {
    if (user) {
      playCyberSFX('click');
    }
  }, [currentView]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center space-y-4">
        {/* Holographic loading rings */}
        <div className="relative w-16 h-16">
          <div className="absolute inset-0 border-4 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
          <div className="absolute inset-2 border-4 border-emerald-500 border-b-transparent rounded-full animate-spin [animation-duration:1.5s] [animation-direction:reverse]"></div>
        </div>
        <p className="text-xs font-mono text-slate-500 tracking-widest animate-pulse">[ LINKING NEURAL DECRYPTION LAYER ]</p>
      </div>
    );
  }

  if (!user) {
    return <Auth />;
  }

  const renderContent = () => {
    switch (currentView) {
      case View.DASHBOARD:
        return <DashboardHome systemColor={systemColor} />;
      case View.NEWS_SCANNER:
        return <NewsScanner />;
      case View.CYBER_MONITOR:
        return <CyberMonitor />;
      case View.EMAIL_SCANNER:
        return <EmailScanner />;
      case View.PROFILE:
        return <Profile />;
      default:
        return <DashboardHome systemColor={systemColor} />;
    }
  };

  return (
    <div className={`flex min-h-screen bg-slate-950 text-slate-100 font-sans relative overflow-hidden transition-colors duration-1000 bg-gradient-to-b ${style.bgGlow}`}>
      
      {/* 1. Behind-Grid Dynamic Scanning Matrix Grid with active canvas particles */}
      <div 
        className="absolute inset-0 pointer-events-none z-0 opacity-80 animate-grid-move" 
        style={{
          backgroundImage: `
            linear-gradient(to right, ${style.gridColor} 1px, transparent 1px),
            linear-gradient(to bottom, ${style.gridColor} 1px, transparent 1px)
          `,
          backgroundSize: '32px 32px'
        }}
      />
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none z-0 brightness-[0.75]" />

      {/* 2. Global Laser Sweeping Scanline Overlay */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-slate-800/5 to-transparent pointer-events-none z-10 opacity-40">
        <div className="w-full h-[1px] bg-gradient-to-r from-transparent via-emerald-500/20 to-transparent absolute top-0 animate-scanline" />
      </div>

      {/* 3. Sidebar Menu */}
      <Sidebar 
        currentView={currentView} 
        setCurrentView={setCurrentView} 
        systemColor={systemColor} 
        setSystemColor={setSystemColor} 
      />
      
      {/* 4. Main HUD Stage */}
      <main className="ml-64 flex-1 p-8 h-screen overflow-y-auto relative z-10 custom-scrollbar flex flex-col justify-between">
        <div>
          {/* Main Cyber Header */}
          <header className="mb-8 flex justify-between items-center bg-slate-900/40 border border-slate-900 p-4 rounded-xl backdrop-blur-md relative overflow-hidden">
            
            {/* Ambient neon marker */}
            <div className={`absolute top-0 left-4 w-24 h-[2px] ${
              systemColor === 'green' ? 'bg-emerald-500' : systemColor === 'purple' ? 'bg-purple-500' : 'bg-blue-500'
            }`} />

            <div className="flex items-center gap-3">
              {/* Rotating radar pulse indicator */}
              <div className="relative w-3.5 h-3.5 flex items-center justify-center">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-60 ${style.indicator}`}></span>
                <span className={`relative inline-flex rounded-full h-2 w-2 ${style.indicator}`}></span>
              </div>
              
              <div>
                <h2 className="text-xl font-black text-white font-mono tracking-widest uppercase flex items-center gap-2">
                  {currentView === View.DASHBOARD && 'Dashboard Overview'}
                  {currentView === View.NEWS_SCANNER && 'Information Security'}
                  {currentView === View.CYBER_MONITOR && 'Network Security'}
                  {currentView === View.EMAIL_SCANNER && 'Workspace Security'}
                  {currentView === View.PROFILE && 'User Profile'}
                </h2>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] font-mono text-slate-500 tracking-wider">CEREBRO Threat Intelligence Terminal</span>
                  <span className="text-slate-700 font-mono text-[10px]">•</span>
                  <span className={`text-[9px] font-mono font-bold tracking-widest px-1.5 py-0.5 rounded ${style.badge}`}>
                    MODE: {systemColor.toUpperCase()}_ACTIVED
                  </span>
                </div>
              </div>
            </div>

            {/* Analyst Credentials Indicator */}
            <div className="flex items-center gap-3.5 font-mono">
               <div className="text-right hidden xl:block">
                 <p className="text-xs font-bold text-white tracking-wider">{user.name}</p>
                 <p className="text-[9px] text-slate-500 flex items-center gap-1 justify-end">
                   <Terminal className="w-3 h-3 text-slate-600" />
                   Security Analyst
                 </p>
               </div>
               
               <button 
                  onClick={() => setCurrentView(View.PROFILE)}
                  onMouseEnter={() => playCyberSFX('hover')}
                  className={`w-10 h-10 rounded-full border bg-slate-950 hover:bg-slate-900 transition-all text-sm font-bold text-white flex items-center justify-center relative cursor-pointer group ${style.border}`}
               >
                 <div className="absolute -inset-1 rounded-full bg-slate-800/10 opacity-0 group-hover:opacity-100 transition-opacity blur-sm" />
                 {user.name.charAt(0).toUpperCase()}
               </button>
            </div>
          </header>
          
          {/* Main Dynamic Viewport Mount */}
          <div className="relative">
            <AnimatePresence mode="wait">
              <motion.div
                key={currentView}
                initial={{ opacity: 0, scale: 0.98, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98, y: -10 }}
                transition={{ duration: 0.28, ease: 'easeInOut' }}
              >
                {renderContent()}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>

        {/* Floating tactical status panel at footer */}
        <footer className="mt-8 pt-4 border-t border-slate-900/60 flex flex-col md:flex-row md:items-center justify-between text-[9px] font-mono text-slate-600 gap-4">
          <div className="flex items-center gap-4 flex-wrap">
            <span>[ SYSTEM: OPERATIONAL ]</span>
            <span>[ BANDWIDTH: 248.6 TB/S ]</span>
            <span>[ LATENCY: 12ms ]</span>
            <span className="text-emerald-500 animate-pulse">[ SECURE ENCRYPTED NODE CONNECTION ]</span>
          </div>
          <div>
            <span>© CEREBRO TACTICAL INTEL AGENT CORES 2026</span>
          </div>
        </footer>
      </main>
    </div>
  );
};

export default App;
