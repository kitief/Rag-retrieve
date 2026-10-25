/**
 * Language switcher.
 *
 * Renders inline in the sidebar footer when expanded (a two-state pill) and as a
 * compact globe toggle when the sidebar is collapsed, mirroring the theme button
 * right above it. The choice is persisted in localStorage and forwarded to the
 * API through the `X-App-Language` header, so UI text, validation messages and
 * generated content all follow the same language.
 */
import { Languages } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SUPPORTED_LANGUAGES, normalizeLanguage, useLanguageStore } from '@/i18n'
import { useLanguage, useT } from '@/i18n/useT'
import type { MessageKey } from '@/i18n/messages'

interface LanguageSwitcherProps {
  collapsed?: boolean
}

const LABEL_KEYS: Record<string, MessageKey> = {
  en: 'language.en',
  zh: 'language.zh',
}

export function LanguageSwitcher({ collapsed = false }: LanguageSwitcherProps) {
  const t = useT()
  const language = useLanguage()
  const setLanguage = useLanguageStore((state) => state.setLanguage)

  const nextLanguage = () => {
    const index = SUPPORTED_LANGUAGES.indexOf(normalizeLanguage(language) ?? 'en')
    setLanguage(SUPPORTED_LANGUAGES[(index + 1) % SUPPORTED_LANGUAGES.length])
  }

  if (collapsed) {
    return (
      <Button
        variant="ghost"
        size="icon"
        className="w-8 h-8 text-muted-foreground hover:text-foreground"
        onClick={nextLanguage}
        title={t('language.switchTo')}
        aria-label={t('language.switchTo')}
      >
        <Languages className="w-4 h-4" />
      </Button>
    )
  }

  return (
    <div
      className="flex items-center gap-1 rounded-md bg-white/5 p-0.5"
      role="group"
      aria-label={t('language.label')}
    >
      <Languages className="w-3.5 h-3.5 ml-1.5 mr-0.5 flex-shrink-0 text-muted-foreground" />
      {SUPPORTED_LANGUAGES.map((code) => {
        const isActive = (normalizeLanguage(language) ?? 'en') === code
        return (
          <button
            key={code}
            type="button"
            onClick={() => setLanguage(code)}
            aria-pressed={isActive}
            className={`flex-1 h-6 rounded text-[11px] font-medium transition-colors ${
              isActive
                ? 'bg-primary/25 text-primary'
                : 'text-muted-foreground hover:text-foreground hover:bg-white/5'
            }`}
          >
            {t(LABEL_KEYS[code])}
          </button>
        )
      })}
    </div>
  )
}
