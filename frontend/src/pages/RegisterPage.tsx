import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail, Lock, User } from 'lucide-react'
import { useRegisterMutation } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AuthLayout } from '@/components/layout/AuthLayout'
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
    <AuthLayout
      brand={t('register.brand')}
      tagline={t('register.tagline')}
      variant="register"
    >
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
    </AuthLayout>
  )
}
