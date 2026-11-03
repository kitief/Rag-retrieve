import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, AuthTokens } from '@/types'

interface AuthState {
  user: User | null
  tokens: AuthTokens | null
  sessionId: string | null
  setAuth: (user: User, tokens: AuthTokens) => void
  clearAuth: () => void
  updateTokens: (tokens: AuthTokens) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      tokens: null,
      sessionId: null,
      setAuth: (user, tokens) => set({ user, tokens, sessionId: crypto.randomUUID() }),
      clearAuth: () => set({ user: null, tokens: null, sessionId: null }),
      updateTokens: (tokens) => set({ tokens }),
    }),
    {
      name: 'auth-storage',
      // The access/refresh tokens are persisted to localStorage, which any script
      // on this origin can read — a successful XSS could exfiltrate them. We do
      // NOT switch to HttpOnly cookies: that would couple the web front-end, the
      // Python backend (CORS/CSRF) and the Tauri WebView origin to a shared cookie
      // domain, a far larger change. Until then keep the XSS surface small (never
      // render user HTML unsafely) and treat this token store as same-origin data.
      partialize: (state) => ({ tokens: state.tokens, user: state.user, sessionId: state.sessionId }),
    }
  )
)
