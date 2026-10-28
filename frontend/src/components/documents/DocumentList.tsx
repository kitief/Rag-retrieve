import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FileText,
  Presentation,
  FileType2,
  FileCode2,
  Table2,
  Video,
  Music,
  Trash2,
  CheckCircle2,
  XCircle,
  Loader2,
  ScanLine,
  AlertTriangle,
  ScrollText,
} from 'lucide-react'
import { useDocuments, useDeleteDocument } from '@/api/documents'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'
import { ParseAuditDialog } from './ParseAuditDialog'
import type { Document } from '@/types'
import type { MessageKey } from '@/i18n/messages'

const fileIcon = (rawExt: string) => {
  const ext = rawExt.startsWith('.') ? rawExt.toLowerCase() : `.${rawExt.toLowerCase()}`
  if (ext === '.pdf') return <FileText className="w-4 h-4 text-red-400" />
  if (ext === '.pptx' || ext === '.ppt') return <Presentation className="w-4 h-4 text-orange-400" />
  // file_type is stored without the leading dot (see documents.py), so both
  // spellings have to be handled.
  if (ext === '.docx' || ext === '.doc') return <FileType2 className="w-4 h-4 text-blue-400" />
  if (ext === '.csv' || ext === '.tsv') return <Table2 className="w-4 h-4 text-cyan-400" />
  if (ext === '.md' || ext === '.markdown') return <FileCode2 className="w-4 h-4 text-green-400" />
  if (ext === '.txt' || ext === '.text') return <FileText className="w-4 h-4 text-slate-300" />
  if (['.mp4', '.mkv', '.mov', '.avi', '.webm'].includes(ext)) return <Video className="w-4 h-4 text-blue-400" />
  return <Music className="w-4 h-4 text-green-400" />
}

const StatusBadge = ({ status }: { status: Document['status'] }) => {
  const t = useT()
  if (status === 'processing') return (
    <Badge className="text-[10px] bg-yellow-500/15 text-yellow-400 border-yellow-500/30 gap-1">
      <Loader2 className="w-2.5 h-2.5 animate-spin" /> {t('doc.processing')}
    </Badge>
  )
  if (status === 'processed') return (
    <Badge className="text-[10px] bg-green-500/15 text-green-400 border-green-500/30 gap-1">
      <CheckCircle2 className="w-2.5 h-2.5" /> {t('doc.ready')}
    </Badge>
  )
  return (
    <Badge className="text-[10px] bg-red-500/15 text-red-400 border-red-500/30 gap-1">
      <XCircle className="w-2.5 h-2.5" /> {t('doc.failed')}
    </Badge>
  )
}

/**
 * Progress for a document that is still being parsed.
 *
 * A scanned book can take minutes of OCR, and a bare spinner gives no way to
 * tell "still working" from "stuck". The stage comes from the pipeline itself
 * (`audit` → `ocr` → `finalize` → `chunk` → `embed` → `store`), so the label
 * says what is actually happening.
 */
const ProgressLine = ({ doc }: { doc: Document }) => {
  const t = useT()
  const percent = Math.max(0, Math.min(100, doc.progress ?? 0))
  const stageKey = `doc.stage.${doc.progress_stage ?? 'parse'}` as MessageKey
  const label = t('doc.progressLabel', { stage: t(stageKey), percent })

  return (
    <div className="mt-1.5 space-y-1">
      <div className="h-1 w-full rounded-full bg-white/10 overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-primary"
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <p className="text-[10px] text-muted-foreground truncate">{label}</p>
    </div>
  )
}

/**
 * Compact summary of the parse audit, clickable to open the full report.
 *
 * Only rendered when the pipeline produced an audit (i.e. PDFs) and something
 * about it is worth knowing: OCR was used, pages were left unread, or the
 * recognizer was unsure. A clean digital PDF gets no badge at all -- there is
 * nothing to act on.
 */
