/**
 * React bindings for the i18n runtime.
 *
 * `useT()` returns a `t` function that is stable per language and re-renders the
 * component when the language changes, so components never need to read the
 * store themselves.
 */
import { useCallback, useMemo } from 'react'
import { enUS, zhCN } from 'date-fns/locale'
import {
  activeLanguage,
  translate,
  useLanguageStore,
  type Language,
  type TranslationParams,
} from './index'
import type { MessageKey } from './messages'

export function useT() {
  const language = useLanguageStore((state) => state.language)
  return useCallback(
    (key: MessageKey, params?: TranslationParams) => translate(language, key, params),
    [language],
  )
}

/** date-fns locale matching the active UI language. */
export function useDateLocale() {
  const language = useLanguageStore((state) => state.language)
  return useMemo(() => (language === 'zh' ? zhCN : enUS), [language])
}

/** Current language for UI that needs to branch on it (e.g. showing a check mark). */
export function useLanguage(): Language {
  return useLanguageStore((state) => state.language)
}

export { activeLanguage }
