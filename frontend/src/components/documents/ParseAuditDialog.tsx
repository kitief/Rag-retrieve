/**
 * Parse report for one document.
 *
 * The layered PDF pipeline records how every page was read (digital text layer,
 * scanned image, mixed, blank), which pages were OCR'd and with what confidence,
 * and which pages could not be read at all. Surfacing that here is the whole
 * point of the audit: a user who gets "not enough information" can open this and
 * see immediately whether the answer is missing because the page was never read,
 * or because it was read badly.
 */
import { AlertTriangle, CheckCircle2, ScanLine, FileText, FileWarning } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useT } from '@/i18n/useT'
import type { ParseAudit, PageAudit } from '@/types'

interface ParseAuditDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  audit: ParseAudit | null | undefined
  filename: string
}

function kindKey(kind: PageAudit['kind']) {
  if (kind === 'scanned') return 'doc.audit.scanned' as const
  if (kind === 'hybrid') return 'doc.audit.hybrid' as const
  if (kind === 'blank') return 'doc.audit.blank' as const
  return 'doc.audit.digital' as const
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-sm font-medium text-foreground mt-0.5 truncate" title={value}>
        {value}
      </p>
    </div>
  )
}

export function ParseAuditDialog({ open, onOpenChange, audit, filename }: ParseAuditDialogProps) {
  const t = useT()

  const notable = audit?.pages ?? []
  const unread = audit ? audit.ocr_skipped_pages + audit.ocr_failed_pages : 0
  const confidencePct = audit?.mean_confidence != null ? Math.round(audit.mean_confidence * 100) : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ScanLine className="w-4 h-4 text-primary" />
            {t('doc.audit.title')}
          </DialogTitle>
          <DialogDescription className="truncate" title={filename}>
            {filename} · {t('doc.audit.desc')}
          </DialogDescription>
        </DialogHeader>

        {!audit ? (
          <p className="text-sm text-muted-foreground py-6 text-center">{t('doc.audit.notableEmpty')}</p>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col gap-3">
            {/* ── Headline numbers ─────────────────────────────────────────── */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat label={t('doc.audit.totalPages', { count: audit.total_pages })} value={`${audit.total_pages}`} />
              <Stat label={t('doc.audit.digital')} value={`${audit.digital_pages}`} />
              <Stat label={t('doc.audit.scanned')} value={`${audit.scanned_pages}`} />
              <Stat label={t('doc.audit.blank')} value={`${audit.blank_pages}`} />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat label={t('doc.audit.ocrPages')} value={`${audit.ocr_pages}`} />
              <Stat
                label={t('doc.audit.confidence')}
                value={confidencePct != null ? `${confidencePct}%` : '—'}
              />
              <Stat label={t('doc.audit.chars')} value={audit.text_chars.toLocaleString()} />
              <Stat
                label={t('doc.audit.engine')}
                value={audit.ocr_engine ?? t('doc.audit.engineNone')}
              />
            </div>

            {/* ── Problem banners ──────────────────────────────────────────── */}
            <div className="flex flex-wrap gap-1.5">
              {unread > 0 && (
                <Badge className="text-[10px] bg-destructive/15 text-destructive border-destructive/30 gap-1">
                  <FileWarning className="w-2.5 h-2.5" />
                  {t('doc.audit.skipped', { count: unread })}
                </Badge>
              )}
              {audit.ocr_truncated && (
                <Badge className="text-[10px] bg-amber-500/15 text-amber-400 border-amber-500/30 gap-1">
                  <AlertTriangle className="w-2.5 h-2.5" />
                  {t('doc.audit.truncated')}
                </Badge>
              )}
              {audit.low_confidence_pages.length > 0 && (
                <Badge className="text-[10px] bg-amber-500/15 text-amber-400 border-amber-500/30 gap-1">
                  <AlertTriangle className="w-2.5 h-2.5" />
                  {t('doc.audit.lowConfidence')}: {audit.low_confidence_pages.join(', ')}
                </Badge>
              )}
              {unread === 0 && audit.low_confidence_pages.length === 0 && !audit.ocr_truncated && (
                <Badge className="text-[10px] bg-emerald-500/15 text-emerald-400 border-emerald-500/30 gap-1">
                  <CheckCircle2 className="w-2.5 h-2.5" />
                  {t('doc.audit.notableEmpty')}
                </Badge>
              )}
            </div>

            {/* ── Warnings verbatim ────────────────────────────────────────── */}
            {audit.warnings.length > 0 && (
              <div className="rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-2.5 py-2">
                <p className="text-[10px] font-medium text-amber-400 mb-1">{t('doc.audit.warnings')}</p>
                <ul className="space-y-0.5">
                  {audit.warnings.map((warning, index) => (
                    <li key={index} className="text-[11px] text-amber-200/80 leading-snug">
                      {warning}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* ── Per-page detail ──────────────────────────────────────────── */}
            <div className="flex-1 min-h-0 flex flex-col">
              <p className="text-[11px] font-medium text-muted-foreground mb-1.5">
                {t('doc.audit.notableTitle')}
                <span className="text-muted-foreground/60"> · {notable.length}</span>
              </p>
              {notable.length === 0 ? (
                <p className="text-[11px] text-muted-foreground/70">{t('doc.audit.notableEmpty')}</p>
              ) : (
                <ScrollArea className="flex-1 min-h-0 pr-2">
                  <ul className="space-y-1">
                    {notable.map((page) => (
                      <li
                        key={page.page}
                        className="flex items-start gap-2 rounded-md px-2 py-1.5 bg-white/[0.03] border border-white/5"
                      >
                        <FileText className="w-3 h-3 mt-0.5 flex-shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="text-[11px] text-foreground">
                            {t('doc.audit.pageLine', { page: page.page })}
                            <span className="text-muted-foreground">
                              {' · '}
                              {t('doc.audit.pageKind', {
                                kind: t(kindKey(page.kind)),
                                chars: page.out_chars,
                              })}
                            </span>
                          </p>
                          <div className="flex flex-wrap items-center gap-1 mt-0.5">
                            {page.ocr_used && page.ocr_confidence != null && (
                              <span className="text-[10px] text-emerald-400">
                                {t('doc.audit.pageOcr', {
                                  confidence: Math.round(page.ocr_confidence * 100),
                                })}
                              </span>
                            )}
                            {page.needs_ocr && !page.ocr_used && (
                              <span className="text-[10px] text-destructive">
                                {t('doc.audit.pageNoOcr')}
                              </span>
                            )}
                            {page.preprocess && page.preprocess !== 'none' && (
                              <span className="text-[10px] text-muted-foreground/70">
                                {page.preprocess}
                              </span>
                            )}
                            {page.note && (
                              <span className="text-[10px] text-muted-foreground/70 truncate">
                                {page.note}
                              </span>
                            )}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </ScrollArea>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
