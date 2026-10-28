/**
 * Settings dialog.
 *
 * Layout mirrors a desktop settings window: a narrow grouped navigation on the
 * left and the active panel on the right. Two groups are exposed today —
 * **Language** (interface + AI output language) and **API** (model provider
 * credentials) — and new groups only need another ``NAV_ITEMS`` entry.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Cpu,
  ExternalLink,
  Globe2,
  KeyRound,
  Loader2,
  PlugZap,
  Plus,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'
import {
  SUPPORTED_LANGUAGES,
  normalizeLanguage,
  useLanguageStore,
  type Language,
} from '@/i18n'
import {
  useConnectLlm,
  useCreateApiKey,
  useDeleteApiKey,
  useResetSettings,
  useSettings,
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
  /**
   * Section to show when the dialog opens. First-run onboarding jumps straight
   * to "api", because the only thing standing between a fresh install and a
   * working assistant is a key.
   */
  initialSection?: Section
}

export function SettingsDialog({
  open,
  onOpenChange,
  initialSection,
}: SettingsDialogProps) {
  const t = useT()
  const { toast } = useToast()
  const [section, setSection] = useState<Section>(initialSection ?? 'language')

  const language = useLanguageStore((state) => state.language)
  const setLanguage = useLanguageStore((state) => state.setLanguage)

  const { data, isLoading, isError } = useSettings(open)
  const updateSettings = useUpdateSettings()
  const resetSettings = useResetSettings()
  const connectLlm = useConnectLlm()
  const createApiKey = useCreateApiKey()
  const updateApiKey = useUpdateApiKey()
  const deleteApiKey = useDeleteApiKey()

  // ── Local form state, seeded from the server payload ─────────────────────
  const [provider, setProvider] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [manualModel, setManualModel] = useState(false)
  /**
   * Models the endpoint returned for the *current* connection attempt.
   *
   * Deliberately empty until "Connect" succeeds: a model name that was never
   * verified against the endpoint is the single most common way to save a
   * broken configuration, so the field starts blank and is filled with the
   * first model the endpoint advertises.
   */
  const [connectedModels, setConnectedModels] = useState<string[]>([])
  const [connection, setConnection] = useState<{ ok: boolean; message: string } | null>(null)

  const seedFrom = (payload: SettingsResponse | undefined) => {
    if (!payload) return
    setProvider(payload.llm.provider)
    setBaseUrl(payload.llm.base_url)
    setApiKey('')
    setManualModel(false)

    // The last probe is persisted server-side, so reopening the dialog shows the
    // same green badge instead of asking the user to prove again what the backend
    // already knows. A stale probe (endpoint or key changed since) is discarded.
    const stored = payload.llm.connection
    if (stored && stored.ok && !stored.stale) {
      setConnectedModels(stored.models)
      setConnection({ ok: true, message: stored.message })
      // Remember a confirmed model, but never resurrect one the endpoint did not
      // advertise — that is exactly the unverified name this panel avoids.
      const remembered = payload.llm.model
      setModel(remembered && stored.models.includes(remembered) ? remembered : stored.models[0] ?? '')
      setManualModel(stored.models.length === 0)
    } else {
      // Nothing trustworthy to restore: the model stays blank until "Connect".
      setModel('')
      setConnectedModels([])
      setConnection(stored ? { ok: false, message: stored.message } : null)
    }
  }

  /**
   * Seed the form exactly once per opening.
   *
   * A plain ``[open, data]`` effect would re-run on every background refetch —
   * including the one triggered right after saving a key — and would wipe the
   * model the user just picked from the dropdown. The ref makes the seed a
   * one-shot per dialog opening; everything the user typed survives refetches.
   */
  const seededRef = useRef(false)
  useEffect(() => {
    if (!open) {
      seededRef.current = false
      return
    }
    if (!data || seededRef.current) return
    seededRef.current = true
    seedFrom(data)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, data])

  useEffect(() => {
    if (open && initialSection) setSection(initialSection)
    // Only react to the dialog opening, not to later section clicks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const providerOptions = data?.providers ?? []
  const savedKeys = data?.api_keys ?? []
  const activeKey = savedKeys.find((item) => item.active)

  const selectedPreset = useMemo(
    () => providerOptions.find((item) => item.name === provider),
    [providerOptions, provider],
  )

  // ── Model discovery ──────────────────────────────────────────────────────
  // There is no background fetch: the list only exists after an explicit
  // "Connect", so the dropdown can never offer a model the endpoint rejected.
  const connected = connection?.ok === true
  const modelChoices = useMemo(() => {
    const set = new Set(connectedModels)
    if (model.trim()) set.add(model.trim())
    return Array.from(set)
  }, [connectedModels, model])

  const handleProviderChange = (nextProvider: string) => {
    setProvider(nextProvider)
    const preset = providerOptions.find((item) => item.name === nextProvider)
    if (preset) setBaseUrl(preset.base_url)
    // Switching provider invalidates the previous connection.
    setModel('')
    setConnectedModels([])
    setConnection(null)
  }

  /** Probe the endpoint with the credentials in the form and fill the dropdown. */
  const handleConnect = async () => {
    setConnection(null)
    try {
      const result = await connectLlm.mutateAsync({
        llm_provider: provider || 'custom',
        llm_base_url: baseUrl.trim(),
        // An empty field means "use the stored key" — same rule as saving.
        llm_api_key: apiKey.trim() || null,
      })
      setConnectedModels(result.models)
      setModel(result.models[0] ?? '')
      setManualModel(result.models.length === 0)
      setConnection({ ok: result.ok, message: result.message })
    } catch {
      setConnectedModels([])
      setModel('')
      setConnection({ ok: false, message: t('settings.connectFailedShort') })
    }
  }

  const handleSave = async () => {
    try {
      const payload: Record<string, string> = { llm_provider: provider }
      // Only send values the user actually filled in: the API treats an empty
      // string as "delete the stored override", which would silently reset a
      // working endpoint just because a field was left blank.
      if (baseUrl.trim()) payload.llm_base_url = baseUrl.trim()
      if (model.trim()) payload.llm_model = model.trim()
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

  /**
   * Store the typed key in the vault and activate it in one step.
   *
   * Saving through the vault (instead of only through ``PUT /settings``) is
   * what makes the key reusable later: the menu beside the input lists every
   * saved key so switching back and forth never needs a retype.
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
        label: '',
        value,
        activate: true,
      })
      setApiKey('')
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

                  {/* Base URL */}
                  <div className="space-y-1.5">
                    <Label htmlFor="settings-base-url" className="text-xs">
                      {t('settings.baseUrl')}
                    </Label>
                    <Input
                      id="settings-base-url"
                      className="h-9 text-sm"
                      value={baseUrl}
                      onChange={(event) => {
                        setBaseUrl(event.target.value)
                        // The previous connection no longer describes this endpoint.
                        setConnectedModels([])
                        setModel('')
                        setConnection(null)
                      }}
                      placeholder="https://api.deepseek.com/v1"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      {t('settings.baseUrlHint')}
                    </p>
                  </div>

                  {/* API key + saved-keys menu, side by side */}
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

                      {/* Saved keys and "save this key" live together in one menu */}
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-9 flex-shrink-0 gap-1.5 text-xs"
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                            <span className="max-w-[9rem] truncate">
                              {activeKey ? activeKey.hint : t('settings.keyMenu')}
                            </span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-64">
                          <DropdownMenuLabel className="text-[11px] font-medium text-muted-foreground">
                            {t('settings.savedKeys')}
                          </DropdownMenuLabel>
                          {savedKeys.length === 0 ? (
                            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">
                              {t('settings.savedKeysEmpty')}
                            </p>
                          ) : (
                            savedKeys.map((item) => (
                              <DropdownMenuItem
                                key={item.id}
                                onSelect={() => void handleActivateKey(item.id)}
                                className="gap-2 text-xs"
                              >
                                <Check
                                  className={`h-3.5 w-3.5 flex-shrink-0 ${
                                    item.active ? 'text-primary' : 'opacity-0'
                                  }`}
                                />
                                <span className="min-w-0 flex-1 truncate">
                                  {item.label} · {item.hint}
                                </span>
                              </DropdownMenuItem>
                            ))
                          )}
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => void handleSaveKey()}
                            disabled={!apiKey.trim() || createApiKey.isPending}
                            className="gap-2 text-xs"
                          >
                            {createApiKey.isPending ? (
                              <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin" />
                            ) : (
                              <Plus className="h-3.5 w-3.5 flex-shrink-0" />
                            )}
                            {t('settings.saveCurrentKey')}
                          </DropdownMenuItem>
                          {activeKey && (
                            <DropdownMenuItem
                              onSelect={() => void handleDeleteKey(activeKey.id)}
                              disabled={deleteApiKey.isPending}
                              className="gap-2 text-xs text-destructive focus:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5 flex-shrink-0" />
                              {t('settings.keyDelete')}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
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

                  {/* Model — stays empty until "Connect" confirms the endpoint */}
                  <div className="space-y-1.5">
                    <Label htmlFor="settings-model" className="text-xs">
                      {t('settings.model')}
                    </Label>
                    <div className="flex items-center gap-1.5">
                      {connected ? (
                        manualModel || modelChoices.length === 0 ? (
                          <Input
                            id="settings-model"
                            className="h-9 flex-1 text-sm"
                            value={model}
                            onChange={(event) => setModel(event.target.value)}
                            placeholder="deepseek-chat"
                          />
                        ) : (
                          <Select
                            value={model}
                            onValueChange={(next) => {
                              if (next === MANUAL_MODEL) {
                                setManualModel(true)
                                return
                              }
                              setModel(next)
                            }}
                          >
                            <SelectTrigger
                              id="settings-model"
                              aria-label={t('settings.model')}
                              className="h-9 flex-1"
                            >
                              <SelectValue placeholder={t('settings.modelPick')} />
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
                        )
                      ) : (
                        <Input
                          id="settings-model"
                          className="h-9 flex-1 text-sm"
                          value=""
                          readOnly
                          disabled
                          placeholder={t('settings.modelConnectFirst')}
                        />
                      )}

                      <Button
                        variant={connected ? 'outline' : 'secondary'}
                        size="sm"
                        className="h-9 flex-shrink-0 gap-1.5 text-xs"
                        onClick={handleConnect}
                        disabled={connectLlm.isPending}
                      >
                        {connectLlm.isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <PlugZap className="h-3.5 w-3.5" />
                        )}
                        {connectLlm.isPending
                          ? t('settings.connecting')
                          : connected
                            ? t('settings.reconnect')
                            : t('settings.connect')}
                      </Button>
                    </div>

                    <p className="text-[10px] text-muted-foreground">
                      {connected
                        ? modelChoices.length === 0
                          ? t('settings.modelsEmpty')
                          : t('settings.modelHint')
                        : t('settings.modelConnectFirst')}
                    </p>
                  </div>

                  {/* Connection status — red until a probe succeeds, green after */}
                  <div
                    role="status"
                    aria-live="polite"
                    className={`flex items-start gap-2 rounded-md border px-3 py-2 text-[11px] ${
                      connection?.ok
                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                        : 'border-destructive/30 bg-destructive/10 text-destructive'
                    }`}
                  >
                    {connection?.ok ? (
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                    ) : (
                      <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                    )}
                    <span className="min-w-0">
                      {connection?.message ?? t('settings.notConnected')}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Footer actions — only the API panel has anything to submit; the
                language choice is applied the moment it is clicked. */}
            <div className="flex items-center justify-between gap-2 border-t border-white/10 px-6 py-3">
              {section === 'api' ? (
                <>
                  <span className="text-[11px] text-muted-foreground">
                    {connected ? t('settings.connectedHint') : t('settings.notConnectedHint')}
                  </span>
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
