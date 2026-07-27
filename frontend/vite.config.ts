import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');

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
          target: env.VITE_API_BASE || 'http://localhost:8000',
          changeOrigin: true,
          ws: true,             // required for the /v1/stream WebSocket
        },
        '/health': { target: env.VITE_API_BASE || 'http://localhost:8000', changeOrigin: true },
        '/ready':  { target: env.VITE_API_BASE || 'http://localhost:8000', changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: mode !== 'production',
    },
  };
});
