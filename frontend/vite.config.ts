import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');

  // Where the dev-server proxy forwards API calls. This is a SERVER-side setting
  // (kept out of the client bundle), separate from VITE_API_BASE which the
  // browser code uses. In Docker the frontend and backend are separate
  // containers, so PROXY_TARGET is set to the backend service (e.g. http://api:8000);
  // running bare on the host it defaults to localhost:8000.
  const proxyTarget = process.env.PROXY_TARGET || env.VITE_API_BASE || 'http://localhost:8000';

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      port: 5173,
      host: true,
      // In development the frontend and API run on different ports. Proxying
      // keeps requests same-origin, so httpOnly session cookies work exactly
      // as they will in production — no CORS special-casing for dev only.
      proxy: {
        '/v1': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true, // required for the /v1/stream WebSocket
        },
        '/health': { target: proxyTarget, changeOrigin: true },
        '/ready': { target: proxyTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
    },
  };
});
