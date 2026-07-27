import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { motion, AnimatePresence } from 'motion/react';

// Decrypted text scrambler component for that elite sci-fi feel
const CyberText: React.FC<{ text: string; delay?: number; speed?: number }> = ({ text, delay = 0, speed = 30 }) => {
  const [displayText, setDisplayText] = useState('');
  
  useEffect(() => {
    let isMounted = true;
    const chars = '01#$X%&*_+<>{}[]¥%@';
    let iterations = 0;
    
    const timeout = setTimeout(() => {
      const interval = setInterval(() => {
        if (!isMounted) return;
        
        setDisplayText(
          text
            .split('')
            .map((char, index) => {
              if (index < iterations) {
                return text[index];
              }
              if (char === ' ') return ' ';
              return chars[Math.floor(Math.random() * chars.length)];
            })
            .join('')
        );
        
        if (iterations >= text.length) {
          clearInterval(interval);
        }
        iterations += 1 / 2; // Settle speed
      }, speed);
      
      return () => clearInterval(interval);
    }, delay);

    return () => {
      isMounted = false;
      clearTimeout(timeout);
    };
  }, [text, delay, speed]);

  return <span>{displayText || text}</span>;
};

// Interface for Theme properties 
interface CyberTheme {
  name: string;
  id: string;
  primary: string; // Tailwind class
  accent: string;  // Tailwind text/border hover
  glow: string;    // Shadow color
  bgGlow: string;  // Background overlay gradient color
  textColor: string;
  canvasColor: string; // RGB values for canvas loop
}

const CYBER_THEMES: CyberTheme[] = [
  {
    name: 'Neon Cyan',
    id: 'cyan',
    primary: 'border-cyan-500 text-cyan-400 focus:ring-cyan-500 bg-cyan-950/20',
    accent: 'text-cyan-400 hover:text-cyan-300 border-cyan-500/30 hover:border-cyan-400 bg-cyan-950/30',
    glow: 'shadow-cyan-500/20',
    bgGlow: 'from-cyan-950/20 via-slate-950 to-slate-950',
    textColor: 'text-cyan-400',
    canvasColor: '6, 182, 212',
  },
  {
    name: 'Matrix Code',
    id: 'green',
    primary: 'border-emerald-500 text-emerald-400 focus:ring-emerald-500 bg-emerald-950/20',
    accent: 'text-emerald-400 hover:text-emerald-300 border-emerald-500/30 hover:border-emerald-400 bg-emerald-950/30',
    glow: 'shadow-emerald-500/20',
    bgGlow: 'from-emerald-950/20 via-slate-950 to-slate-950',
    textColor: 'text-emerald-400',
    canvasColor: '16, 185, 129',
  },
  {
    name: 'Quantum Violet',
    id: 'purple',
    primary: 'border-purple-500 text-purple-400 focus:ring-purple-500 bg-purple-950/20',
    accent: 'text-purple-400 hover:text-purple-300 border-purple-500/30 hover:border-purple-400 bg-purple-950/30',
    glow: 'shadow-purple-500/20',
    bgGlow: 'from-purple-950/20 via-slate-950 to-slate-950',
    textColor: 'text-purple-400',
    canvasColor: '139, 92, 246',
  },
  {
    name: 'Infected Crimson',
    id: 'red',
    primary: 'border-rose-500 text-rose-400 focus:ring-rose-500 bg-rose-950/20',
    accent: 'text-rose-400 hover:text-rose-300 border-rose-500/30 hover:border-rose-400 bg-rose-950/30',
    glow: 'shadow-rose-500/20',
    bgGlow: 'from-rose-950/25 via-slate-950 to-slate-950',
    textColor: 'text-rose-400',
    canvasColor: '244, 63, 94',
  },
];

