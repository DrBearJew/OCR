import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { ArrowRight, Eye, EyeOff, FileText } from 'lucide-react'
import { completeInitialSetup, getAuthStatus, login } from '../api/client'
import { useI18n } from '../i18n'

export default function LoginPanel({ onLogin }: { onLogin: () => void }) {
  const { language, setLanguage, t } = useI18n()
  const [needsSetup, setNeedsSetup] = useState(false)
  const [statusLoaded, setStatusLoaded] = useState(false)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getAuthStatus()
      .then((status) => {
        if (!active) return
        setNeedsSetup(status.needs_setup)
        if (status.needs_setup && status.default_username) {
          setUsername(status.default_username)
        }
      })
      .catch(() => {
        // Fall back to regular sign-in if status endpoint is unreachable.
      })
      .finally(() => {
        if (active) setStatusLoaded(true)
      })
    return () => {
      active = false
    }
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setError('')

    if (needsSetup) {
      if (password.length < 8) {
        setError(t('login.setupPasswordTooShort'))
        return
      }
      if (password !== confirmPassword) {
        setError(t('login.setupPasswordMismatch'))
        return
      }
    }

    setSubmitting(true)
    try {
      if (needsSetup) {
        await completeInitialSetup(username.trim(), password)
      } else {
        await login(username, password)
      }
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.failed'))
    } finally {
      setSubmitting(false)
    }
  }

  const isDe = language === 'de'
  const canSubmit = !submitting && username.trim().length > 0 && (!needsSetup || (password.length >= 8 && confirmPassword.length > 0))

  return (
    <main className="auth-split" aria-label={t('login.aria')}>
      <section className="auth-editorial" aria-hidden="false">
        <div className="auth-editorial-top">
          <div className="auth-wordmark">
            <span className="auth-logo"><FileText size={17} strokeWidth={2.1} /></span>
            <span>Dok OCR</span>
          </div>
        </div>

        <div className="auth-editorial-body">
          <h1>
            {isDe
              ? <>Ihr papierloses Archiv, <em>lokal gelesen</em> und klar sortiert.</>
              : <>Your paperless archive, <em>read locally</em> and filed cleanly.</>}
          </h1>
          <p className="auth-editorial-lead">
            {isDe
              ? 'Rechnungen, Belege und Verträge auf eigener Hardware erkennen, prüfen und sofort wiederfinden.'
              : 'Extract text, structured fields, and invoice totals on your own hardware — with full-text search across every page.'}
          </p>

          <dl className="auth-pillars">
            <div>
              <dt>01</dt>
              <dd>{isDe ? 'Lokale OCR- und Metadaten-Extraktion ohne Cloud-Zwang' : 'Local OCR & metadata extraction with zero cloud lock-in'}</dd>
            </div>
            <div>
              <dt>02</dt>
              <dd>{isDe ? 'Sammlungen, Schemas und Prüf-Warteschlangen für Belege' : 'Structured collections, custom schemas & scan-verified review'}</dd>
            </div>
            <div>
              <dt>03</dt>
              <dd>{isDe ? 'Volltextsuche und Original-PDF-Ansicht direkt nebeneinander' : 'Instant full-text search alongside original PDF previews'}</dd>
            </div>
          </dl>
        </div>

        <svg className="auth-sheet-motif" viewBox="0 0 360 220" fill="none" aria-hidden="true">
          <rect x="24" y="18" width="210" height="270" rx="6" stroke="currentColor" strokeOpacity="0.14" strokeWidth="1" />
          <rect x="52" y="42" width="210" height="270" rx="6" fill="currentColor" fillOpacity="0.035" stroke="currentColor" strokeOpacity="0.22" strokeWidth="1" />
          <line x1="78" y1="80" x2="176" y2="80" stroke="currentColor" strokeOpacity="0.26" strokeWidth="1.5" />
          <line x1="78" y1="104" x2="232" y2="104" stroke="currentColor" strokeOpacity="0.14" strokeWidth="1" />
          <line x1="78" y1="122" x2="214" y2="122" stroke="currentColor" strokeOpacity="0.14" strokeWidth="1" />
          <line x1="78" y1="140" x2="198" y2="140" stroke="currentColor" strokeOpacity="0.14" strokeWidth="1" />
          <line x1="78" y1="176" x2="232" y2="176" stroke="currentColor" strokeOpacity="0.2" strokeWidth="1" strokeDasharray="3 4" />
          <rect x="172" y="190" width="60" height="14" rx="3" fill="currentColor" fillOpacity="0.16" />
        </svg>
      </section>

      <section className="auth-pane">
        <div className="auth-lang" role="group" aria-label={t('language.label')}>
          <button type="button" className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')}>EN</button>
          <button type="button" className={language === 'de' ? 'active' : ''} onClick={() => setLanguage('de')}>DE</button>
        </div>

        <div className="auth-form-wrap">
          <header className="auth-form-header">
            <h2>{needsSetup ? t('login.setupTitle') : (isDe ? 'Anmelden' : 'Sign in')}</h2>
            <p>{needsSetup ? t('login.setupSubtitle') : t('login.subtitle')}</p>
          </header>

          <form className="auth-form" onSubmit={submit}>
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
              <span>{needsSetup ? t('login.setupPassword') : t('login.password')}</span>
              <div className="auth-password-wrap">
                <input
                  autoComplete={needsSetup ? 'new-password' : 'current-password'}
                  placeholder={needsSetup ? t('login.setupPasswordPlaceholder') : '••••••••'}
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

            {needsSetup && (
              <label className="auth-field">
                <span>{t('login.setupConfirmPassword')}</span>
                <input
                  autoComplete="new-password"
                  placeholder="••••••••"
                  type={showPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </label>
            )}

            {error && <p className="auth-error" role="alert">{error}</p>}

            <button className="primary auth-submit" type="submit" disabled={!statusLoaded || !canSubmit}>
              <span>{submitting ? '…' : (needsSetup ? t('login.setupSubmit') : t('login.submit'))}</span>
              {!submitting && <ArrowRight size={15} />}
            </button>
          </form>

          <p className="auth-foot">
            {needsSetup
              ? t('login.setupFoot')
              : (isDe ? 'Selbstgehostetes Dokumentenarchiv & OCR' : 'Self-hosted document archive & OCR')}
          </p>
        </div>
      </section>
    </main>
  )
}
