import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const API_TARGET = 'http://localhost:8000';

// Proxy API paths to the FastAPI backend so the browser can call same-origin
// relative URLs (avoids CORS and keeps auth headers simple).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/conversations': { target: API_TARGET, changeOrigin: true },
      '/manifests': { target: API_TARGET, changeOrigin: true },
      '/resources': { target: API_TARGET, changeOrigin: true },
      '/fs': { target: API_TARGET, changeOrigin: true },
    },
  },
});
