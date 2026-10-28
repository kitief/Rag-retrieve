import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Brain, MessageSquare, Plus, Search, LogOut, ChevronLeft, History, Sun, Moon, Trash2, Pencil, Check, X, Settings,
  PlugZap, Plug
} from 'lucide-react'
import { useChats, useCreateChat, useDeleteChat, useUpdateChat } from '@/api/chats'
import { useAuthStore } from '@/store/authStore'
import { useThemeStore } from '@/store/themeStore'
import { useT, useDateLocale } from '@/i18n/useT'
import { SettingsDialog } from '@/components/settings/SettingsDialog'
import { useSettings } from '@/api/settings'
import { isDesktopBuild } from '@/lib/desktop'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/use-toast'
import { useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { parseBackendDate } from '@/lib/utils'

const FIRST_RUN_FLAG = 'ragvault-onboarding-done'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { chatId } = useParams()
  const navigate = useNavigate()
  const { user, clearAuth } = useAuthStore()
  const { theme, toggleTheme } = useThemeStore()
  const t = useT()
  const dateLocale = useDateLocale()
  const { data: chatsData } = useChats()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsSection, setSettingsSection] = useState<'language' | 'api'>('language')
  const { data: settingsData } = useSettings(true)
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const updateChat = useUpdateChat()

  const chats = chatsData?.chats ?? []
  const filtered = chats.filter((c) =>
    c.title.toLowerCase().includes(search.toLowerCase())
  )

  const handleCreateChat = async () => {
    try {
      const chat = await createChat.mutateAsync({ title: t('chats.defaultTitle') })
      navigate(`/chats/${chat.id}`)
    } catch {
      toast({ title: t('common.error'), description: t('sidebar.createFailed'), variant: 'destructive' })
    }
  }

  const startEditing = (event: React.MouseEvent, id: string, title: string) => {
    event.preventDefault()
    event.stopPropagation()
    setEditingChatId(id)
    setEditingTitle(title)
  }

  const cancelEditing = (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    setEditingChatId(null)
  }

  const saveTitle = async (event?: React.MouseEvent | React.KeyboardEvent) => {
    event?.preventDefault()
    event?.stopPropagation()
    if (!editingChatId || !editingTitle.trim()) return
    try {
      await updateChat.mutateAsync({ chatId: editingChatId, title: editingTitle.trim() })
      setEditingChatId(null)
    } catch {
      toast({ title: t('common.error'), description: t('sidebar.renameFailed'), variant: 'destructive' })
    }
  }

  const handleDeleteChat = async (e: React.MouseEvent, id: string, title: string) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm(t('sidebar.deleteConfirm', { title }))) return
    try {
      if (user?.id) {
        const key = `ragvault-last-chat:${user.id}`
        if (localStorage.getItem(key) === id) {
          localStorage.removeItem(key)
        }
      }
      await deleteChat.mutateAsync({ chatId: id, purge: true })
      toast({ description: t('sidebar.deleted', { title }) })
      if (chatId === id) {
        navigate('/chats')
      }
    } catch {
      toast({ title: t('common.error'), description: t('sidebar.deleteFailed'), variant: 'destructive' })
    }
  }

  const handleLogout = () => {
    queryClient.clear()
    clearAuth()
    navigate('/login')
  }

  // Ctrl+, opens the settings dialog, matching the shortcut shown in the menu.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === ',') {
        event.preventDefault()
        setSettingsOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // First run in the desktop build: a fresh install has no API key, so every AI
  // feature answers with "LLM not configured". Rather than let the user hit that
  // wall, open the settings dialog on the API section once. The flag is stored
  // per install so a user who deliberately skips it is not nagged again.
  useEffect(() => {
    if (!isDesktopBuild()) return
    if (!settingsData) return
    if (settingsData.llm.api_key_set) return
    if (window.localStorage.getItem(FIRST_RUN_FLAG)) return
    setSettingsSection('api')
    setSettingsOpen(true)
  }, [settingsData])

  const dismissFirstRun = () => {
    window.localStorage.setItem(FIRST_RUN_FLAG, '1')
  }

  /**
   * Whether the AI endpoint is actually reachable.
   *
   * The stored probe is the only honest source: a key merely being present says
   * nothing about whether the endpoint accepts it, and a probe recorded against
   * an older base URL or key is returned as ``stale``. Both cases show red.
   */
  const connection = settingsData?.llm.connection
  const isConnected = Boolean(connection?.ok) && !connection?.stale
  const connectedModel = isConnected ? settingsData?.llm.model ?? '' : ''

  const openApiSettings = () => {
    setSettingsSection('api')
    setSettingsOpen(true)
  }

  return (
    <motion.div
      animate={{ width: collapsed ? 64 : 280 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className="relative flex flex-col h-full flex-shrink-0 glass border-r border-white/10 z-30"
    >
      {/* Centered Border Toggle Arrow Button */}
      <button
        type="button"
        onClick={onToggle}
        title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        className="absolute -right-3.5 top-1/2 -translate-y-1/2 z-50 w-7 h-7 rounded-full bg-primary text-primary-foreground border-2 border-background shadow-2xl hover:scale-110 active:scale-95 flex items-center justify-center cursor-pointer transition-all duration-200"
      >
        <ChevronLeft className={`w-4 h-4 transition-transform duration-300 ${collapsed ? 'rotate-180' : ''}`} />
      </button>

      {/* Inner Content */}
      <div className="flex flex-col h-full w-full overflow-hidden">
        {/* Header - Non-clickable static brand */}
        <div className={`flex items-center gap-3 px-4 py-4 border-b border-white/10 select-none ${collapsed ? 'justify-center py-4' : ''}`}>
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center shadow-md">
            <Brain className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="font-semibold text-sm gradient-text whitespace-nowrap"
            >
              RagVault
            </motion.span>
          )}
        </div>

        {!collapsed && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="px-3 py-3">
            {/* Search */}
            <div className="relative mb-3">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('sidebar.searchPlaceholder')}
                className="pl-8 h-8 text-xs bg-white/5 border-white/10"
              />
            </div>

            {/* New Chat Button */}
            <Button onClick={handleCreateChat} className="w-full h-8 text-xs btn-gradient text-white border-0 mb-3" size="sm" disabled={createChat.isPending}>
              <Plus className="w-3.5 h-3.5 mr-1.5" />
              {t('sidebar.newChat')}
            </Button>
          </motion.div>
        )}

        {/* Chat List */}
        <ScrollArea className="flex-1 px-2">
          <div className="space-y-0.5 pb-2">
            {filtered.map((chat) => (
              <motion.div
                key={chat.id}
                whileHover={{ x: 2 }}
                onClick={() => {
                  if (editingChatId !== chat.id) {
                    navigate(`/chats/${chat.id}`)
                  }
                }}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer group transition-all duration-150 ${chatId === chat.id
                  ? 'bg-primary/20 border-l-2 border-primary text-foreground'
                  : 'hover:bg-white/5 text-muted-foreground hover:text-foreground'
                  }`}
              >
                <MessageSquare className="w-4 h-4 flex-shrink-0 text-primary/80" />
                {!collapsed && (
                  <>
                    <div className="flex-1 min-w-0 pr-1">
                      {editingChatId === chat.id ? (
                        <Input
                          autoFocus
                          value={editingTitle}
                          onChange={(event) => setEditingTitle(event.target.value)}
                          onKeyDown={(event) => {
                            event.stopPropagation()
                            if (event.key === 'Enter') void saveTitle(event)
                            if (event.key === 'Escape') setEditingChatId(null)
                          }}
                          onMouseDown={(event) => event.stopPropagation()}
                          onClick={(event) => {
                            event.preventDefault()
                            event.stopPropagation()
                          }}
                          className="h-7 text-xs bg-white/10 border-primary/40 text-foreground"
                          placeholder={t('sidebar.chatNamePlaceholder')}
                        />
                      ) : (
                        <p className="text-xs font-medium truncate text-foreground/90 group-hover:text-foreground" title={chat.title}>
                          {chat.title}
                        </p>
                      )}
                      <p className="text-[10px] text-muted-foreground">
                        {formatDistanceToNow(parseBackendDate(chat.updated_at), {
                          addSuffix: true,
                          locale: dateLocale,
                        })}
                      </p>
                    </div>
                    {editingChatId === chat.id ? (
                      <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="w-7 h-7 bg-green-500/10 text-green-400 hover:bg-green-500/20 hover:text-green-300"
                          onClick={(event) => void saveTitle(event)}
                          title={t('sidebar.saveName')}
                        >
                          <Check className="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="w-7 h-7 bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                          onClick={cancelEditing}
                          title={t('sidebar.cancelRename')}
                        >
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="icon"
                          className={`w-7 h-7 transition-all ${chatId === chat.id
                            ? 'bg-primary/20 text-primary hover:bg-primary/30'
                            : 'bg-white/5 text-muted-foreground hover:bg-primary/20 hover:text-primary'
                            }`}
                          onClick={(event) => startEditing(event, chat.id, chat.title)}
                          title={t('sidebar.rename')}
                          aria-label={t('sidebar.renameAria', { title: chat.title })}
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className={`w-7 h-7 transition-all ${chatId === chat.id
                            ? 'bg-destructive/20 text-destructive hover:bg-destructive/30'
                            : 'bg-white/5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive'
                            }`}
                          onClick={(event) => handleDeleteChat(event, chat.id, chat.title)}
                          title={t('chat.delete')}
                          aria-label={t('sidebar.deleteAria', { title: chat.title })}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </motion.div>
            ))}
            {!collapsed && filtered.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                {search ? t('sidebar.noMatches') : t('sidebar.noChats')}
              </p>
            )}
          </div>
        </ScrollArea>

        {/* Bottom Nav */}
        {!collapsed ? (
          <div className="border-t border-white/10 px-3 py-3 space-y-1">
            <Link to="/quiz">
              <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-8 text-muted-foreground hover:text-foreground">
                <History className="w-3.5 h-3.5 mr-2" /> {t('sidebar.quizHistory')}
              </Button>
            </Link>

            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-xs h-8 text-muted-foreground hover:text-foreground"
              onClick={toggleTheme}
              title={theme === 'dark' ? t('sidebar.switchToLight') : t('sidebar.switchToDark')}
            >
              {theme === 'dark' ? (
                <>
                  <Moon className="w-3.5 h-3.5 mr-2 text-blue-500" /> {t('sidebar.darkMode')}
                </>
              ) : (
                <>
                  <Sun className="w-3.5 h-3.5 mr-2 text-amber-400" /> {t('sidebar.lightMode')}
                </>
              )}
            </Button>

            {/* Connection shortcut — red means the endpoint was never verified,
                green means a probe succeeded and is still describing the config
                in use. Clicking it jumps straight to the API panel. */}
            <Button
              variant="ghost"
              size="sm"
              onClick={openApiSettings}
              data-testid="sidebar-connection"
              data-connected={isConnected ? 'true' : 'false'}
              className={`w-full justify-start text-xs h-8 ${
                isConnected
                  ? 'text-emerald-400 hover:text-emerald-300'
                  : 'text-destructive hover:text-destructive'
              }`}
              title={
                isConnected
                  ? t('sidebar.connectionHintOn', { base_url: connection?.base_url ?? '' })
                  : t('sidebar.connectionHintOff')
              }
            >
              {isConnected ? (
                <>
                  <PlugZap className="w-3.5 h-3.5 mr-2" />
                  <span className="truncate">
                    {connectedModel
                      ? t('sidebar.connectionOn', { model: connectedModel })
                      : t('sidebar.connection')}
                  </span>
                </>
              ) : (
                <>
                  <Plug className="w-3.5 h-3.5 mr-2" />
                  {t('sidebar.connectionOff')}
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="border-t border-white/10 p-2 flex flex-col items-center gap-1">
            <Link to="/quiz" title={t('sidebar.quizHistory')}>
              <Button variant="ghost" size="icon" className="w-8 h-8 text-muted-foreground hover:text-foreground">
                <History className="w-4 h-4" />
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="icon"
              className="w-8 h-8 text-muted-foreground hover:text-foreground"
              onClick={toggleTheme}
              title={theme === 'dark' ? t('sidebar.switchToLight') : t('sidebar.switchToDark')}
            >
              {theme === 'dark' ? <Moon className="w-4 h-4 text-blue-500" /> : <Sun className="w-4 h-4 text-amber-400" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={openApiSettings}
              data-testid="sidebar-connection-collapsed"
              data-connected={isConnected ? 'true' : 'false'}
              className={`w-8 h-8 ${isConnected ? 'text-emerald-400 hover:text-emerald-300' : 'text-destructive hover:text-destructive'}`}
              title={isConnected ? t('sidebar.connectionOn', { model: connectedModel }) : t('sidebar.connectionOff')}
            >
              {isConnected ? <PlugZap className="w-4 h-4" /> : <Plug className="w-4 h-4" />}
            </Button>
          </div>
        )}

        {/* User Row — click opens the account menu (Settings / Sign out) */}
        <div className="border-t border-white/10 p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="account-menu-trigger"
                aria-label={t('settings.open')}
                className={`flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
                  collapsed ? 'justify-center' : ''
                }`}
              >
                <Avatar className="w-7 h-7 flex-shrink-0">
                  <AvatarFallback className="bg-primary/20 text-primary text-xs font-semibold">
                    {user?.name?.charAt(0).toUpperCase() ?? 'U'}
                  </AvatarFallback>
                </Avatar>
                {!collapsed && (
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate">{user?.name}</p>
                    <p className="text-[10px] text-muted-foreground truncate">{user?.email}</p>
                  </div>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align={collapsed ? 'center' : 'start'} className="min-w-[13rem]">
              <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>
                <Settings className="mr-2 h-3.5 w-3.5" />
                <span className="flex-1">{t('settings.open')}</span>
                <span className="ml-3 text-[10px] tracking-wide text-muted-foreground">
                  {t('settings.shortcut')}
                </span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={handleLogout}
                className="text-destructive focus:bg-destructive/10 focus:text-destructive"
              >
                <LogOut className="mr-2 h-3.5 w-3.5" />
                {t('settings.logout')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <SettingsDialog
        open={settingsOpen}
        onOpenChange={(open) => {
          setSettingsOpen(open)
          if (!open) {
            dismissFirstRun()
            setSettingsSection('language')
          }
        }}
        initialSection={settingsSection}
      />
    </motion.div>
  )
}
