import type { FormEvent } from 'react'
import { useState } from 'react'
import { Eye, EyeOff, FileText } from 'lucide-react'
import { login } from '../api/client'
import { useI18n } from '../i18n'

export default function LoginPanel({ onLogin }: { onLogin: () => void }) {
  const { language, setLanguage, t } = useI18n()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      await login(username, password)
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.failed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-shell" aria-label={t('login.aria')}>
      <div className="auth-lang" role="group" aria-label={t('language.label')}>
        <button type="button" className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')}>EN</button>
        <button type="button" className={language === 'de' ? 'active' : ''} onClick={() => setLanguage('de')}>DE</button>
      </div>

      <section className="auth-container">
        <div className="auth-brand">
          <span className="auth-logo" aria-hidden="true"><FileText size={20} strokeWidth={2.2} /></span>
          <h1>Dok OCR</h1>
          <p>{t('login.subtitle')}</p>
        </div>

        <form className="auth-card" onSubmit={submit}>
          <label className="auth-field">
            <span>{t('login.username')}</span>
            <input
              autoComplete="username"
              autoFocus
              placeholder={t('login.username')}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>

          <label className="auth-field">
            <span>{t('login.password')}</span>
            <div className="auth-password-wrap">
              <input
                autoComplete="current-password"
                placeholder="••••••••"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="button"
                className="auth-eye-btn"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? t('login.hidePasswordAria') : t('login.showPasswordAria')}
                title={showPassword ? t('login.hidePassword') : t('login.showPassword')}
              >
                {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </label>

          {error && <p className="auth-error" role="alert">{error}</p>}

          <button className="primary auth-submit" type="submit" disabled={submitting || !username.trim()}>
            {submitting ? '…' : t('login.submit')}
          </button>
        </form>

        <p className="auth-foot">
          {language === 'de' ? 'Selbstgehostetes Dokumentenarchiv & OCR' : 'Self-hosted document archive & OCR'}
        </p>
      </section>
    </main>
  )
}
