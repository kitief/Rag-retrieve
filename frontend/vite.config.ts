import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // No `rewrite` on purpose. The SPA always calls `/api/...` and the backend
      // strips that prefix itself in DesktopLocalMiddleware
      // (backend/app/main.py) — the same code path serves the desktop build.
      //
      // Stripping it here as well removes it twice, so `/api/settings` becomes
      // `/settings`, which is not a router path: SpaMiddleware answers with
      // index.html and every API call silently returns HTML instead of JSON.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