export const Auth: React.FC = () => {
  const [isLogin, setIsLogin] = useState(true);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login, signup, loginWithGoogle } = useAuth();

  // Audio configuration
  const [audioEnabled, setAudioEnabled] = useState(false);
  
  // Theme state (default is Neon Cyan)
  const [theme, setTheme] = useState<CyberTheme>(CYBER_THEMES[0]);
  
  // Holographic Terminal Simulation
  const [isDecrypting, setIsDecrypting] = useState(false);
  const [decryptionProgress, setDecryptionProgress] = useState(0);
  const [decryptLogs, setDecryptLogs] = useState<string[]>([]);
  
  // Parallax tracking
  const [mousePos, setMousePos] = useState({ x: 0, y: 0, rawX: 0, rawY: 0 });
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Sound Synthesizer via Web Audio API (creates retro sine waves, alerts, and access sweep sounds on demand)
  const playSFX = (type: 'hover' | 'success' | 'error' | 'switch' | 'keyboard') => {
    if (!audioEnabled) return;
    try {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);

      if (type === 'hover') {
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(1000, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.015, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.04);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.04);
      } else if (type === 'keyboard') {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(700 + Math.random() * 500, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.01, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.02);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.02);
      } else if (type === 'switch') {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(440, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.1);
        gain.gain.setValueAtTime(0.02, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.1);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.1);
      } else if (type === 'error') {
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(180, audioCtx.currentTime);
        osc.frequency.linearRampToValueAtTime(90, audioCtx.currentTime + 0.35);
        gain.gain.setValueAtTime(0.04, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.35);
        
        // Parallel alert chime
        const extraOsc = audioCtx.createOscillator();
        const extraGain = audioCtx.createGain();
        extraOsc.type = 'triangle';
        extraOsc.frequency.setValueAtTime(360, audioCtx.currentTime);
        extraOsc.frequency.linearRampToValueAtTime(420, audioCtx.currentTime + 0.35);
        extraOsc.connect(extraGain);
        extraGain.connect(audioCtx.destination);
        extraGain.gain.setValueAtTime(0.03, audioCtx.currentTime);
        extraGain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.35);

        osc.start();
        osc.stop(audioCtx.currentTime + 0.35);
        extraOsc.start();
        extraOsc.stop(audioCtx.currentTime + 0.35);
      } else if (type === 'success') {
        // Futuristic dual-oscillator musical sweep
        const freqs = [392.00, 523.25, 659.25, 783.99, 1046.50]; // G4, C5, E5, G5, C6
        freqs.forEach((freq, idx) => {
          const oscNode = audioCtx.createOscillator();
          const gainNode = audioCtx.createGain();
          oscNode.type = 'sine';
          oscNode.frequency.setValueAtTime(freq, audioCtx.currentTime + idx * 0.08);
          oscNode.connect(gainNode);
          gainNode.connect(audioCtx.destination);
          gainNode.gain.setValueAtTime(0.025, audioCtx.currentTime + idx * 0.08);
          gainNode.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + idx * 0.08 + 0.3);
          oscNode.start(audioCtx.currentTime + idx * 0.08);
          oscNode.stop(audioCtx.currentTime + idx * 0.08 + 0.3);
        });
      }
    } catch (e) {
      console.warn("Virtual synthesizer blocked", e);
    }
  };

  // Parallax updates on mouse move
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const x = (e.clientX - window.innerWidth / 2) / (window.innerWidth / 2);
      const y = (e.clientY - window.innerHeight / 2) / (window.innerHeight / 2);
      setMousePos({ x, y, rawX: e.clientX, rawY: e.clientY });
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  // Cyber Canvas Matrix & Starfield effect backdrops
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    // Matrix columns / particle configs
    const columns = Math.floor(width / 24);
    const drops: number[] = Array(columns).fill(0);
    const particles: Array<{ x: number; y: number; speedX: number; speedY: number; radius: number; color: string }> = [];

    // Create custom constellation points for Cyan/Violet themes
    for (let i = 0; i < 45; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        speedX: (Math.random() - 0.5) * 0.6,
        speedY: (Math.random() - 0.5) * 0.6,
        radius: Math.random() * 2 + 0.5,
        color: `rgba(${theme.canvasColor}, ${Math.random() * 0.5 + 0.1})`,
      });
    }

    const draw = () => {
      // 1. Semi-transparent wash for trailing ghosts
      ctx.fillStyle = 'rgba(2, 6, 23, 0.15)';
      ctx.fillRect(0, 0, width, height);

      // 2. Draw Digital constellation background for Cyan, Purple themes
      if (theme.id !== 'green') {
        particles.forEach((p) => {
          p.x += p.speedX;
          p.y += p.speedY;

          // Parallax mouse interaction (warp particles slightly away from cursor)
          const dx = mousePos.rawX - p.x;
          const dy = mousePos.rawY - p.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 180) {
            const force = (180 - dist) / 180;
            p.x -= (dx / dist) * force * 1.5;
            p.y -= (dy / dist) * force * 1.5;
          }

          if (p.x < 0 || p.x > width) p.speedX *= -1;
          if (p.y < 0 || p.y > height) p.speedY *= -1;

          ctx.beginPath();
          ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${theme.canvasColor}, ${p.radius > 1.5 ? 0.4 : 0.2})`;
          ctx.shadowBlur = 4;
          ctx.shadowColor = `rgb(${theme.canvasColor})`;
          ctx.fill();
          ctx.shadowBlur = 0;
        });

        // Live Grid Overlay
        ctx.strokeStyle = `rgba(${theme.canvasColor}, 0.03)`;
        ctx.lineWidth = 1;
        const gridSize = 50;
        // Apply slight offset based on mouse parallax
        const offsetX = mousePos.x * 12;
        const offsetY = mousePos.y * 12;

        ctx.beginPath();
        for (let x = offsetX % gridSize; x < width; x += gridSize) {
          ctx.moveTo(x, 0);
          ctx.lineTo(x, height);
        }
        for (let y = offsetY % gridSize; y < height; y += gridSize) {
          ctx.moveTo(0, y);
          ctx.lineTo(width, y);
        }
        ctx.stroke();

      } else {
        // 3. Pure Green Cyber Matrix Rain
        ctx.font = '15px monospace';
        ctx.fillStyle = `rgba(${theme.canvasColor}, 0.85)`;
        ctx.shadowBlur = 8;
        ctx.shadowColor = `rgb(${theme.canvasColor})`;

        for (let i = 0; i < drops.length; i++) {
          const text = String.fromCharCode(33 + Math.floor(Math.random() * 33));
          const x = i * 24;
          const y = drops[i] * 24;

          // Randomize character opacities
          ctx.fillText(text, x, y);

          if (y > height && Math.random() > 0.975) {
            drops[i] = 0;
          }
          drops[i]++;
        }
        ctx.shadowBlur = 0;
      }

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
  }, [theme, mousePos.rawX, mousePos.rawY]);

  const triggerDecryptionSim = (targetName: string, targetEmail: string) => {
    setIsDecrypting(true);
    setDecryptionProgress(0);
    setDecryptLogs([]);
    playSFX('switch');

    const milestones = [
      { prg: 5, log: 'Establishing secure channel...' },
      { prg: 15, log: '🧬 ALLOCATING CACHE LINES & DIRECT MEMORY BUFFERS...' },
      { prg: 30, log: 'Connected to CEREBRO API' },
      { prg: 45, log: 'Verifying credentials...' },
      { prg: 60, log: `🛡️ VERIFYING AUTH KEY FOR ANALYST: [${targetName.toUpperCase() || 'ANALYST_SEC_01'}]` },
      { prg: 78, log: '🛸 MOUNTING CEREBRO COGNITIVE NEURAL GRAPH...' },
      { prg: 90, log: '⚡ GEMINI MODELS SECURED AND PRE-HEATED FOR INFERENCE' },
      { prg: 97, log: '💾 DECRYPTING ANALYST DATABASES... COMPLETE' },
      { prg: 100, log: '🚀 ACCESS CONFIRMED. REDIRECTING ENCRYPTED SHELL...' },
    ];

    let currentPrg = 0;
    const interval = setInterval(() => {
      const step = Math.floor(Math.random() * 4) + 2;
      currentPrg = Math.min(100, currentPrg + step);
      setDecryptionProgress(currentPrg);
      playSFX('keyboard');

      const triggerMilestone = milestones.find(m => currentPrg >= m.prg);
      if (triggerMilestone && currentPrg < 100) {
        setDecryptLogs(prev => {
          if (!prev.includes(triggerMilestone.log)) {
            return [...prev, triggerMilestone.log];
          }
          return prev;
        });
      }

      if (currentPrg >= 100) {
        clearInterval(interval);
        setDecryptLogs(prev => [...prev, '🚀 ACCESS CONFIRMED. REDIRECTING ENCRYPTED SHELL...']);
        playSFX('success');

        // Execute asynchronous credential verification on completion
        setTimeout(async () => {
          try {
            if (isLogin) {
              await login(email, password);
            } else {
              await signup(name, email, password);
            }
          } catch (err: any) {
            playSFX('error');
            setError(err.message || 'Signature alignment failure.');
            setIsDecrypting(false);
            setLoading(false);
          }
        }, 1200);
      }
    }, 70);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (!email || !password) {
        throw new Error('CORRUPTING SIGNATURE: Identity indices are blank.');
      }
      if (!isLogin && !name) {
        throw new Error('REGISTRATION UNRESOLVED: Analyst Identity is required.');
      }
      // Authenticate FIRST. The previous build ran a ~5 second "decryption"
      // animation and only called login() after it finished, so an invalid
      // password produced several seconds of ACCESS CONFIRMED before failing.
      if (isLogin) {
        await login(email, password);
      } else {
        await signup(name, email, password);
      }
      playSFX('success');
      setLoading(false);
    } catch (err: any) {
      playSFX('error');
      setError(err.message || 'Intrusion Countermeasures triggered. Verification failed.');
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    setError('');
    setLoading(true);
    try {
      await loginWithGoogle();
    } catch (err: any) {
      playSFX('error');
      setError(err.message || 'Secure Identity Exchange handshake disrupted.');
      setLoading(false);
    }
  };

  return (
    <div className={`min-h-screen relative flex items-center justify-center bg-slate-950 p-6 overflow-hidden select-none bg-gradient-to-b ${theme.bgGlow} transition-colors duration-1000`}>
      {/* 1. Behind-Grid Infinite Canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none z-0 brightness-[0.7]" />

      {/* 2. Scanning CRT scanlines overhead filter */}
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(circle_at_50%_50%,rgba(0,0,0,0)_50%,rgba(0,0,0,0.45)_100%)] z-10" />
      <div 
        className="absolute inset-0 pointer-events-none z-10 opacity-[0.035]"
        style={{
          backgroundImage: `repeating-linear-gradient(0deg, #000, #000 2px, transparent 2px, transparent 4px)`
        }}
      />

      {/* 3. Global Audio Synth + Theme Selector bar in the header */}
      <div className="absolute top-6 left-6 right-6 flex items-center justify-between z-20">
        {/* Synthetic Chime Controller */}
        <button
          onClick={() => {
            setAudioEnabled(!audioEnabled);
            setAudioEnabled((next) => {
              if (next) {
                // Initialize audio context safely by firing immediate success sweep
                try {
                  const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
                  const osc = audioCtx.createOscillator();
                  const gain = audioCtx.createGain();
                  osc.connect(gain);
                  gain.connect(audioCtx.destination);
                  osc.frequency.setValueAtTime(800, audioCtx.currentTime);
                  gain.gain.setValueAtTime(0.015, audioCtx.currentTime);
                  gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.1);
                  osc.start();
                  osc.stop(audioCtx.currentTime + 0.1);
                } catch {}
              }
              return next;
            });
          }}
          className={`px-4 py-2 rounded-lg border text-xs font-mono tracking-wider flex items-center gap-3 transition-all duration-300 ${
            audioEnabled 
              ? `${theme.textColor} border-current bg-white/5 shadow-lg ${theme.glow}`
              : 'text-slate-500 border-slate-800 bg-slate-950 hover:text-slate-300 hover:border-slate-700'
          }`}
        >
          {audioEnabled ? (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-ping inline-block" />
              🔊 SYSTEM SYNTH APU: ACTIVE
            </>
          ) : (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-slate-600 inline-block" />
              🔇 SYSTEM SYNTH APU: OFF
            </>
          )}
        </button>

        {/* Floating coordinate display */}
        <div className="hidden lg:block font-mono text-[10px] text-slate-500 tracking-widest bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800/80">
          GRID_COORD X: <span className={theme.textColor}>{(mousePos.x * 500).toFixed(0)}</span> Y: <span className={theme.textColor}>{(mousePos.y * 500).toFixed(0)}</span> | MATRIX STATE: SECURE
        </div>

        {/* Dynamic theme switching palette */}
        <div className="flex items-center gap-2 bg-slate-900/40 p-1.5 rounded-xl border border-slate-800/85">
          {CYBER_THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setTheme(t);
                playSFX('switch');
              }}
              title={t.name}
              className={`w-6 h-6 rounded-lg transition-transform hover:scale-110 relative flex items-center justify-center ${
                t.id === 'cyan' ? 'bg-cyan-500' :
                t.id === 'green' ? 'bg-emerald-500' :
                t.id === 'purple' ? 'bg-purple-500' : 'bg-rose-500'
              }`}
            >
              {theme.id === t.id && (
                <span className="w-2 h-2 rounded-full bg-slate-950 animate-pulse animate-ping" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 4. Left-hand Floating Cyber Monitor Widget (Parallax drifted) */}
      <div 
        className="hidden xl:flex absolute left-12 w-64 flex-col bg-slate-900/40 border border-slate-800/80 rounded-xl p-5 font-mono text-[11px] gap-4 pointer-events-none z-10 select-none shadow-2xl backdrop-blur-md transition-transform duration-300 ease-out"
        style={{
          transform: `perspective(1000px) translateY(${mousePos.y * 20}px) translateX(${mousePos.x * -15}px) rotateY(${mousePos.x * 4}deg)`,
        }}
      >
        <div className="flex items-center justify-between border-b border-slate-850 pb-2">
          <span className={`text-[10px] tracking-widest ${theme.textColor} font-bold`}>[SEC_ANALYSIS_STREAM]</span>
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
        </div>
        <div className="space-y-2 max-h-48 overflow-hidden text-slate-400">
          <p className="truncate"><span className="text-slate-600">11:32:04</span> IP 192.168.0.1 blocked - SYN Flood</p>
          <p className="truncate"><span className="text-slate-600">11:32:19</span> NLP Scan complete: Fake ratio 12%</p>
          <p className="truncate"><span className="text-slate-600">11:33:01</span> Cognitive Node [GEMINI] ping 43ms</p>
          <p className="truncate"><span className="text-slate-600">11:34:42</span> Security firewall sandbox: ONLINE</p>
          <p className="truncate"><span className="text-slate-600">11:35:10</span> Thread 0x7FFA89B deployed</p>
          <p className="truncate"><span className="text-slate-600">11:35:28</span> Cerebro memory footprint optimized</p>
        </div>
        <div className="border-t border-slate-850 pt-2 flex justify-between text-[10px] text-slate-500">
          <span>PORT: 3000/TCP</span>
          <span className="animate-pulse">ONLINE</span>
        </div>
      </div>

      {/* 5. Right-hand Floating Space Locator Widget (Parallax drifted in opposite vector) */}
      <div 
        className="hidden xl:flex absolute right-12 w-64 flex-col bg-slate-900/40 border border-slate-800/80 rounded-xl p-5 font-mono text-[11px] items-center pointer-events-none z-10 select-none shadow-2xl backdrop-blur-md transition-transform duration-300 ease-out"
        style={{
          transform: `perspective(1000px) translateY(${mousePos.y * -20}px) translateX(${mousePos.x * 15}px) rotateY(${mousePos.x * -4}deg)`,
        }}
      >
        <span className={`text-[10px] tracking-widest ${theme.textColor} font-bold mb-4`}>[TACTICAL_COMPASS]</span>
        <div className="relative w-36 h-36 flex items-center justify-center">
          {/* Inner ring spinning clockwise */}
          <div className="absolute w-32 h-32 rounded-full border border-dashed border-slate-800 animate-spin" style={{ animationDuration: '20s' }} />
          {/* Outer compass grid spinning counter-clockwise */}
          <div className="absolute w-28 h-28 rounded-full border border-slate-700/60 animate-spin flex items-center justify-center" style={{ animationDuration: '10s', animationDirection: 'reverse' }}>
            <div className="w-1 h-28 bg-gradient-to-t from-transparent via-blue-500/20 to-transparent absolute" />
            <div className="w-28 h-1 bg-gradient-to-r from-transparent via-blue-500/20 to-transparent absolute" />
          </div>
          {/* Central Core Pulse */}
          <div className={`w-8 h-8 rounded-full border border-current flex items-center justify-center bg-slate-950 ${theme.textColor} animate-pulse shadow-lg ${theme.glow}`}>
            <svg className="w-4 h-4 text-current" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 009 11M9 11V9m0 2h.01M4 21h16M3 9a9 9 0 019-9 9 9 0 019 9v12H3V9z"/>
            </svg>
          </div>
        </div>
        <div className="mt-4 text-center">
          <p className="text-[10px] text-slate-500">DECRYPTION ENGINE CORE</p>
          <p className={`text-xs font-semibold ${theme.textColor}`}>COMPASS_V3.80</p>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {/* Holographic Decrypting Monitor Sequencer screen */}
        {isDecrypting ? (
          <motion.div
            key="hacker-boot"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className={`w-full max-w-xl bg-slate-950/85 border border-slate-800 rounded-2xl p-8 z-20 shadow-2xl backdrop-blur-lg relative border-l-4 ${theme.id === 'cyan' ? 'border-l-cyan-500' : theme.id === 'green' ? 'border-l-emerald-500' : theme.id === 'purple' ? 'border-l-purple-500' : 'border-l-rose-500'}`}
          >
            <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-6">
              <div className="flex items-center gap-3">
                <span className="flex h-3 w-3 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
                </span>
                <h3 className="font-mono text-xs text-red-500 tracking-widest font-extrabold uppercase">
                  [SECURITY ROOT SHELL ACCESS ACTIVE]
                </h3>
              </div>
              <span className={`font-mono text-xs ${theme.textColor} font-bold`}>
                DECRYPTING: {decryptionProgress}%
              </span>
            </div>

            {/* Matrix Deco Bars */}
            <div className="w-full bg-slate-900 h-2.5 rounded-full overflow-hidden mb-6 border border-slate-850">
              <div
                className={`h-full bg-gradient-to-r from-blue-600 via-emerald-400 to-cyan-400 transition-all duration-70 bg-size-200 animate-pulse`}
                style={{ width: `${decryptionProgress}%`, backgroundSize: '200% 200%' }}
              />
            </div>

            {/* Terminal scrolling area */}
            <div className="w-full bg-black/60 border border-slate-900 rounded-xl p-4 h-48 font-mono text-[11px] overflow-y-auto space-y-2 flex flex-col justify-end text-emerald-400/90 shadow-inner">
              <div className="flex-1 overflow-y-auto scrollbar-hide space-y-1.5 flex flex-col justify-end pointer-events-none">
                <p className="text-slate-500">// INITIALIZING SECURE SHELL TRANSFER</p>
                {decryptLogs.map((log, index) => (
                  <p key={index} className="leading-relaxed font-bold">
                    <span className="text-slate-500">&gt;&gt;</span> {log}
                  </p>
                ))}
                {decryptionProgress < 100 && (
                  <p className="animate-pulse text-cyan-400">
                    <span className="text-slate-500">&gt;&gt;</span> LOADING QUANTUM CACHE BLOCKS... [{String.fromCharCode(33 + (decryptionProgress % 30))}]
                  </p>
                )}
              </div>
            </div>

            <div className="mt-6 flex justify-between items-center font-mono text-[10px] text-slate-500">
              <span>EST_TIME_REMAINING: {((100 - decryptionProgress) * 0.05).toFixed(1)}s</span>
              <span>HOST: 0.0.0.0:3000 // DECRYTION_THREAD</span>
            </div>
          </motion.div>
        ) : (
          /* Main Authentication Terminal form card with 3D Parallax Tilt */
          <motion.div
            key="auth-card"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -30 }}
            className={`w-full max-w-md bg-slate-900/75 border border-slate-800 rounded-2xl p-8 z-20 shadow-2xl backdrop-blur-md relative transform transition-transform duration-300 ease-out shadow-inner border-t-2 ${theme.id === 'cyan' ? 'border-t-cyan-500/80 shadow-cyan-500/5' : theme.id === 'green' ? 'border-t-emerald-500/80 shadow-emerald-500/5' : theme.id === 'purple' ? 'border-t-purple-500/80 shadow-purple-500/5' : 'border-t-rose-500/80 shadow-rose-500/5'}`}
            style={{
              transform: `perspective(1000px) rotateY(${mousePos.x * 6}deg) rotateX(${-mousePos.y * 6}deg) translateY(${mousePos.y * -8}px)`,
            }}
          >
            {/* Corner Bracket decorations */}
            <div className={`absolute top-4 left-4 font-mono text-[10px] font-bold ${theme.textColor} opacity-40`}>[SYS.I]</div>
            <div className={`absolute top-4 right-4 font-mono text-[10px] font-bold ${theme.textColor} opacity-40`}>[CEREBRO_V1.02]</div>
            <div className={`absolute bottom-4 left-4 font-mono text-[8px] text-slate-600`}>DECENTRAL_STATION</div>
            <div className={`absolute bottom-4 right-4 font-mono text-[8px] text-slate-600`}>BYPASS_PORT_3000</div>

            <div className="text-center mb-8 mt-2">
              {/* Dynamic circular glowing launcher icon */}
              <div 
                className={`w-14 h-14 bg-slate-950 rounded-xl border border-dashed text-white flex items-center justify-center mx-auto mb-4 relative transition-all duration-500 ${
                  theme.id === 'cyan' ? 'border-cyan-500/50 shadow-cyan-500/20 shadow-lg' :
                  theme.id === 'green' ? 'border-emerald-500/50 shadow-emerald-500/20 shadow-lg' :
                  theme.id === 'purple' ? 'border-purple-500/50 shadow-purple-500/20 shadow-lg' :
                  'border-rose-500/50 shadow-rose-500/20 shadow-lg'
                }`}
              >
                {/* Rotating SVG grid inside launcher */}
                <div className="absolute inset-1 rounded-lg border border-slate-900 border-dashed animate-spin" style={{ animationDuration: '12s' }} />
                <svg className="w-8 h-8 text-white relative z-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <h1 className="text-3xl font-extrabold text-white tracking-widest font-mono">
                <CyberText text="CEREBRO" speed={60} />
              </h1>
              <p className="text-slate-400 mt-2 font-mono text-[11px] tracking-widest uppercase">
                Identify Threats. Analyze Digital Truth.
              </p>
            </div>

            {/* Cybernetic Navigation Tabs to easily switch between Login and Register */}
            <div className="grid grid-cols-2 gap-2 mb-6 border-b border-slate-800/80 pb-3">
              <button
                type="button"
                onClick={() => {
                  setIsLogin(true);
                  setError('');
                  playSFX('switch');
                }}
                className={`py-2 text-center font-mono text-xs tracking-widest uppercase transition-all duration-300 border rounded-lg cursor-pointer ${
                  isLogin
                    ? `${theme.textColor} bg-slate-950/80 border-slate-700 shadow-md shadow-slate-900`
                    : 'text-slate-500 border-transparent hover:text-slate-300 hover:bg-slate-900/30'
                }`}
              >
                [ SIGN_IN ]
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsLogin(false);
                  setError('');
                  playSFX('switch');
                }}
                className={`py-2 text-center font-mono text-xs tracking-widest uppercase transition-all duration-300 border rounded-lg cursor-pointer ${
                  !isLogin
                    ? `${theme.textColor} bg-slate-950/80 border-slate-700 shadow-md shadow-slate-900`
                    : 'text-slate-500 border-transparent hover:text-slate-300 hover:bg-slate-900/30'
                }`}
              >
                [ SIGN_UP / REGISTER ]
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5 relative">
              {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs text-center font-mono flex items-center justify-center gap-2 animate-shake">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-ping" />
                  {error}
                </div>
              )}

              {!isLogin && (
                <div className="relative group">
                  <label className="block text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-1.5 flex justify-between">
                    <span>ANALYST IDENTITY</span>
                    <span className="text-slate-600">[NULL]</span>
                  </label>
                  <div className="relative">
                    <span className="absolute left-3.5 top-1/2 transform -translate-y-1/2 text-slate-500 font-mono text-xs">&gt;&nbsp;</span>
                    <input
                      type="text"
                      required
                      value={name}
                      onKeyDown={() => playSFX('keyboard')}
                      onChange={(e) => setName(e.target.value)}
                      className={`w-full bg-slate-950/90 border border-slate-800 rounded-lg pl-8 pr-4 py-3 text-sm font-mono text-slate-100 outline-none transition-all focus:border-cyan-400 ${theme.primary}`}
                      placeholder="e.g. Neo Wright"
                    />
                  </div>
                </div>
              )}

              <div className="relative group">
                <label className="block text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-1.5 flex justify-between">
                  <span>CRYPTO ENDPOINT EMAIL</span>
                  <span className="text-slate-600">[SECURE_SHELL]</span>
                </label>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 transform -translate-y-1/2 text-slate-500 font-mono text-xs">&gt;&nbsp;</span>
                  <input
                    type="email"
                    required
                    value={email}
                    onKeyDown={() => playSFX('keyboard')}
                    onChange={(e) => setEmail(e.target.value)}
                    className={`w-full bg-slate-950/90 border border-slate-800 rounded-lg pl-8 pr-4 py-3 text-sm font-mono text-slate-100 outline-none transition-all focus:border-cyan-400 ${theme.primary}`}
                    placeholder="analyst@cerebro.ai"
                  />
                </div>
              </div>

              <div className="relative group">
                <label className="block text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-1.5 flex justify-between">
                  <span>SECURITY AUTH KEY</span>
                  <span className="text-slate-600">[ENCRYPTED]</span>
                </label>
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 transform -translate-y-1/2 text-slate-500 font-mono text-xs">&gt;&nbsp;</span>
                  <input
                    type="password"
                    required
                    value={password}
                    onKeyDown={() => playSFX('keyboard')}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`w-full bg-slate-950/90 border border-slate-800 rounded-lg pl-8 pr-4 py-3 text-sm font-mono text-slate-100 outline-none transition-all focus:border-cyan-400 ${theme.primary}`}
                    placeholder="••••••••"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                onMouseEnter={() => playSFX('hover')}
                className={`w-full font-mono text-xs font-bold tracking-widest py-3.5 rounded-lg border uppercase transition-all duration-300 flex justify-center items-center gap-2 cursor-pointer ${theme.accent}`}
              >
                {loading ? (
                  <div className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    CONNECTING MATRIX...
                  </div>
                ) : (
                  <span>{isLogin ? '[ DECRYPT & SIGN IN ]' : '[ DECRYPT & REGISTER ACCOUNT ]'}</span>
                )}
              </button>

              <div className="relative flex py-1 items-center">
                <div className="flex-grow border-t border-slate-800/80"></div>
                <span className="flex-shrink mx-4 text-slate-500 font-mono text-[9px] tracking-widest">OR</span>
                <div className="flex-grow border-t border-slate-800/80"></div>
              </div>

              <div className="space-y-3">
                <button
                  type="button"
                  onClick={handleGoogleSignIn}
                  disabled={loading}
                  onMouseEnter={() => playSFX('hover')}
                  className="w-full font-mono text-xs font-bold tracking-widest py-3 rounded-lg border border-slate-800 hover:border-slate-600 bg-slate-950/40 hover:bg-slate-900 text-slate-400 hover:text-white transition-all duration-300 flex justify-center items-center gap-2 cursor-pointer"
                >
                  <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335"/>
                  </svg>
                  <span>[ESTABLISH GOOGLE LINK]</span>
                </button>
                
                <p className="text-[9px] font-mono text-slate-500 leading-relaxed bg-slate-950/50 p-2.5 rounded border border-slate-900/60 text-center">
                  ⚠️ <span className="text-amber-500/80 font-bold">GOOGLE AUTH NOTE:</span> Google SSO requires explicit DNS redirect mapping. If Google blocks you with <span className="text-amber-500 font-bold">Error 401</span>, please switch to the <span className="text-cyan-400 font-bold underline cursor-pointer" onClick={() => setIsLogin(false)}>[ SIGN_UP ]</span> tab above to register instantly via credentials.
                </p>
              </div>
            </form>

            {/* Bottom Toggle switch styled as terminal options */}
            <div className="mt-8 text-center border-t border-slate-800/80 pt-6">
              <p className="text-slate-500 font-mono text-[10px] tracking-widest uppercase mb-1">
                {isLogin ? "IDENTITY Footprint unregistered?" : "Already verified within matrix?"}
              </p>
              <button
                onClick={() => {
                  setIsLogin(!isLogin);
                  setError('');
                  playSFX('switch');
                }}
                onMouseEnter={() => playSFX('hover')}
                className={`font-mono text-xs tracking-widest hover:underline ${theme.textColor}`}
              >
                {isLogin ? '> REGISTER NEW FOOTPRINT' : '> CONNECT AS REGISTERED AGENT'}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
