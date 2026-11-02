import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Trash2, Zap, ChevronRight, ChevronLeft, Brain, MessageSquare, BookOpen, Sparkles, RotateCw, Pencil, Check, X
} from 'lucide-react'
import { useMessages, streamMessage } from '@/api/messages'
import { useChat, useClearKnowledge, useUpdateChat, useDeleteChat } from '@/api/chats'
import { useDocuments } from '@/api/documents'
import { useGenerateQuiz, useSubmitQuiz } from '@/api/quiz'
import { downloadNotesPdf, useNotes, useGenerateNotes, downloadRemedialNotesPdf, useRemedialNotes, useGenerateRemedialNotes } from '@/api/notes'
import { DocumentList } from '@/components/documents/DocumentList'
import { DropZone } from '@/components/documents/DropZone'
import { MessageBubble, StreamingBubble } from '@/components/chat/MessageBubble'
import { ChatInput } from '@/components/chat/ChatInput'
import { QuizCard, QuizResults } from '@/components/quiz/QuizCard'
import { NotesGeneratingGraphic } from '@/components/notes/NotesGeneratingGraphic'
import { NotesCardsView } from '@/components/notes/NotesCardsView'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/store/authStore'
import { useT } from '@/i18n/useT'
import type { Quiz, QuizResult, ChatListResponse } from '@/types'

function getApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string') {
    return error.response.data.detail
  }
  return error instanceof Error ? error.message : fallback
}

