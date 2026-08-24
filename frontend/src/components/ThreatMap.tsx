import React, { useEffect, useRef } from 'react';

/**
 * Live global threat map — the animated background for the auth + dashboard.
 *
 * Real city coordinates are projected equirectangularly; a field of faint dots
 * clustered around them suggests the inhabited landmasses (no map asset needed),
 * and "attacks" arc between cities with a travelling pulse and an impact ripple —
 * the classic security-operations-center look. Self-contained canvas, no deps.
 */

interface City {
  lon: number;
  lat: number;
}

// ~35 major cities, spread across the continents.
const CITIES: City[] = [
  { lon: -74.0, lat: 40.7 },
  { lon: -118.2, lat: 34.0 },
  { lon: -87.6, lat: 41.9 },
  { lon: -79.4, lat: 43.7 },
  { lon: -99.1, lat: 19.4 },
  { lon: -74.1, lat: 4.7 },
  { lon: -46.6, lat: -23.5 },
  { lon: -58.4, lat: -34.6 },
  { lon: -70.7, lat: -33.4 },
  { lon: -0.1, lat: 51.5 },
  { lon: 2.3, lat: 48.9 },
  { lon: -3.7, lat: 40.4 },
  { lon: 13.4, lat: 52.5 },
  { lon: 37.6, lat: 55.75 },
  { lon: 28.9, lat: 41.0 },
  { lon: 31.2, lat: 30.0 },
  { lon: 3.4, lat: 6.5 },
  { lon: 28.0, lat: -26.2 },
  { lon: 36.8, lat: -1.3 },
  { lon: 55.3, lat: 25.2 },
  { lon: 46.7, lat: 24.6 },
  { lon: 51.4, lat: 35.7 },
  { lon: 72.8, lat: 19.0 },
  { lon: 77.2, lat: 28.6 },
  { lon: 77.6, lat: 13.0 },
  { lon: 103.8, lat: 1.35 },
  { lon: 100.5, lat: 13.75 },
  { lon: 106.8, lat: -6.2 },
  { lon: 114.2, lat: 22.3 },
  { lon: 121.5, lat: 31.2 },
  { lon: 116.4, lat: 39.9 },
  { lon: 127.0, lat: 37.5 },
  { lon: 139.7, lat: 35.7 },
  { lon: 151.2, lat: -33.9 },
  { lon: 115.9, lat: -31.95 },
];

interface Attack {
  sx: number;
  sy: number;
  ex: number;
  ey: number;
  cx: number;
  cy: number;
  t: number;
  speed: number;
  threat: boolean;
  done: boolean;
}
interface Ripple {
  x: number;
  y: number;
  r: number;
  max: number;
  hue: string;
}
interface Dust {
  x: number;
  y: number;
  r: number;
  a: number;
}

interface Props {
  accentRGB?: string; // e.g. "6, 182, 212"
}

