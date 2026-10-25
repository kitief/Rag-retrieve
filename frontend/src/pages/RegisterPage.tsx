import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, Lock, User, Brain } from 'lucide-react'
import { useRegisterMutation } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'

export function RegisterPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const register = useRegisterMutation()
  const { toast } = useToast()
  const t = useT()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await register.mutateAsync({ name, email, password })
      navigate('/chats')
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? t('register.failedFallback')
      toast({ title: t('common.error'), description: msg, variant: 'destructive' })
    }
  }

  return (
    <div className="min-h-screen flex bg-background">
      <div className="hidden lg:flex flex-1 items-center justify-center relative overflow-hidden bg-gradient-to-br from-surface via-background to-primary/20">
        <div className="absolute inset-0">
          <div className="absolute top-1/3 left-1/3 w-64 h-64 bg-primary/20 rounded-full blur-3xl animate-pulse" />
          <div className="absolute bottom-1/4 right-1/3 w-48 h-48 bg-blue-600/20 rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1.5s' }} />
        </div>
        <div className="relative z-10 text-center px-8">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center mx-auto mb-6 animate-glow">
            <Brain className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-4xl font-bold gradient-text mb-3">{t('register.brand')}</h1>
          <p className="text-muted-foreground text-lg max-w-xs">
            {t('register.tagline')}
          </p>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center px-6">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-sm">
          <div className="glass-card rounded-2xl p-8">
            <div className="mb-8">
              <h2 className="text-2xl font-bold text-foreground">{t('register.title')}</h2>
              <p className="text-sm text-muted-foreground mt-1">{t('register.subtitle')}</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-xs">{t('register.name')}</Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t('register.namePlaceholder')} required className="pl-10 bg-white/5 border-white/10" />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-xs">{t('login.email')}</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t('login.emailPlaceholder')} required className="pl-10 bg-white/5 border-white/10" />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-xs">{t('login.password')}</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required minLength={8} className="pl-10 bg-white/5 border-white/10" />
                </div>
              </div>

              <Button type="submit" className="w-full btn-gradient text-white border-0 h-11" disabled={register.isPending}>
                {register.isPending ? t('register.creating') : t('register.create')}
              </Button>
            </form>

            <p className="text-xs text-muted-foreground text-center mt-6">
              {t('register.haveAccount')}{' '}
              <Link to="/login" className="text-primary hover:underline font-medium">{t('register.signIn')}</Link>
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
