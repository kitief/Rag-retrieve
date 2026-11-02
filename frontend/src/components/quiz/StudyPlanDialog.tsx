/**
 * Study-plan dialog: the only user-facing entry point of the recommendation
 * backend (`GET /chats/{id}/recommendations`).
 *
 * The endpoint reads the weak topics of the last five quizzes and asks the LLM
 * for a Markdown study plan. It is a `GET` that calls the LLM, so it must never
 * fire on page load — the query stays disabled until the dialog is opened, and
 * re-opening refetches because the query has no `staleTime` and remounts.
 */
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { GraduationCap, RotateCw } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useRecommendations } from '@/api/quiz'
import { useT } from '@/i18n/useT'

interface StudyPlanDialogProps {
  chatId?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function StudyPlanDialog({ chatId, open, onOpenChange }: StudyPlanDialogProps) {
  const t = useT()
  const { data, isPending, isError, error, refetch, isFetching } = useRecommendations(chatId, {
    enabled: open && !!chatId,
  })

  const plan = data?.recommendations?.trim() ?? ''
  const loading = open && (isPending || (isFetching && !plan))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col gap-3">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <span className="w-7 h-7 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center flex-shrink-0">
              <GraduationCap className="w-4 h-4 text-primary" />
            </span>
            {t('quiz.planTitle')}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {t('quiz.planDesc')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 overflow-y-auto pr-1">
          {loading ? (
            <div className="space-y-2 py-4">
              <p className="text-xs text-muted-foreground animate-pulse">{t('quiz.planGenerating')}</p>
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-3 rounded bg-white/5 animate-pulse"
                  style={{ width: `${92 - i * 14}%` }}
                />
              ))}
            </div>
          ) : isError ? (
            <div className="py-6 text-center space-y-3">
              <p className="text-xs text-destructive">{t('quiz.planFailed')}</p>
              <p className="text-[11px] text-muted-foreground break-words">
                {error instanceof Error ? error.message : ''}
              </p>
              <Button size="sm" variant="outline" onClick={() => void refetch()} className="border-white/15">
                <RotateCw className="w-3.5 h-3.5 mr-1.5" />
                {t('common.retry')}
              </Button>
            </div>
          ) : !plan ? (
            <p className="text-xs text-muted-foreground py-6 text-center">{t('quiz.planEmpty')}</p>
          ) : (
            <div className="text-sm leading-relaxed space-y-1.5">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1({ children }) { return <h3 className="text-base font-semibold mt-3 mb-1.5">{children}</h3> },
                  h2({ children }) { return <h4 className="text-sm font-semibold mt-3 mb-1.5">{children}</h4> },
                  h3({ children }) { return <h4 className="text-sm font-semibold mt-2.5 mb-1">{children}</h4> },
                  p({ children }) { return <p className="mb-2 last:mb-0 text-[13px]">{children}</p> },
                  ul({ children }) { return <ul className="list-disc pl-5 mb-2 space-y-1 text-[13px]">{children}</ul> },
                  ol({ children }) { return <ol className="list-decimal pl-5 mb-2 space-y-1 text-[13px]">{children}</ol> },
                  strong({ children }) { return <strong className="font-semibold text-foreground">{children}</strong> },
                  code({ children }) {
                    return <code className="bg-white/10 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
                  },
                }}
              >
                {plan}
              </ReactMarkdown>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 pt-1 border-t border-white/10">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="text-xs text-muted-foreground"
          >
            <RotateCw className={`w-3.5 h-3.5 mr-1.5 ${isFetching ? 'animate-spin' : ''}`} />
            {t('quiz.planRegenerate')}
          </Button>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} className="border-white/15 text-xs">
            {t('quiz.planClose')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