export const ThreatMap: React.FC<Props> = ({ accentRGB = '6, 182, 212' }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let W = 0,
      H = 0;
    let nodes: { x: number; y: number; phase: number }[] = [];
    let dust: Dust[] = [];
    let attacks: Attack[] = [];
    let ripples: Ripple[] = [];
    let last = performance.now();
    let acc = 0;
    let frame = 0;

    const project = (lon: number, lat: number) => ({
      x: ((lon + 180) / 360) * W,
      y: ((90 - lat) / 180) * H,
    });

    function build() {
      W = canvas!.clientWidth;
      H = canvas!.clientHeight;
      canvas!.width = Math.floor(W * dpr);
      canvas!.height = Math.floor(H * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      nodes = CITIES.map((c) => {
        const p = project(c.lon, c.lat);
        return { x: p.x, y: p.y, phase: Math.random() * Math.PI * 2 };
      });

      dust = [];
      const spread = Math.min(W, H) * 0.045;
      const g = () => Math.random() + Math.random() + Math.random() - 1.5; // ~gaussian
      for (let i = 0; i < 560; i++) {
        const c = CITIES[Math.floor(Math.random() * CITIES.length)];
        const p = project(c.lon, c.lat);
        dust.push({
          x: p.x + g() * spread * 2.4,
          y: p.y + g() * spread * 1.7,
          r: Math.random() * 1.3 + 0.4,
          a: Math.random() * 0.35 + 0.12,
        });
      }
    }

    function spawn() {
      if (nodes.length < 2) return;
      const a = nodes[Math.floor(Math.random() * nodes.length)];
      let b = nodes[Math.floor(Math.random() * nodes.length)];
      let guard = 0;
      while (b === a && guard++ < 5) b = nodes[Math.floor(Math.random() * nodes.length)];
      if (b === a) return;
      const mx = (a.x + b.x) / 2,
        my = (a.y + b.y) / 2;
      const dist = Math.hypot(b.x - a.x, b.y - a.y);
      const lift = Math.min(dist * 0.4, H * 0.4);
      attacks.push({
        sx: a.x,
        sy: a.y,
        ex: b.x,
        ey: b.y,
        cx: mx,
        cy: my - lift,
        t: 0,
        speed: 0.006 + Math.random() * 0.008,
        threat: Math.random() < 0.62,
        done: false,
      });
      if (attacks.length > 30) attacks.shift();
    }

    const bez = (s: number, c: number, e: number, u: number) =>
      (1 - u) * (1 - u) * s + 2 * (1 - u) * u * c + u * u * e;

    const draw = (ts: number) => {
      const dt = Math.min(ts - last, 60);
      last = ts;
      const step = dt / 16;

      // trailing fade
      ctx.fillStyle = 'rgba(2, 6, 23, 0.30)';
      ctx.fillRect(0, 0, W, H);

      // graticule
      ctx.strokeStyle = `rgba(${accentRGB}, 0.05)`;
      ctx.lineWidth = 1;
      for (let lon = -180; lon <= 180; lon += 30) {
        const x = ((lon + 180) / 360) * W;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, H);
        ctx.stroke();
      }
      for (let lat = -60; lat <= 60; lat += 30) {
        const y = ((90 - lat) / 180) * H;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
        ctx.stroke();
      }

      // landmass dust
      for (const d of dust) {
        ctx.beginPath();
        ctx.fillStyle = `rgba(${accentRGB}, ${d.a})`;
        ctx.arc(d.x, d.y, d.r, 0, 6.283);
        ctx.fill();
      }

      // city nodes
      for (const n of nodes) {
        n.phase += 0.03 * step;
        const pulse = (Math.sin(n.phase) + 1) / 2;
        ctx.beginPath();
        ctx.fillStyle = `rgba(${accentRGB}, ${0.5 + pulse * 0.5})`;
        ctx.arc(n.x, n.y, 1.4 + pulse * 0.8, 0, 6.283);
        ctx.fill();
        ctx.beginPath();
        ctx.strokeStyle = `rgba(${accentRGB}, ${0.18 * (1 - pulse)})`;
        ctx.lineWidth = 1;
        ctx.arc(n.x, n.y, 3 + pulse * 6, 0, 6.283);
        ctx.stroke();
      }

      // spawn + draw attacks
      acc += dt;
      if (acc > 340) {
        acc = 0;
        spawn();
      }
      for (const at of attacks) {
        at.t += at.speed * step;
        const tt = Math.min(at.t, 1);
        const col = at.threat ? '244, 63, 94' : accentRGB; // rose vs accent
        const seg = 24;
        ctx.beginPath();
        for (let i = 0; i <= seg; i++) {
          const u = (i / seg) * tt;
          const x = bez(at.sx, at.cx, at.ex, u);
          const y = bez(at.sy, at.cy, at.ey, u);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = `rgba(${col}, 0.5)`;
        ctx.lineWidth = 1.2;
        ctx.stroke();
        // travelling head
        const hx = bez(at.sx, at.cx, at.ex, tt);
        const hy = bez(at.sy, at.cy, at.ey, tt);
        ctx.beginPath();
        ctx.fillStyle = `rgba(${col}, 0.95)`;
        ctx.arc(hx, hy, 1.9, 0, 6.283);
        ctx.fill();
        if (at.t >= 1 && !at.done) {
          at.done = true;
          ripples.push({ x: at.ex, y: at.ey, r: 0, max: 18, hue: col });
        }
      }
      attacks = attacks.filter((a) => a.t < 1.15);

      // impact ripples
      for (const r of ripples) {
        r.r += 0.7 * step;
        ctx.beginPath();
        ctx.strokeStyle = `rgba(${r.hue}, ${Math.max(0, 0.6 * (1 - r.r / r.max))})`;
        ctx.lineWidth = 1.2;
        ctx.arc(r.x, r.y, r.r, 0, 6.283);
        ctx.stroke();
      }
      ripples = ripples.filter((r) => r.r < r.max);

      frame = requestAnimationFrame(draw);
    };

    build();
    frame = requestAnimationFrame(draw);
    const onResize = () => build();
    window.addEventListener('resize', onResize);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', onResize);
    };
  }, [accentRGB]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 h-full w-full"
      style={{ width: '100%', height: '100%' }}
    />
  );
};