const AuditBadges = ({ doc, onOpen }: { doc: Document; onOpen: () => void }) => {
  const t = useT()
  const audit = doc.parse_audit
  if (!audit) return null

  const unread = audit.ocr_skipped_pages + audit.ocr_failed_pages
  const lowConf = audit.low_confidence_pages.length
  if (audit.ocr_pages === 0 && unread === 0 && lowConf === 0 && !audit.ocr_truncated) return null

  return (
    <button
      type="button"
      onClick={onOpen}
      title={t('doc.audit.open')}
      className="flex flex-wrap items-center gap-1 rounded transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {audit.ocr_pages > 0 && (
        <Badge className="text-[10px] bg-sky-500/15 text-sky-400 border-sky-500/30 gap-1">
          <ScanLine className="w-2.5 h-2.5" />
          {t('doc.audit.badgeOcr', { count: audit.ocr_pages })}
        </Badge>
      )}
      {(unread > 0 || audit.ocr_truncated) && (
        <Badge className="text-[10px] bg-destructive/15 text-destructive border-destructive/30 gap-1">
          <AlertTriangle className="w-2.5 h-2.5" />
          {t('doc.audit.badgeUnread', { count: unread })}
        </Badge>
      )}
      {lowConf > 0 && (
        <Badge className="text-[10px] bg-amber-500/15 text-amber-400 border-amber-500/30 gap-1">
          <AlertTriangle className="w-2.5 h-2.5" />
          {t('doc.audit.badgeLowConf', { count: lowConf })}
        </Badge>
      )}
      <ScrollText className="w-3 h-3 text-muted-foreground" />
    </button>
  )
}

interface DocumentListProps {
  chatId: string
}

export function DocumentList({ chatId }: DocumentListProps) {
  const t = useT()
  const { data, isLoading, isError } = useDocuments(chatId, {
    refetchInterval: (data: any) =>
      data?.documents?.some((d: any) => d.status === 'processing') ? 3000 : false,
  })
  const deleteDoc = useDeleteDocument(chatId)
  const { toast } = useToast()
  const [auditDoc, setAuditDoc] = useState<Document | null>(null)

  const docs = data?.documents ?? []

  if (isLoading && !isError) return <div className="py-4 text-xs text-muted-foreground text-center">{t('doc.loading')}</div>

  if (docs.length === 0) return (
    <div className="py-6 text-center">
      <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-50" />
      <p className="text-xs text-muted-foreground">{t('doc.empty')}</p>
      <p className="text-[10px] text-muted-foreground/60 mt-0.5">{t('doc.emptyHint')}</p>
    </div>
  )

  const handleDelete = async (docId: string, filename: string) => {
    try {
      await deleteDoc.mutateAsync(docId)
      toast({ description: t('doc.removed', { name: filename }) })
    } catch {
      toast({ title: t('common.error'), description: t('doc.deleteFailed'), variant: 'destructive' })
    }
  }

  return (
    <>
      <div className="space-y-1.5 w-full">
      <AnimatePresence>
        {docs.map((doc) => (
          <motion.div
            key={doc.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            className="group flex items-start gap-2 p-2 rounded-lg glass hover:bg-white/8 transition-colors max-w-full overflow-hidden"
          >
            <div className="mt-0.5 flex-shrink-0">{fileIcon(doc.file_type)}</div>
            <div className="flex-1 min-w-0 overflow-hidden">
              <p className="text-xs font-medium truncate text-foreground block max-w-full" title={doc.filename}>{doc.filename}</p>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                <StatusBadge status={doc.status} />
                {doc.total_chunks != null && (
                  <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                    {t('doc.chunks', { count: doc.total_chunks })}
                  </span>
                )}
                {doc.status === 'processed' && (
                  <AuditBadges doc={doc} onOpen={() => setAuditDoc(doc)} />
                )}
              </div>
              {doc.status === 'processing' && <ProgressLine doc={doc} />}
              {doc.status === 'failed' && doc.error_message && (
                <p className="mt-1 text-[10px] text-destructive/80 leading-snug break-words">
                  {doc.error_message}
                </p>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="w-6 h-6 flex-shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all"
              onClick={() => handleDelete(doc.id, doc.filename)}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </motion.div>
        ))}
      </AnimatePresence>
      </div>

      <ParseAuditDialog
        open={auditDoc !== null}
        onOpenChange={(open) => { if (!open) setAuditDoc(null) }}
        audit={auditDoc?.parse_audit ?? null}
        filename={auditDoc?.filename ?? ''}
      />
    </>
  )
}
