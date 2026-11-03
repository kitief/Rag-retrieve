import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { Brain, Sparkles } from 'lucide-react'
import { useT } from '@/i18n/useT'
import type { MessageKey } from '@/i18n/messages'

interface AuthLayoutProps {
  /** Brand line under the logo (already-translated string). */
  brand: string
  /** Tagline under the brand (already-translated string). */
  tagline: string
  /** Translation keys rendered as the hero feature list; empty hides the list. */
  features?: readonly MessageKey[]
  /** Swaps the hero gradient direction (login vs register). */
  variant?: 'login' | 'register'
  children: ReactNode
}

/**
 * Shared shell for the login / register pages: an animated hero on the left and
 * a glass card on the right. The two pages only differed in copy, the optional
 * feature list and the hero gradient direction, so both now reuse this layout.
 */
export function AuthLayout({
  brand,
  tagline,
  features = [],
  variant = 'login',
  children,
}: AuthLayoutProps) {
  const t = useT()
  const gradient =
    variant === 'register'
      ? 'bg-gradient-to-br from-surface via-background to-primary/20'
      : 'bg-gradient-to-br from-primary/20 via-background to-surface'

  return (
    <div className="min-h-screen flex bg-background">
      {/* Left — animated hero */}
      <div className={`hidden lg:flex flex-1 items-center justify-center relative overflow-hidden ${gradient}`}>
        <div className="absolute inset-0">
          <div className={`absolute w-64 h-64 bg-primary/20 rounded-full blur-3xl animate-pulse ${variant === 'register' ? 'top-1/3 left-1/3' : 'top-1/4 left-1/4'}`} />
          <div
            className={`absolute w-48 h-48 rounded-full blur-3xl animate-pulse ${variant === 'register' ? 'bottom-1/4 right-1/3 bg-blue-600/20' : 'bottom-1/3 right-1/4 bg-primary/10'}`}
            style={{ animationDelay: variant === 'register' ? '1.5s' : '1s' }}
          />
        </div>
        <div className="relative z-10 text-center px-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center mx-auto mb-6 animate-glow">
            <Brain className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-4xl font-bold gradient-text mb-3">{brand}</h1>
          <p className="text-muted-foreground text-lg max-w-xs">{tagline}</p>
          {features.length > 0 && (
            <div className="mt-8 flex flex-col gap-3 text-sm text-muted-foreground">
              {features.map((key) => (
                <div key={key} className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-primary" />
                  <span>{t(key)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right — form card */}
      <div className="flex-1 flex items-center justify-center px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-sm"
        >
          <div className="glass-card rounded-2xl p-8">{children}</div>
        </motion.div>
      </div>
    </div>
  )
}
