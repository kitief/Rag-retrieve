import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail, Lock } from 'lucide-react'
import { useLoginMutation } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { useToast } from '@/components/ui/use-toast'
import { useT } from '@/i18n/useT'

const LOGIN_FEATURES = ['login.feature1', 'login.feature2', 'login.feature3'] as const

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const navigate = useNavigate()
  const login = useLoginMutation()
  const { toast } = useToast()
  const t = useT()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await login.mutateAsync({ email, password })
      navigate('/chats')
    } catch {
      toast({
        title: t('login.failedTitle'),
        description: t('login.failedDesc'),
        variant: 'destructive',
      })
    }
  }

  return (
    <AuthLayout
      brand="RagVault"
      tagline={t('login.tagline')}
      features={LOGIN_FEATURES}
      variant="login"
    >
      <div className="mb-8">
        <h2 className="text-2xl font-bold text-foreground">{t('login.welcomeBack')}</h2>
        <p className="text-sm text-muted-foreground mt-1">{t('login.subtitle')}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="email" className="text-xs">{t('login.email')}</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('login.emailPlaceholder')}
              required
              className="pl-10 bg-white/5 border-white/10"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-xs">{t('login.password')}</Label>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              className="pl-10 bg-white/5 border-white/10"
            />
          </div>
        </div>

        <Button
          type="submit"
          className="w-full btn-gradient text-white border-0 h-11"
          disabled={login.isPending}
        >
          {login.isPending ? t('login.signingIn') : t('login.signIn')}
        </Button>
      </form>

      <p className="text-xs text-muted-foreground text-center mt-6">
        {t('login.noAccount')}{' '}
        <Link to="/register" className="text-primary hover:underline font-medium">
          {t('login.register')}
        </Link>
      </p>
    </AuthLayout>
  )
}
