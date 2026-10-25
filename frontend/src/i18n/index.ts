/**
 * Minimal i18n runtime: a zustand store (persisted, mirroring `themeStore`) plus
 * a pure `translate()` helper so non-React modules (axios interceptors, plain
 * functions) can translate too.
 *
 * The language is resolved in this order when the app boots:
 *   1. the value persisted from a previous visit (user picked it explicitly),
 *   2. `defaultLanguage`, seeded from the backend `/config` endpoint — which
 *      reads `APP_LANGUAGE` from the container environment,
 *   3. `DEFAULT_LANGUAGE`.
 *
 * The active language is mirrored onto `<html lang>` and pushed to the API
 * through the `X-App-Language` header (see `src/api/client.ts`), so streamed
 * answers and error messages come back in the same language as the UI.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { en, messages, MessageKey } from './messages'

export const SUPPORTED_LANGUAGES = ['en', 'zh'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]
export const DEFAULT_LANGUAGE: Language = 'en'

export type TranslationParams = Record<string, string | number>
export type Translate = (key: MessageKey, params?: TranslationParams) => string

/** Normalise arbitrary input (`zh-CN`, `cn`, `中文`, `EN`) to a supported code. */
export function normalizeLanguage(value: string | null | undefined): Language | null {
  if (!value) return null
  const lowered = value.trim().toLowerCase().replace(/_/g, '-')
  if (!lowered) return null
  if ((SUPPORTED_LANGUAGES as readonly string[]).includes(lowered)) {
    return lowered as Language
  }
  const base = lowered.split('-')[0]
  if ((SUPPORTED_LANGUAGES as readonly string[]).includes(base)) {
    return base as Language
  }
  // Chinese aliases that are not valid BCP-47 tags but appear in configs.
  if (['cn', 'chinese', 'mandarin', '中文', '简体中文'].includes(lowered)) {
    return 'zh'
  }
  if (['english', 'en-us', 'en-gb'].includes(lowered)) {
    return 'en'
  }
  return null
}

/** Translate outside of React (interceptors, helpers). */
export function translate(
  language: string | null | undefined,
  key: MessageKey,
  params?: TranslationParams,
): string {
  const code = normalizeLanguage(language) ?? DEFAULT_LANGUAGE
  const table = messages[code] ?? en
  let template: string = table[key] ?? en[key] ?? key
  if (!params) return template
  for (const [name, value] of Object.entries(params)) {
    template = template.split(`{${name}}`).join(String(value))
  }
  return template
}

interface LanguageState {
  /** Effective language used for rendering. */
  language: Language
  /** Language the deployment configured via `APP_LANGUAGE`; used on a first visit. */
  defaultLanguage: Language
  /** True once the visitor picked a language, which pins it against `APP_LANGUAGE`. */
  userSelected: boolean
  setLanguage: (language: Language) => void
  toggleLanguage: () => void
  setDefaultLanguage: (language: Language) => void
}

function applyDocumentLanguage(language: Language) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
}

export const useLanguageStore = create<LanguageState>()(
  persist(
    (set, get) => ({
      language: DEFAULT_LANGUAGE,
      defaultLanguage: DEFAULT_LANGUAGE,
      userSelected: false,
      setLanguage: (language: Language) => {
        set({ language, userSelected: true })
        applyDocumentLanguage(language)
      },
      toggleLanguage: () => {
        const next: Language = get().language === 'zh' ? 'en' : 'zh'
        set({ language: next, userSelected: true })
        applyDocumentLanguage(next)
      },
      // Only moves the *effective* language when the visitor never chose one,
      // so a container-side `APP_LANGUAGE` change applies to fresh browsers.
      setDefaultLanguage: (language: Language) => {
        set((state) => ({
          defaultLanguage: language,
          language: state.userSelected ? state.language : language,
        }))
        if (!get().userSelected) applyDocumentLanguage(language)
      },
    }),
    {
      name: 'ragvault-language-preference',
      partialize: (state) => ({
        language: state.language,
        defaultLanguage: state.defaultLanguage,
        userSelected: state.userSelected,
      }),
      onRehydrateStorage: () => (state) => {
        applyDocumentLanguage(state?.language ?? DEFAULT_LANGUAGE)
      },
    },
  ),
)

/** Effective language: the user's choice, otherwise the deployment default. */
export function activeLanguage(): Language {
  const state = useLanguageStore.getState()
  return normalizeLanguage(state.language) ?? normalizeLanguage(state.defaultLanguage) ?? DEFAULT_LANGUAGE
}

/** Translate for the currently active language (usable outside React). */
export function t(key: MessageKey, params?: TranslationParams): string {
  return translate(activeLanguage(), key, params)
}

/** Seed the default language (and `<html lang>`) before the first render. */
export function initLocale(defaultLanguage?: string | null) {
  const normalized = normalizeLanguage(defaultLanguage)
  const state = useLanguageStore.getState()
  if (normalized) {
    state.setDefaultLanguage(normalized)
  }
  applyDocumentLanguage(activeLanguage())
}

/**
 * Fetch the deployment default from the backend and apply it.
 *
 * Called once on boot; failures are ignored because the built-in default is
 * always a valid fallback.
 */
export async function syncLocaleFromServer(): Promise<Language> {
  try {
    const response = await fetch('/api/config', { headers: { Accept: 'application/json' } })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data: { default_language?: string; supported_languages?: string[] } = await response.json()
    const language = normalizeLanguage(data.default_language)
    if (language) {
      useLanguageStore.getState().setDefaultLanguage(language)
      return language
    }
  } catch {
    // Backend not reachable yet (or offline): keep the built-in default.
  }
  return activeLanguage()
}
