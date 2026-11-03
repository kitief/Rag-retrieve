import axios from 'axios'
import { useAuthStore } from '@/store/authStore'
import { activeLanguage } from '@/i18n'
import { localAuthHeaders } from '@/lib/desktop'
import type { AuthTokens } from '@/types'

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: attach Bearer token + the UI language
api.interceptors.request.use((config) => {
  const tokens = useAuthStore.getState().tokens
  if (tokens?.access_token) {
    config.headers.Authorization = `Bearer ${tokens.access_token}`
  }
  // The API answers (and generates) in the language the user is reading the UI
  // in, so validation errors and AI output always match the interface.
  config.headers['X-App-Language'] = activeLanguage()
  // Desktop build only: prove we are the window the shell spawned, not a random
  // page that guessed the port.
  Object.assign(config.headers, localAuthHeaders())
  return config
})

// Shared in-flight refresh: concurrent 401s reuse one request instead of
// each firing its own, which would race and could drop or overwrite tokens.
let refreshPromise: Promise<AuthTokens> | null = null

async function refreshTokens(): Promise<AuthTokens> {
  const tokens = useAuthStore.getState().tokens
  if (!tokens?.refresh_token) {
    throw new Error('No refresh token')
  }

  // Call refresh endpoint directly with axios to avoid loop
  const res = await axios.post(
    '/api/auth/refresh',
    { refresh_token: tokens.refresh_token },
    {
      headers: {
        'X-App-Language': activeLanguage(),
        ...localAuthHeaders(),
      },
    },
  )

  const newTokens: AuthTokens = res.data
  useAuthStore.getState().updateTokens(newTokens)
  return newTokens
}

// Response interceptor: auto-refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const originalRequest = error.config
    // If 401 and not already retrying
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true
      try {
        const newTokens = await (refreshPromise ??= refreshTokens())
        originalRequest.headers.Authorization = `Bearer ${newTokens.access_token}`
        return axios(originalRequest)
      } catch (err) {
        useAuthStore.getState().clearAuth()
        window.location.href = '/login'
        return Promise.reject(err)
      } finally {
        refreshPromise = null
      }
    }
    return Promise.reject(error)
  }
)

export default api
