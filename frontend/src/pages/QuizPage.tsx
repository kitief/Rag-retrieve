import { motion } from 'framer-motion'
import { History, Zap } from 'lucide-react'
import { useChats } from '@/api/chats'
import { useQueries } from '@tanstack/react-query'
import api from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { formatDistanceToNow } from 'date-fns'
import { parseBackendDate } from '@/lib/utils'
import { useT, useDateLocale } from '@/i18n/useT'
import type { Quiz } from '@/types'

export function QuizPage() {
  const t = useT()
  const { data: chatsData } = useChats()
  const chats = chatsData?.chats ?? []

  // Fetch every chat's quiz history in one batched observer instead of one
  // useQuizHistory call per chat (which would fire an N+1 request storm).
  const quizHistories = useQueries({
    queries: chats.map((chat) => ({
      queryKey: ['quiz-history', chat.id] as const,
      queryFn: async (): Promise<Quiz[]> => {
        const res = await api.get(`/chats/${chat.id}/quiz-history`)
        return res.data
      },
    })),
  })

  return (
    <div className="h-full flex flex-col p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3 border-b border-white/10 pb-4">
        <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center border border-primary/30">
          <History className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">{t('quizHistory.title')}</h1>
          <p className="text-xs text-muted-foreground">{t('quizHistory.subtitle')}</p>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-6 pr-2">
          {chats.map((chat, index) => (
            <ChatQuizSection
              key={chat.id}
              chatTitle={chat.title}
              quizzes={quizHistories[index]?.data ?? []}
            />
          ))}
          {chats.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-12">{t('quizHistory.empty')}</p>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

function ChatQuizSection({ chatTitle, quizzes }: { chatTitle: string; quizzes: Quiz[] }) {
  const t = useT()
  const dateLocale = useDateLocale()

  if (quizzes.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold mb-3 text-muted-foreground">{chatTitle}</h2>
      <div className="grid gap-3">
        {quizzes.map((quiz) => {
          const score = quiz.score ?? null
          const pct = score != null ? Math.round(score) : null
          return (
            <motion.div
              key={quiz.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="glass-card rounded-xl p-4 flex items-center gap-4"
            >
              {/* Score Circle */}
              <div className={`w-12 h-12 rounded-full flex items-center justify-center flex-shrink-0 text-sm font-bold ${pct == null ? 'bg-white/10 text-muted-foreground'
                  : pct >= 80 ? 'bg-success/20 text-success'
                    : pct >= 50 ? 'bg-primary/20 text-primary'
                      : 'bg-destructive/20 text-destructive'
                }`}>
                {pct != null ? `${pct}%` : '-'}
              </div>

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-primary" />
                  {quiz.topic}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t('quizHistory.summary', {
                    count: quiz.total_questions,
                    time: formatDistanceToNow(parseBackendDate(quiz.created_at), {
                      addSuffix: true,
                      locale: dateLocale,
                    }),
                  })}
                </p>
                {quiz.weak_topics && quiz.weak_topics.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {quiz.weak_topics.slice(0, 3).map((topic: string, i: number) => (
                      <Badge key={`${topic}-${i}`} className="text-[10px] bg-orange-500/10 text-orange-400 border-orange-500/20">
                        {topic.length > 30 ? topic.slice(0, 30) + '…' : topic}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
