/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    // Dev-only same-origin proxy: when running the real client
    // (VITE_USE_MOCKS=false) without VITE_API_BASE, /api/* is forwarded to the
    // backend so the browser never makes a cross-origin (CORS) request. Set
    // NB_DEV_API_TARGET to point at a backend on a different host/port.
    proxy: {
      '/api': {
        target: process.env.NB_DEV_API_TARGET ?? 'http://localhost:8090',
        changeOrigin: true,
      },
    },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // vitest collects unit tests under src/. Playwright lives in playwright/
    // and uses @playwright/test's own runner.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules', 'dist', 'playwright/**'],
  },
});
