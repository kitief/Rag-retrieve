/**
 * Settings dialog.
 *
 * Layout mirrors a desktop settings window: a narrow grouped navigation on the
 * left and the active panel on the right. Two groups are exposed today —
 * **Language** (interface + AI output language) and **API** (model provider
 * credentials) — and new groups only need another ``NAV_ITEMS`` entry.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  Cpu,
  ExternalLink,
  Globe2,
  KeyRound,
  Loader2,
  PlugZap,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-react'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'
import {
  SUPPORTED_LANGUAGES,
  normalizeLanguage,
  useLanguageStore,
  type Language,
} from '@/i18n'
import {
  useCreateApiKey,
  useDeleteApiKey,
  useLlmModels,
  useResetSettings,
  useSettings,
  useTestLlm,
  useUpdateApiKey,
  useUpdateSettings,
  type SettingsResponse,
} from '@/api/settings'
import type { MessageKey } from '@/i18n/messages'

type Section = 'language' | 'api'

interface NavItem {
  id: Section
  icon: typeof Globe2
  labelKey: MessageKey
  descKey: MessageKey
}

const NAV_ITEMS: NavItem[] = [
  { id: 'language', icon: Globe2, labelKey: 'settings.navLanguage', descKey: 'settings.navLanguageDesc' },
  { id: 'api', icon: Cpu, labelKey: 'settings.navApi', descKey: 'settings.navApiDesc' },
]

const LANGUAGE_LABEL_KEYS: Record<string, MessageKey> = {
  en: 'language.en',
  zh: 'language.zh',
}

/** Sentinel used by the model dropdown to switch to free-text entry. */
const MANUAL_MODEL = '__manual__'

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const t = useT()
  const { toast } = useToast()
  const [section, setSection] = useState<Section>('language')

  const language = useLanguageStore((state) => state.language)
  const setLanguage = useLanguageStore((state) => state.setLanguage)

  const { data, isLoading, isError } = useSettings(open)
  const updateSettings = useUpdateSettings()
  const resetSettings = useResetSettings()
  const testLlm = useTestLlm()
  const createApiKey = useCreateApiKey()
  const updateApiKey = useUpdateApiKey()
  const deleteApiKey = useDeleteApiKey()

  // ── Local form state, seeded from the server payload ─────────────────────
  const [provider, setProvider] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [keyLabel, setKeyLabel] = useState('')
  const [manualModel, setManualModel] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const seedFrom = (payload: SettingsResponse | undefined) => {
    if (!payload) return
    setProvider(payload.llm.provider)
    setBaseUrl(payload.llm.base_url)
    setModel(payload.llm.model)
    setApiKey('')
    setKeyLabel('')
    setManualModel(false)
    setTestResult(null)
  }

  useEffect(() => {
    if (open) seedFrom(data)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, data])

  const providerOptions = data?.providers ?? []
  const savedKeys = data?.api_keys ?? []
  const activeKey = savedKeys.find((item) => item.active)

  const selectedPreset = useMemo(
    () => providerOptions.find((item) => item.name === provider),
    [providerOptions, provider],
  )

  // ── Model discovery ──────────────────────────────────────────────────────
  // Only ask the endpoint while the API panel is visible; the request costs a
  // round trip and depends on the credentials that are currently saved.
  const modelsQuery = useLlmModels(open && section === 'api')
  const availableModels = modelsQuery.data?.models ?? []

  const modelChoices = useMemo(() => {
    const set = new Set(availableModels)
    if (model.trim()) set.add(model.trim())
    return Array.from(set)
  }, [availableModels, model])

  const handleProviderChange = (nextProvider: string) => {
    setProvider(nextProvider)
    const preset = providerOptions.find((item) => item.name === nextProvider)
    if (preset) {
      setBaseUrl(preset.base_url)
      setModel(preset.model)
    }
    setTestResult(null)
  }

  const handleSave = async () => {
    try {
      const payload: Record<string, string> = {
        llm_provider: provider,
        llm_base_url: baseUrl.trim(),
        llm_model: model.trim(),
      }
      // An empty field means "keep the stored key"; only send when typed.
      if (apiKey.trim()) payload.llm_api_key = apiKey.trim()

      await updateSettings.mutateAsync(payload)
      setApiKey('')
      toast({ title: t('settings.saved'), description: t('settings.savedDesc') })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.saveFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleTest = async () => {
    const payload: Record<string, string> = {
      llm_provider: provider,
      llm_base_url: baseUrl.trim(),
      llm_model: model.trim(),
    }
    if (apiKey.trim()) payload.llm_api_key = apiKey.trim()
    try {
      const result = await testLlm.mutateAsync(payload)
      setTestResult({ ok: result.ok, message: result.message })
    } catch {
      setTestResult({ ok: false, message: t('settings.saveFailed') })
    }
  }

  /**
   * Store the typed key in the vault and activate it in one step.
   *
   * Saving through the vault (instead of only through ``PUT /settings``) is
   * what makes the key reusable later: the dropdown above lists every saved
   * key so switching back and forth never needs a retype.
   */
  const handleSaveKey = async () => {
    const value = apiKey.trim()
    if (!value) {
      toast({
        title: t('common.error'),
        description: t('settings.keyRequired'),
        variant: 'destructive',
      })
      return
    }
    try {
      await createApiKey.mutateAsync({
        provider: provider || 'custom',
        label: keyLabel.trim(),
        value,
        activate: true,
      })
      setApiKey('')
      setKeyLabel('')
      toast({ title: t('settings.keySaved'), description: t('settings.keySavedDesc') })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.saveFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleActivateKey = async (keyId: string) => {
    try {
      await updateApiKey.mutateAsync({ id: keyId, activate: true })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.saveFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleDeleteKey = async (keyId: string) => {
    try {
      await deleteApiKey.mutateAsync(keyId)
      toast({ title: t('settings.keyDeleted') })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.keyDeleteFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleLanguageChange = (next: Language) => {
    // Per-browser, applied immediately — same as the sidebar switcher.
    setLanguage(next)
  }

  const activeLanguage = (normalizeLanguage(language) ?? 'en') as Language

  const handleSetDefaultLanguage = async () => {
    try {
      await updateSettings.mutateAsync({ language: activeLanguage })
      toast({ title: t('settings.saved'), description: t('settings.languageDefaultSet') })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.saveFailed'),
        variant: 'destructive',
      })
    }
  }

  const handleReset = async () => {
    try {
      const payload = await resetSettings.mutateAsync()
      seedFrom(payload)
      toast({ title: t('settings.saved'), description: t('settings.resetDone') })
    } catch {
      toast({
        title: t('common.error'),
        description: t('settings.saveFailed'),
        variant: 'destructive',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        className="max-w-3xl gap-0 overflow-hidden p-0 sm:rounded-2xl"
        aria-describedby={undefined}
      >
        <DialogTitle className="sr-only">{t('settings.title')}</DialogTitle>
        <DialogDescription className="sr-only">{t('settings.subtitle')}</DialogDescription>

        <div className="relative flex h-[36rem] max-h-[85vh]">
          {/* Close — top-right corner of the dialog */}
          <DialogClose
            aria-label={t('settings.close')}
            title={t('settings.close')}
            className="absolute right-3 top-3 z-10 rounded-md p-1.5 text-muted-foreground opacity-70 transition hover:bg-white/10 hover:text-foreground hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <X className="h-4 w-4" />
          </DialogClose>

          {/* ── Left: grouped navigation ─────────────────────────────────── */}
          <aside className="flex w-56 flex-shrink-0 flex-col border-r border-white/10 bg-black/20">
            <div className="px-4 pb-2 pt-5">
              <p className="text-sm font-semibold">{t('settings.title')}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {t('settings.subtitle')}
              </p>
            </div>
            <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon
                const isActive = section === item.id
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSection(item.id)}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                      isActive
                        ? 'bg-primary/20 text-primary'
                        : 'text-muted-foreground hover:bg-white/5 hover:text-foreground'
                    }`}
                  >
                    <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" />
                    <span className="min-w-0">
                      <span className="block text-xs font-medium">{t(item.labelKey)}</span>
                      <span className="block truncate text-[10px] opacity-70">
                        {t(item.descKey)}
                      </span>
                    </span>
                  </button>
                )
              })}
            </nav>
            <div className="border-t border-white/10 px-3 py-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-full justify-start text-[11px] text-muted-foreground hover:text-foreground"
                onClick={handleReset}
                disabled={resetSettings.isPending}
              >
                {resetSettings.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                )}
                {t('settings.reset')}
              </Button>
            </div>
          </aside>

          {/* ── Right: panel ─────────────────────────────────────────────── */}
          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex-1 overflow-y-auto px-6 py-5 pr-10">
              {isLoading && (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              )}

              {isError && !isLoading && (
                <p className="text-sm text-destructive">{t('settings.loadFailed')}</p>
              )}

              {!isLoading && !isError && section === 'language' && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold">{t('settings.languageTitle')}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('settings.languageDesc')}
                    </p>
                  </div>

                  <div className="space-y-1.5">
                    {SUPPORTED_LANGUAGES.map((code) => {
                      const isActive = activeLanguage === code
                      return (
                        <button
                          key={code}
                          type="button"
                          onClick={() => handleLanguageChange(code)}
                          aria-pressed={isActive}
                          className={`flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                            isActive
                              ? 'border-primary/40 bg-primary/10 text-foreground'
                              : 'border-white/10 hover:bg-white/5'
                          }`}
                        >
                          <span>{t(LANGUAGE_LABEL_KEYS[code])}</span>
                          {isActive && <Check className="h-4 w-4 text-primary" />}
                        </button>
                      )
                    })}
                  </div>

                  {data && (
                    <div className="space-y-2 rounded-lg border border-white/10 px-3 py-2.5">
                      <p className="text-[11px] text-muted-foreground">
                        {t('settings.languageDefault', {
                          language: t(LANGUAGE_LABEL_KEYS[data.language.current] ?? 'language.en'),
                        })}
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-[11px]"
                        onClick={handleSetDefaultLanguage}
                        disabled={
                          updateSettings.isPending || data.language.current === activeLanguage
                        }
                      >
                        {t('settings.languageMakeDefault')}
                      </Button>
                    </div>
                  )}
                </div>
              )}

              {!isLoading && !isError && section === 'api' && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold">{t('settings.apiTitle')}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t('settings.apiDesc')}
                    </p>
                  </div>

                  {/* Provider — dropdown */}
                  <div className="space-y-1.5">
                    <Label htmlFor="settings-provider" className="text-xs">
                      {t('settings.provider')}
                    </Label>
                    <Select value={provider} onValueChange={handleProviderChange}>
                      <SelectTrigger id="settings-provider" aria-label={t('settings.provider')}>
                        <SelectValue placeholder={t('settings.provider')} />
                      </SelectTrigger>
                      <SelectContent>
                        {providerOptions.map((item) => (
                          <SelectItem key={item.name} value={item.name}>
                            {item.label}
                            {item.base_url ? ` · ${item.base_url}` : ''}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] text-muted-foreground">
                      {t('settings.providerHint')}
                    </p>
                  </div>

                  {/* Saved keys — switch between them */}
                  <div className="space-y-1.5">
                    <Label htmlFor="settings-saved-keys" className="text-xs">
                      {t('settings.savedKeys')}
                    </Label>
                    {savedKeys.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground">
                        {t('settings.savedKeysEmpty')}
                      </p>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <Select
                          value={activeKey?.id ?? ''}
                          onValueChange={handleActivateKey}
                        >
                          <SelectTrigger
                            id="settings-saved-keys"
                            aria-label={t('settings.savedKeys')}
                            className="flex-1"
                          >
                            <SelectValue placeholder={t('settings.keyPick')} />
                          </SelectTrigger>
                          <SelectContent>
                            {savedKeys.map((item) => (
                              <SelectItem key={item.id} value={item.id}>
                                {`${item.label} · ${item.hint}`}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {activeKey && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-9 w-9 flex-shrink-0 text-muted-foreground hover:text-destructive"
                            title={t('settings.keyDelete')}
                            aria-label={t('settings.keyDelete')}
                            onClick={() => handleDeleteKey(activeKey.id)}
                            disabled={deleteApiKey.isPending}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Add a key */}
                  <div className="space-y-1.5">
                    <Label htmlFor="settings-api-key" className="text-xs">
                      {t('settings.apiKey')}
                    </Label>
                    <div className="flex items-center gap-1.5">
                      <Input
                        id="settings-api-key"
                        type="password"
                        autoComplete="off"
                        className="h-9 flex-1 text-sm"
                        placeholder={
                          data?.llm.api_key_set
                            ? t('settings.apiKeySet', { hint: data.llm.api_key_hint })
                            : t('settings.apiKeyPlaceholder')
                        }
                        value={apiKey}
                        onChange={(event) => setApiKey(event.target.value)}
                      />
                      <Input
                        className="h-9 w-40 text-sm"
                        placeholder={t('settings.keyLabelPlaceholder')}
                        aria-label={t('settings.keyLabel')}
                        value={keyLabel}
                        onChange={(event) => setKeyLabel(event.target.value)}
                      />
                      <Button
                        variant="secondary"
                        size="sm"
                        className="h-9 flex-shrink-0 text-xs"
                        onClick={handleSaveKey}
                        disabled={createApiKey.isPending}
                      >
                        {createApiKey.isPending ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                        )}
                        {t('settings.saveKey')}
                      </Button>
                    </div>
                    <p className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                      {data?.llm.api_key_set
                        ? t('settings.apiKeySet', { hint: data.llm.api_key_hint })
                        : t('settings.apiKeyMissing')}
                      {selectedPreset?.api_key_env && (
                        <span className="opacity-70">· {selectedPreset.api_key_env}</span>
                      )}
                      {selectedPreset?.docs_url && (
                        <a
                          href={selectedPreset.docs_url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline"
                        >
                          {t('settings.apiKeyGet')}
                          <ExternalLink className="h-2.5 w-2.5" />
                        </a>
                      )}
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="settings-base-url" className="text-xs">
                        {t('settings.baseUrl')}
                      </Label>
                      <Input
                        id="settings-base-url"
                        className="h-9 text-sm"
                        value={baseUrl}
                        onChange={(event) => setBaseUrl(event.target.value)}
                        placeholder="https://api.deepseek.com/v1"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        {t('settings.baseUrlHint')}
                      </p>
                    </div>

                    {/* Model — dropdown fed by GET /models, with a manual escape hatch */}
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <Label htmlFor="settings-model" className="text-xs">
                          {t('settings.model')}
                        </Label>
                        <button
                          type="button"
                          onClick={() => modelsQuery.refetch()}
                          title={t('settings.modelsRefresh')}
                          aria-label={t('settings.modelsRefresh')}
                          className="rounded p-0.5 text-muted-foreground transition hover:text-foreground"
                        >
                          <RefreshCw
                            className={`h-3 w-3 ${modelsQuery.isFetching ? 'animate-spin' : ''}`}
                          />
                        </button>
                      </div>

                      {manualModel || modelChoices.length === 0 ? (
                        <div className="space-y-1">
                          <Input
                            id="settings-model"
                            className="h-9 text-sm"
                            value={model}
                            onChange={(event) => setModel(event.target.value)}
                            placeholder="deepseek-chat"
                          />
                          {modelChoices.length > 0 && (
                            <button
                              type="button"
                              className="text-[10px] text-primary hover:underline"
                              onClick={() => setManualModel(false)}
                            >
                              {t('settings.modelPick')} ▾
                            </button>
                          )}
                        </div>
                      ) : (
                        <Select
                          value={model}
                          onValueChange={(next) => {
                            if (next === MANUAL_MODEL) {
                              setManualModel(true)
                              return
                            }
                            setModel(next)
                            setTestResult(null)
                          }}
                        >
                          <SelectTrigger id="settings-model" aria-label={t('settings.model')}>
                            <SelectValue placeholder={t('settings.model')} />
                          </SelectTrigger>
                          <SelectContent>
                            {modelChoices.map((name) => (
                              <SelectItem key={name} value={name}>
                                {name}
                              </SelectItem>
                            ))}
                            <SelectSeparator />
                            <SelectItem value={MANUAL_MODEL}>
                              <span className="inline-flex items-center gap-1">
                                <Plus className="h-3 w-3" />
                                {t('settings.modelManual')}
                              </span>
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      )}

                      <p className="text-[10px] text-muted-foreground">
                        {modelsQuery.isLoading
                          ? t('settings.modelsLoading')
                          : modelsQuery.data?.source === 'unavailable'
                            ? t('settings.modelsUnavailable')
                            : modelChoices.length === 0
                              ? t('settings.modelsEmpty')
                              : t('settings.modelHint')}
                      </p>
                    </div>
                  </div>

                  {data && (
                    <div className="rounded-lg border border-white/10 px-3 py-2.5">
                      <p className="text-[11px] font-medium text-muted-foreground">
                        {t('settings.advanced')}
                      </p>
                      <div className="mt-1.5 grid grid-cols-3 gap-2 text-[11px]">
                        <span className="text-muted-foreground">
                          {t('settings.timeout')}
                          <span className="ml-1 text-foreground">
                            {data.llm.timeout_seconds}s
                          </span>
                        </span>
                        <span className="text-muted-foreground">
                          {t('settings.retries')}
                          <span className="ml-1 text-foreground">{data.llm.max_retries}</span>
                        </span>
                        <span className="text-muted-foreground">
                          {t('settings.concurrency')}
                          <span className="ml-1 text-foreground">
                            {data.llm.max_concurrency}
                          </span>
                        </span>
                      </div>
                    </div>
                  )}

                  {testResult && (
                    <p
                      className={`rounded-md border px-3 py-2 text-[11px] ${
                        testResult.ok
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                          : 'border-destructive/30 bg-destructive/10 text-destructive'
                      }`}
                    >
                      {testResult.message}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Footer actions — only the API panel has anything to submit; the
                language choice is applied the moment it is clicked. */}
            <div className="flex items-center justify-between gap-2 border-t border-white/10 px-6 py-3">
              {section === 'api' ? (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground hover:text-foreground"
                    onClick={handleTest}
                    disabled={testLlm.isPending}
                  >
                    {testLlm.isPending ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <PlugZap className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    {testLlm.isPending ? t('settings.testing') : t('settings.test')}
                  </Button>
                  <Button
                    size="sm"
                    className="text-xs"
                    onClick={handleSave}
                    disabled={updateSettings.isPending}
                  >
                    {updateSettings.isPending && (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    )}
                    {updateSettings.isPending ? t('settings.saving') : t('settings.save')}
                  </Button>
                </>
              ) : (
                <>
                  <span className="text-[11px] text-muted-foreground">
                    {t('settings.languageApplied')}
                  </span>
                  <DialogClose asChild>
                    <Button size="sm" className="text-xs">
                      {t('settings.done')}
                    </Button>
                  </DialogClose>
                </>
              )}
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}
