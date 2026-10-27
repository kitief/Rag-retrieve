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
      // No `rewrite` on purpose. The SPA always calls `/api/...`; who removes
      // that prefix depends on the deployment:
      //
      //   * Docker — frontend/nginx.conf turns `/api/` into `/` when proxying
      //     to the backend.
      //   * Dev server and desktop build — the backend does it itself in
      //     DesktopLocalMiddleware (backend/app/main.py).
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
