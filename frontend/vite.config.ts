import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { readdirSync, statSync, unlinkSync, rmdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

/**
 * Empties `dist` before a build so stale `index-<hash>.js` files never
 * accumulate. `backend/ragvault-backend.spec` copies the whole directory into
 * the frozen backend, so every leftover build used to end up in the installer
 * (~16 MB of dead bundles by the time this was noticed).
 *
 * This exists instead of `build.emptyOutDir` because that path goes through
 * Vite's own `emptyDir()`, which uses `fs.rmSync()` — and `fs.rmSync()` silently
 * does nothing on this machine (it returns without throwing and the file is
 * still there, so nothing looks wrong until the directory is inspected).
 * `fs.unlinkSync()` / `fs.rmdirSync()` work fine, so the deletion is spelled out
 * with those instead of a recursive helper.
 */
function cleanDist(): Plugin {
  let target = ''

  const remove = (entry: string) => {
    const stat = statSync(entry, { throwIfNoEntry: false })
    if (!stat) return

    if (stat.isDirectory()) {
      for (const child of readdirSync(entry)) remove(join(entry, child))
      rmdirSync(entry)
      return
    }

    unlinkSync(entry)
  }

  return {
    name: 'ragvault-clean-dist',
    apply: 'build',
    configResolved(config) {
      target = resolve(config.root, config.build.outDir)
    },
    buildStart() {
      remove(target)
    },
  }
}

export default defineConfig({
  plugins: [react(), cleanDist()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
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
