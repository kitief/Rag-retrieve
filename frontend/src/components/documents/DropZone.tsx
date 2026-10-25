import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion } from 'framer-motion'
import { UploadCloud, FileText, Presentation } from 'lucide-react'
import { useUploadDocument } from '@/api/documents'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'

// Audio/video transcription and image OCR are shelved for now, so the uploader
// only accepts PDF and PowerPoint. Re-enable the extra MIME entries below (and
// the matching extensions in SUPPORTED_EXTS) once the backend parsing pipeline
// is turned back on via ENABLE_AUDIO_VIDEO_UPLOADS.
const ACCEPTED_TYPES: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
  'application/vnd.ms-powerpoint': ['.ppt', '.pot', '.pps'],
  'application/x-mspowerpoint': ['.ppt', '.pptx'],
  'application/mspowerpoint': ['.ppt'],
  'application/powerpoint': ['.ppt'],
  'application/x-powerpoint': ['.ppt'],
  'application/x-dos_ms_powerpoint': ['.ppt'],
  // Shelved: video/mp4, video/x-matroska, video/quicktime, video/x-msvideo,
  // video/webm, audio/mpeg, audio/wav, audio/mp4, audio/ogg, audio/flac, audio/aac
}

const SUPPORTED_EXTS = ['.pdf', '.pptx', '.ppt']

const FILE_LABELS = [
  { icon: FileText, label: 'PDF', color: 'text-red-400' },
  { icon: Presentation, label: 'PPTX', color: 'text-orange-400' },
]

interface DropZoneProps {
  chatId: string
}

export function DropZone({ chatId }: DropZoneProps) {
  const t = useT()
  const upload = useUploadDocument(chatId)
  const { toast } = useToast()

  const onDrop = useCallback(
    async (acceptedFiles: File[], rejectedFiles: any[]) => {
      const validFiles: File[] = [...acceptedFiles]
      const actualRejected: any[] = []

      // If browser MIME detection failed for valid extensions like .ppt, rescue them
      for (const rej of rejectedFiles) {
        const file = rej.file
        const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
        if (SUPPORTED_EXTS.includes(ext)) {
          validFiles.push(file)
        } else {
          actualRejected.push(rej)
        }
      }

      if (actualRejected.length > 0) {
        const names = actualRejected.map((r) => r.file.name).join(', ')
        toast({
          title: t('upload.unsupported'),
          description: t('upload.unsupportedDesc', { names }),
          variant: 'destructive',
        })
      }
      for (const file of validFiles) {
        try {
          await upload.mutateAsync(file)
          toast({ title: t('upload.uploading'), description: t('upload.processing', { name: file.name }) })
        } catch {
          toast({
            title: t('upload.failed'),
            description: t('upload.failedDesc', { name: file.name }),
            variant: 'destructive',
          })
        }
      }
    },
    [upload, toast, t]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: 2 * 1024 * 1024 * 1024,
  })

  return (
    <motion.div
      {...(getRootProps() as any)}
      whileHover={{ scale: 1.01 }}
      className={`border-2 border-dashed rounded-xl p-3 cursor-pointer transition-colors duration-200 ${
        isDragActive
          ? 'border-primary bg-primary/10 animate-glow'
          : 'border-white/15 hover:border-primary/50 hover:bg-white/3'
      }`}
    >
      <input {...getInputProps()} />
      <div className="flex flex-col items-center gap-1 text-center">
        <motion.div
          animate={isDragActive ? { scale: [1, 1.15, 1], rotate: [0, -5, 5, 0] } : {}}
          transition={{ repeat: isDragActive ? Infinity : 0, duration: 0.6 }}
        >
          <UploadCloud className={`w-6 h-6 ${isDragActive ? 'text-primary' : 'text-muted-foreground'}`} />
        </motion.div>
        <p className="text-xs font-medium text-foreground">
          {isDragActive ? t('upload.drop') : t('upload.drag')}
        </p>
        <p className="text-[10px] text-muted-foreground">{t('upload.browse')}</p>
        <div className="flex items-center gap-2 mt-0.5 flex-wrap justify-center">
          {FILE_LABELS.map(({ icon: Icon, label, color }) => (
            <div key={label} className="flex items-center gap-0.5">
              <Icon className={`w-2.5 h-2.5 ${color}`} />
              <span className="text-[9px] text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  )
}