export function ChatDetailPage() {
  const { chatId } = useParams<{ chatId: string }>()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const queryClient = useQueryClient()
  const t = useT()
  const { data: chatData, isError: isChatError } = useChat(chatId!)

  useEffect(() => {
    if (chatData) {
      queryClient.setQueryData<ChatListResponse>(['chats'], (old) => {
        if (!old) return { chats: [chatData] }
        if (!old.chats.some((c) => c.id === chatData.id)) {
          return { chats: [chatData, ...old.chats] }
        }
        return old
      })
    }
  }, [chatData, queryClient])

  useEffect(() => {
    if (isChatError && chatId) {
      queryClient.removeQueries({ queryKey: ['chat', chatId] })
      queryClient.removeQueries({ queryKey: ['documents', chatId] })
      queryClient.removeQueries({ queryKey: ['messages', chatId] })
      queryClient.removeQueries({ queryKey: ['notes', chatId] })
      queryClient.removeQueries({ queryKey: ['remedial-notes', chatId] })
      navigate('/chats', { replace: true })
    }
  }, [isChatError, chatId, navigate, queryClient])

  const abortControllerRef = useRef<AbortController | null>(null)

  const [centerViewMode, setCenterViewMode] = useState<'chat' | 'notes' | 'remedial'>('chat')
  const [rhsTab, setRhsTab] = useState<'quiz' | 'notes'>('quiz')

  useEffect(() => {
    // Abort active stream from previous chat on chatId change
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    setStreamingContent(null)
    setOptimisticUserMessage(null)
    setIsStreaming(false)
    sentMessageCountRef.current = null
    setActiveQuiz(null)
    setQuizResult(null)
    setSelectedQuizType(null)
    setCenterViewMode('chat')
    setRhsTab('quiz')

    if (chatId && user?.id) {
      localStorage.setItem(`ragvault-last-chat:${user.id}`, chatId)
    }

    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [chatId])

  const { data: messagesData } = useMessages(chatId!)
  const { data: docsData } = useDocuments(chatId!)
  const docCount = docsData?.documents?.length ?? 0
  const documentsProcessing = docsData?.documents?.some((doc) => doc.status === 'processing') ?? false
  const { data: notesData } = useNotes(chatId!)
  const generateNotes = useGenerateNotes(chatId!)
  const { data: remedialNotesData } = useRemedialNotes(chatId!)
  const generateRemedialNotes = useGenerateRemedialNotes(chatId!)

  const clearKnowledge = useClearKnowledge()
  const generateQuiz = useGenerateQuiz(chatId!)
  const submitQuiz = useSubmitQuiz()
  const updateChat = useUpdateChat()
  const deleteChat = useDeleteChat()
  const { toast } = useToast()

  const [streamingContent, setStreamingContent] = useState<string | null>(null)
  const [optimisticUserMessage, setOptimisticUserMessage] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const sentMessageCountRef = useRef<number | null>(null)
  const [docsPanelOpen, setDocsPanelOpen] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [quizTopic, setQuizTopic] = useState('')
  const [selectedQuizType, setSelectedQuizType] = useState<'auto' | 'topic' | null>(null)
  const [activeQuiz, setActiveQuiz] = useState<Quiz | null>(null)
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null)
  const [isDownloadingNotesPdf, setIsDownloadingNotesPdf] = useState(false)
  const [isDownloadingRemedialPdf, setIsDownloadingRemedialPdf] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [headerTitle, setHeaderTitle] = useState('')

  useEffect(() => {
    if (chatData?.title) {
      setHeaderTitle(chatData.title)
    }
  }, [chatData?.title])

  const handleSaveHeaderTitle = async () => {
    if (!chatId || !headerTitle.trim()) return
    try {
      await updateChat.mutateAsync({ chatId, title: headerTitle.trim() })
      setIsEditingTitle(false)
      toast({ description: t('chat.renamed') })
    } catch {
      toast({ title: t('common.error'), description: t('chat.renameFailed'), variant: 'destructive' })
    }
  }

  const handleDeleteCurrentChat = async () => {
    if (!chatId || !chatData) return
    if (!confirm(t('chat.deleteConfirm', { title: chatData.title }))) return
    try {
      if (user?.id) {
        const key = `ragvault-last-chat:${user.id}`
        if (localStorage.getItem(key) === chatId) {
          localStorage.removeItem(key)
        }
      }
      await deleteChat.mutateAsync({ chatId, purge: true })
      toast({ description: t('chat.deleted', { title: chatData.title }) })
      navigate('/chats')
    } catch {
      toast({ title: t('common.error'), description: t('chat.deleteFailed'), variant: 'destructive' })
    }
  }

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const messages = messagesData?.messages ?? []

  // The optimistic bubble must disappear as soon as the persisted copy arrives.
  // Counting messages is not reliable (two invalidations can land out of order,
  // and the refetch may return only the user turn), so compare the actual text.
  const persistedUserEcho =
    optimisticUserMessage !== null &&
    messages.some(
      (msg) =>
        msg.role === 'user' &&
        msg.content.trim() === optimisticUserMessage.trim() &&
        !msg.id.startsWith('temp-'),
    )

  useEffect(() => {
    if (persistedUserEcho) {
      setOptimisticUserMessage(null)
    }
  }, [persistedUserEcho])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, optimisticUserMessage])

  useEffect(() => {
    // Wait for the assistant turn as well — a refetch that only brings back the
    // user message must not tear down the in-flight stream.
    if (
      sentMessageCountRef.current !== null &&
      messages.length >= sentMessageCountRef.current + 2
    ) {
      setOptimisticUserMessage(null)
      setStreamingContent(null)
      sentMessageCountRef.current = null
    }
  }, [messages.length])

  const handleSend = async (content: string) => {
    if (!chatId) return

    // Cancel any existing in-flight stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    sentMessageCountRef.current = messages.length
    setIsStreaming(true)
    setOptimisticUserMessage(content)
    setStreamingContent('')

    try {
      await streamMessage(
        chatId,
        content,
        (token) => {
          if (!controller.signal.aborted) {
            setStreamingContent((prev) => (prev ?? '') + token)
          }
        },
        async () => {
          if (!controller.signal.aborted) {
            setIsStreaming(false)
            try {
              await queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
              await queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
              await queryClient.invalidateQueries({ queryKey: ['chats'] })
              window.setTimeout(() => {
                void queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
                void queryClient.invalidateQueries({ queryKey: ['chats'] })
              }, 5000)
            } finally {
              setOptimisticUserMessage(null)
              setStreamingContent(null)
              sentMessageCountRef.current = null
            }
          }
        },
        (error) => {
          if (!controller.signal.aborted) {
            setOptimisticUserMessage(null)
            setStreamingContent(null)
            setIsStreaming(false)
            sentMessageCountRef.current = null
            toast({
              title: t('chat.answerUnavailable'),
              description: error instanceof Error ? error.message : t('chat.answerFailed'),
              variant: 'destructive',
            })
          }
        },
        controller.signal,
      )
    } catch {
      if (!controller.signal.aborted) {
        setOptimisticUserMessage(null)
        setStreamingContent(null)
        setIsStreaming(false)
        sentMessageCountRef.current = null
      }
    }
  }

  const handleStopStream = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    setIsStreaming(false)
    setOptimisticUserMessage(null)
    setStreamingContent(null)
    sentMessageCountRef.current = null
  }

  const handleOpenNotes = async () => {
    setCenterViewMode('notes')
    if (!notesData && !generateNotes.isPending) {
      try {
        await generateNotes.mutateAsync()
      } catch (error) {
        toast({
          title: t('chat.notesUnavailable'),
          description: getApiErrorMessage(error, t('chat.notesHint')),
          variant: 'destructive',
        })
      }
    }
  }

  const handleDownloadNotesPdf = async () => {
    if (!chatId) return
    setIsDownloadingNotesPdf(true)
    try {
      const savedTo = await downloadNotesPdf(chatId)
      // The desktop shell opens a native save dialog; a null result means the
      // user cancelled it, which needs no error toast.
      if (savedTo) {
        toast({ title: t('chat.pdfSaved'), description: t('chat.pdfSavedDesc', { path: savedTo }) })
      }
    } catch {
      toast({ title: t('chat.pdfFailed'), description: t('chat.pdfHint'), variant: 'destructive' })
    } finally {
      setIsDownloadingNotesPdf(false)
    }
  }

  const handleOpenRemedialNotes = async () => {
    setCenterViewMode('remedial')
    try {
      await generateRemedialNotes.mutateAsync(activeQuiz?.id)
    } catch (error) {
      toast({
        title: t('chat.remedialUnavailable'),
        description: getApiErrorMessage(error, t('chat.remedialHint')),
        variant: 'destructive',
      })
    }
  }

  const handleDownloadRemedialPdf = async () => {
    if (!chatId) return
    setIsDownloadingRemedialPdf(true)
    try {
      const savedTo = await downloadRemedialNotesPdf(chatId)
      if (savedTo) {
        toast({ title: t('chat.pdfSaved'), description: t('chat.pdfSavedDesc', { path: savedTo }) })
      }
    } catch {
      toast({ title: t('chat.remedialPdfFailed'), description: t('chat.remedialPdfHint'), variant: 'destructive' })
    } finally {
      setIsDownloadingRemedialPdf(false)
    }
  }

  const handleGenerateQuiz = async (type: 'auto' | 'topic', topicOverride?: string) => {
    if (!chatId) return
    setSelectedQuizType(type)
    const topic = type === 'auto' ? 'General Summary' : (topicOverride || 'General Summary')
    try {
      const quiz = await generateQuiz.mutateAsync({ topic, num_questions: 20 })
      setActiveQuiz(quiz)
      setQuizResult(null)
    } catch (error) {
      toast({
        title: t('chat.quizUnavailable'),
        description: getApiErrorMessage(error, t('chat.notesHint')),
        variant: 'destructive',
      })
      setSelectedQuizType(null)
    }
  }

  const handleSubmitQuiz = async (answers: Record<string, string>) => {
    if (!activeQuiz) return
    try {
      const result = await submitQuiz.mutateAsync({ quizId: activeQuiz.id, answers })
      setQuizResult(result)
    } catch {
      toast({ title: t('common.error'), description: t('chat.quizFailed'), variant: 'destructive' })
    }
  }


  const handleClearKnowledge = async () => {
    if (!chatId || !confirm(t('chat.clearConfirm'))) return
    try {
      await clearKnowledge.mutateAsync(chatId)
      toast({ description: t('chat.cleared') })
    } catch {
      toast({ title: t('common.error'), description: t('chat.clearFailed'), variant: 'destructive' })
    }
  }

  return (
    <div className="relative flex h-full overflow-hidden">
      {/* Left Panel — Documents (Collapsible Slider) */}
      <motion.div
        animate={{ width: docsPanelOpen ? 288 : 0 }}
        transition={{ duration: 0.3, ease: 'easeInOut' }}
        className="flex-shrink-0 flex flex-col border-r border-white/10 glass overflow-hidden relative"
      >
        {docsPanelOpen && (
          <div className="w-72 min-w-[288px] max-w-[288px] flex flex-col h-full overflow-hidden">
            <div className="px-4 py-3 border-b border-white/10 flex-shrink-0 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-xs font-semibold text-foreground">{t('chat.documents')}</h3>
                <Badge variant="secondary" className="text-[10px]">
                  {docCount === 1
                    ? t('chat.fileCount', { count: docCount })
                    : t('chat.fileCountPlural', { count: docCount })}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="w-6 h-6 text-muted-foreground hover:text-foreground"
                onClick={() => setDocsPanelOpen(false)}
                title={t('chat.hideDocuments')}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
            </div>

            {/* Scrollable document list */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <DocumentList chatId={chatId!} />
            </div>

            {/* Fixed DropZone */}
            <div className="p-3 border-t border-white/10 flex-shrink-0">
              <DropZone chatId={chatId!} />
            </div>

            {/* Clear Knowledge Footer */}
            <div className="p-3 border-t border-white/10 flex-shrink-0">
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-xs text-destructive hover:text-destructive hover:bg-destructive/10 border border-destructive/20"
                onClick={handleClearKnowledge}
              >
                <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                {t('chat.clearKnowledge')}
              </Button>
            </div>
          </div>
        )}
      </motion.div>

      {/* Center Section — Dynamic View (Chat or AI Notes) */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 glass-card flex-shrink-0 gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
            {!docsPanelOpen && (
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs bg-white/5 border-white/10 hover:bg-white/10 text-muted-foreground hover:text-foreground flex items-center gap-1 flex-shrink-0"
                onClick={() => setDocsPanelOpen(true)}
                title={t('chat.showDocuments')}
              >
                <ChevronRight className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">{t('chat.docs', { count: docCount })}</span>
              </Button>
            )}
            <Brain className="w-5 h-5 text-purple-400 flex-shrink-0" />
            {isEditingTitle ? (
              <div className="flex items-center gap-1.5 max-w-sm">
                <Input
                  autoFocus
                  value={headerTitle}
                  onChange={(e) => setHeaderTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void handleSaveHeaderTitle()
                    if (e.key === 'Escape') {
                      setIsEditingTitle(false)
                      setHeaderTitle(chatData?.title ?? '')
                    }
                  }}
                  className="h-7 text-xs bg-white/10 border-primary/40"
                  placeholder={t('chat.chatNamePlaceholder')}
                />
                <Button variant="ghost" size="icon" className="w-6 h-6 text-green-400 hover:bg-green-500/10 flex-shrink-0" onClick={handleSaveHeaderTitle} title={t('chat.saveTitle')}>
                  <Check className="w-3.5 h-3.5" />
                </Button>
                <Button variant="ghost" size="icon" className="w-6 h-6 text-muted-foreground hover:bg-white/10 flex-shrink-0" onClick={() => { setIsEditingTitle(false); setHeaderTitle(chatData?.title ?? '') }} title={t('chat.cancel')}>
                  <X className="w-3.5 h-3.5" />
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-1.5 min-w-0">
                <h2 className="text-sm font-semibold truncate max-w-md" title={chatData?.title ?? t('chat.knowledgeSpace')}>
                  {chatData?.title ?? t('chat.knowledgeSpace')}
                </h2>
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-6 h-6 text-muted-foreground hover:text-primary hover:bg-white/10 flex-shrink-0"
                  onClick={() => {
                    setHeaderTitle(chatData?.title ?? '')
                    setIsEditingTitle(true)
                  }}
                  title={t('chat.rename')}
                >
                  <Pencil className="w-3 h-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-6 h-6 text-muted-foreground hover:text-destructive hover:bg-destructive/10 flex-shrink-0"
                  onClick={handleDeleteCurrentChat}
                  title={t('chat.delete')}
                >
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {/* View Mode Toggle Buttons */}
            <div className="flex items-center gap-1 bg-white/5 p-1 rounded-xl border border-white/10">
              <Button
                variant={centerViewMode === 'chat' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs px-3"
                onClick={() => setCenterViewMode('chat')}
              >
                <MessageSquare className="w-3.5 h-3.5 mr-1.5" />
                {t('chat.tabChat')}
              </Button>
              <Button
                variant={centerViewMode === 'notes' ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 text-xs px-3"
                onClick={handleOpenNotes}
              >
                <Sparkles className="w-3.5 h-3.5 mr-1.5 text-purple-400" />
                {t('chat.tabNotes')}
              </Button>
            </div>
          </div>
        </div>

        {/* Center Main Content Area */}
        {centerViewMode === 'notes' ? (
          <div className="flex-1 overflow-hidden">
            {generateNotes.isPending ? (
              <NotesGeneratingGraphic />
            ) : notesData ? (
              <NotesCardsView
                notes={notesData}
                onRegenerate={() => generateNotes.mutateAsync()}
                onDownloadPdf={handleDownloadNotesPdf}
                isRegenerating={generateNotes.isPending}
                isDownloadingPdf={isDownloadingNotesPdf}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full p-8 text-center">
                <BookOpen className="w-12 h-12 text-purple-400/40 mb-4" />
                <h3 className="text-base font-semibold mb-2">{t('chat.noNotesTitle')}</h3>
                <p className="text-xs text-muted-foreground max-w-sm mb-6 leading-relaxed">
                  {t('chat.noNotesBody')}
                </p>
                <Button
                  onClick={() => generateNotes.mutateAsync()}
                  disabled={generateNotes.isPending}
                  className="btn-gradient text-white border-0 px-6 py-2.5 text-xs rounded-xl"
                >
                  <Sparkles className="w-4 h-4 mr-2" />
                  {t('chat.generateNotes')}
                </Button>
              </div>
            )}
          </div>
        ) : centerViewMode === 'remedial' ? (
          <div className="flex-1 overflow-hidden">
            {generateRemedialNotes.isPending ? (
              <NotesGeneratingGraphic />
            ) : remedialNotesData ? (
              <NotesCardsView
                notes={remedialNotesData}
                onRegenerate={() => generateRemedialNotes.mutateAsync(activeQuiz?.id)}
                onDownloadPdf={handleDownloadRemedialPdf}
                isRegenerating={generateRemedialNotes.isPending}
                isDownloadingPdf={isDownloadingRemedialPdf}
              />
            ) : (
              <div className="flex flex-col items-center justify-center h-full p-8 text-center">
                <Zap className="w-12 h-12 text-amber-400/40 mb-4" />
                <h3 className="text-base font-semibold mb-2">{t('chat.noRemedialTitle')}</h3>
                <p className="text-xs text-muted-foreground max-w-sm mb-6 leading-relaxed">
                  {t('chat.noRemedialBody')}
                </p>
                <Button
                  onClick={handleOpenRemedialNotes}
                  disabled={generateRemedialNotes.isPending}
                  className="btn-gradient text-white border-0 px-6 py-2.5 text-xs rounded-xl"
                >
                  <Sparkles className="w-4 h-4 mr-2 text-amber-300" />
                  {t('chat.generateRemedial')}
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {/* Messages View */}
            <ScrollArea className="flex-1 min-h-0 px-5 py-4">
              <AnimatePresence>
                {messages.length === 0 && !isStreaming && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex flex-col items-center justify-center h-64 text-center gap-3"
                  >
                    <Brain className="w-10 h-10 text-muted-foreground opacity-30" />
                    <p className="text-sm text-muted-foreground">{t('chat.emptyHint1')}</p>
                    <p className="text-xs text-muted-foreground/60">{t('chat.emptyHint2')}</p>
                  </motion.div>
                )}
                {messages.map((msg) => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}
                {optimisticUserMessage !== null && !persistedUserEcho && (
                  <MessageBubble
                    key="temp-optimistic-user"
                    message={{
                      id: 'temp-optimistic-user',
                      chat_id: chatId!,
                      role: 'user',
                      content: optimisticUserMessage,
                      citations: [],
                      created_at: new Date().toISOString(),
                    }}
                  />
                )}
                {streamingContent !== null && (
                  <StreamingBubble key="streaming-bubble" content={streamingContent} />
                )}
              </AnimatePresence>
              <div ref={messagesEndRef} />
            </ScrollArea>

            {/* Input */}
            <ChatInput
              onSend={handleSend}
              onStop={handleStopStream}
              isStreaming={isStreaming}
              disabled={!chatId || documentsProcessing}
              disabledMessage={t('chat.processingDisabled')}
            />
          </div>
        )}
      </div>

      {/* Right Panel — Quiz & AI Notes RHS */}
      <motion.div
        animate={{ width: rightPanelOpen ? 320 : 0 }}
        transition={{ duration: 0.3 }}
        className="flex-shrink-0 flex flex-col border-l border-white/10 glass overflow-hidden"
      >
        {rightPanelOpen && (
          <div className="w-80 flex flex-col h-full overflow-hidden">
            {/* RHS Panel Header with Quiz / Notes Tabs */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-white/10 flex-shrink-0">
              <div className="flex items-center gap-1 bg-white/5 p-0.5 rounded-lg border border-white/10">
                <button
                  onClick={() => setRhsTab('quiz')}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold transition-colors ${rhsTab === 'quiz' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                  <Zap className="w-3.5 h-3.5" />
                  {t('chat.tabQuiz')}
                </button>
                <button
                  onClick={() => {
                    setRhsTab('notes')
                    handleOpenRemedialNotes()
                  }}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold transition-colors ${rhsTab === 'notes' ? 'bg-purple-500/20 text-purple-300' : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                  <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                  {t('chat.remedialSection')}
                </button>
              </div>

              <Button variant="ghost" size="icon" className="w-6 h-6" onClick={() => setRightPanelOpen(false)}>
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>

            {/* RHS Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {rhsTab === 'notes' ? (
                /* RHS Quiz Remedial Notes Card Summary */
                <div className="space-y-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-amber-400" />
                      <h4 className="text-xs font-semibold">{t('chat.remedialCardTitle')}</h4>
                    </div>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                      {t('chat.remedialCardBody')}
                    </p>

                    <Button
                      onClick={handleOpenRemedialNotes}
                      disabled={generateRemedialNotes.isPending}
                      className="w-full btn-gradient text-white border-0 h-8 text-xs rounded-lg mt-1 quiz-generate-btn"
                    >
                      {generateRemedialNotes.isPending ? (
                        <>
                          <RotateCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                          {t('chat.analyzing')}
                        </>
                      ) : remedialNotesData ? (
                        t('chat.viewRemedial')
                      ) : (
                        t('chat.generateWrongNotes')
                      )}
                    </Button>
                  </div>
                </div>
              ) : (
                /* RHS Quiz Content */
                !activeQuiz ? (
                  <div className="flex flex-col gap-4 py-2">
                    <div className="text-center mb-2 flex items-center justify-between">
                      <div className="text-left">
                        <h4 className="text-sm font-semibold">{t('chat.startQuiz')}</h4>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                          {t('chat.startQuizBody')}
                        </p>
                      </div>
                      {selectedQuizType && !generateQuiz.isPending && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-[10px] h-6 px-2 text-muted-foreground hover:text-foreground"
                          onClick={() => setSelectedQuizType(null)}
                        >
                          {t('chat.reset')}
                        </Button>
                      )}
                    </div>

                    {/* Section 1: Auto Quiz */}
                    {selectedQuizType !== 'topic' && (
                      <div className="bg-white/5 border border-white/10 rounded-xl p-3.5 flex flex-col gap-2.5 shadow-sm quiz-card-box">
                        <div className="flex items-center gap-1.5">
                          <Brain className="w-4 h-4 text-purple-400" />
                          <h5 className="text-xs font-semibold">{t('chat.autoQuiz')}</h5>
                        </div>
                        <p className="text-[10px] text-muted-foreground leading-relaxed">
                          {t('chat.autoQuizBody')}
                        </p>
                        <Button
                          onClick={() => handleGenerateQuiz('auto', 'General Summary')}
                          disabled={generateQuiz.isPending}
                          className="w-full btn-gradient text-white border-0 h-8 text-[11px] rounded-lg mt-1 quiz-generate-btn"
                        >
                          {generateQuiz.isPending && selectedQuizType === 'auto'
                            ? t('chat.generating20')
                            : t('chat.generateAuto')}
                        </Button>
                      </div>
                    )}

                    {/* Section 2: Topic Quiz */}
                    {selectedQuizType !== 'auto' && (
                      <div className="bg-white/5 border border-white/10 rounded-xl p-3.5 flex flex-col gap-2.5 shadow-sm quiz-card-box">
                        <div className="flex items-center gap-1.5">
                          <Zap className="w-4 h-4 text-purple-400" />
                          <h5 className="text-xs font-semibold">{t('chat.topicQuiz')}</h5>
                        </div>
                        <p className="text-[10px] text-muted-foreground leading-relaxed">
                          {t('chat.topicQuizBody')}
                        </p>
                        <div className="space-y-2 mt-1">
                          <Input
                            value={quizTopic}
                            onChange={(e) => setQuizTopic(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleGenerateQuiz('topic', quizTopic)}
                            placeholder={t('chat.topicPlaceholder')}
                            disabled={generateQuiz.isPending}
                            className="h-8 text-xs bg-white/5 border-white/10 focus-visible:ring-1 focus-visible:ring-purple-500/50 quiz-topic-input"
                          />
                          <Button
                            onClick={() => handleGenerateQuiz('topic', quizTopic)}
                            disabled={!quizTopic.trim() || generateQuiz.isPending}
                            className="w-full btn-gradient text-white border-0 h-8 text-[11px] rounded-lg quiz-generate-btn"
                          >
                            {generateQuiz.isPending && selectedQuizType === 'topic'
                              ? t('chat.generating20')
                              : t('chat.generateTopic')}
                          </Button>
                        </div>
                      </div>
                    )}

                    {selectedQuizType && generateQuiz.isPending && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-xs text-muted-foreground hover:text-foreground border border-white/10"
                        onClick={() => setSelectedQuizType(null)}
                      >
                        {t('chat.cancelOrShowAll')}
                      </Button>
                    )}
                  </div>
                ) : quizResult ? (
                  <QuizResults
                    result={quizResult}
                    chatId={chatId}
                    onRetry={() => { setActiveQuiz(null); setQuizResult(null); setSelectedQuizType(null) }}
                    onGenerateRemedialNotes={handleOpenRemedialNotes}
                    isGeneratingRemedial={generateRemedialNotes.isPending}
                  />
                ) : (
                  <div className="space-y-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-[11px] h-7 text-muted-foreground hover:text-foreground px-2"
                      onClick={() => { setActiveQuiz(null); setQuizResult(null); setSelectedQuizType(null) }}
                    >
                      {t('chat.exitQuiz')}
                    </Button>
                    <QuizCard
                      quiz={activeQuiz}
                      onSubmit={handleSubmitQuiz}
                      isSubmitting={submitQuiz.isPending}
                    />
                  </div>
                )
              )}
            </div>
          </div>
        )}
      </motion.div>

      {/* Collapsed right panel toggle */}
      {!rightPanelOpen && (
        <Button
          variant="ghost"
          size="icon"
          className="absolute right-2 top-1/2 z-20 -translate-y-1/2 w-8 h-8 bg-background/80 border border-white/10 shadow-lg"
          onClick={() => setRightPanelOpen(true)}
          title={activeQuiz ? t('chat.resumeQuiz') : t('chat.showQuizNotes')}
        >
          {activeQuiz ? <Zap className="w-4 h-4 text-primary" /> : <ChevronLeft className="w-4 h-4" />}
        </Button>
      )}
    </div>

  )
}
