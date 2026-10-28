/**
 * Settings API.
 *
 * The dialog talks to `/api/settings`, which persists the overrides in the
 * backend database so they survive container restarts and take precedence over
 * the `.env` defaults. The API key is write-only: the GET response only reports
 * whether one exists and a short masked hint.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from './client'

export interface ProviderInfo {
  name: string
  label: string
  base_url: string
  model: string
  api_key_env: string
  docs_url: string
}

export interface LanguageSettings {
  current: string
  supported: string[]
  source: string
}

export interface ConnectionState {
  ok: boolean
  message: string
  provider: string
  base_url: string
  models: string[]
  checked_at: string | null
  /**
   * True when the saved provider/base URL/key no longer match what was probed.
   * The badge treats a stale probe as "not connected" so an old green light
   * cannot outlive an edit.
   */
  stale: boolean
  key_hint: string
}

export interface LLMSettings {
  provider: string
  base_url: string
  model: string
  api_key_set: boolean
  api_key_hint: string
  timeout_seconds: number
  max_retries: number
  max_concurrency: number
  /** Last probe, persisted server-side so it survives closing the dialog. */
  connection: ConnectionState | null
}

export interface SettingsResponse {
  language: LanguageSettings
  llm: LLMSettings
  providers: ProviderInfo[]
  api_keys: ApiKeyInfo[]
  restart_required: boolean
}

export interface ApiKeyInfo {
  id: string
  provider: string
  label: string
  hint: string
  active: boolean
  created_at: string | null
}

export interface ApiKeyCreate {
  provider: string
  label?: string
  value: string
  activate?: boolean
}

export interface ApiKeyUpdate {
  label?: string
  value?: string
  activate?: boolean
}

export interface ModelsResponse {
  models: string[]
  base_url: string
  source: string
}

/** Credentials typed into the dialog, probed without being saved. */
export interface ConnectRequest {
  llm_provider?: string | null
  llm_base_url?: string | null
  llm_api_key?: string | null
}

export interface ConnectResponse {
  ok: boolean
  message: string
  provider: string
  base_url: string
  models: string[]
  source: string
}

export interface SettingsUpdate {
  language?: string | null
  llm_provider?: string | null
  llm_base_url?: string | null
  llm_model?: string | null
  llm_api_key?: string | null
}

export interface SettingsTestResponse {
  ok: boolean
  message: string
  provider: string
  model: string
  base_url: string
}

export const settingsKeys = {
  all: ['settings'] as const,
  models: ['settings', 'models'] as const,
}

export function useSettings(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.all,
    queryFn: async () => {
      const { data } = await api.get<SettingsResponse>('/settings')
      return data
    },
    enabled,
    staleTime: 30_000,
  })
}

/**
 * The model ids the configured endpoint advertises.
 *
 * Refetched whenever the settings change, because the list depends on the base
 * URL and the active key. ``source`` is ``"unavailable"`` when the provider has
 * no `/models` endpoint, in which case the dialog falls back to free text.
 */
export function useLlmModels(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.models,
    queryFn: async () => {
      const { data } = await api.get<ModelsResponse>('/settings/llm/models')
      return data
    },
    enabled,
    staleTime: 60_000,
    retry: false,
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SettingsUpdate) => {
      const { data } = await api.put<SettingsResponse>('/settings', payload)
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKeys.all, data)
      // The sidebar badge reads the connection from this same payload, so the
      // connect result has to reach it without waiting out the stale time.
      void queryClient.invalidateQueries({ queryKey: settingsKeys.all })
    },
  })
}

export function useResetSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.delete<SettingsResponse>('/settings')
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKeys.all, data)
    },
  })
}

export function useTestLlm() {
  return useMutation({
    mutationFn: async (payload: SettingsUpdate) => {
      const { data } = await api.post<SettingsTestResponse>('/settings/llm/test', payload)
      return data
    },
  })
}

/**
 * Probe the endpoint with the credentials currently in the form.
 *
 * This is the "Connect" button behind the model dropdown: besides reporting
 * whether the endpoint is reachable and which model ids it serves, the backend
 * records the outcome so the next time the dialog opens it can restore the same
 * badge and model list instead of starting from blank. Only the *result* is
 * stored — never the key itself beyond the vault.
 */
export function useConnectLlm() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ConnectRequest) => {
      const { data } = await api.post<ConnectResponse>('/settings/llm/connect', payload)
      return data
    },
    onSuccess: () => {
      // The probe wrote its outcome server-side; refresh so a later reopen reads
      // the stored state rather than a cache that predates the probe.
      void queryClient.invalidateQueries({ queryKey: settingsKeys.all })
    },
  })
}

/**
 * Save a key into the vault.
 *
 * ``activate`` (default true on the server) also points the running
 * configuration at the new secret, so saving is enough to start using it.
 */
export function useCreateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ApiKeyCreate) => {
      const { data } = await api.post<ApiKeyInfo>('/settings/llm/keys', payload)
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: settingsKeys.all })
      void queryClient.invalidateQueries({ queryKey: settingsKeys.models })
    },
  })
}

/** Switch to a saved key, or rename one. */
export function useUpdateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: ApiKeyUpdate & { id: string }) => {
      const { data } = await api.patch<SettingsResponse>(`/settings/llm/keys/${id}`, payload)
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKeys.all, data)
      void queryClient.invalidateQueries({ queryKey: settingsKeys.models })
    },
  })
}

export function useDeleteApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.delete<SettingsResponse>(`/settings/llm/keys/${id}`)
      return data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(settingsKeys.all, data)
    },
  })
}
