import type { CSSProperties, FormEvent } from 'react'
import { useState } from 'react'
import { login } from '../api/client'
import { useI18n } from '../i18n'
import atmosphereArt from '../assets/login-sliced-atmosphere.webp'
import heroPanelArt from '../assets/login-sliced-hero-panel.webp'
import rightDocsArt from '../assets/login-sliced-right-docs.webp'

const disabledMethods = [
  { labelKey: 'login.google', icon: 'G' },
  { labelKey: 'login.apple', icon: '●' },
  { labelKey: 'login.emailCode', icon: '✉' },
]

const heroCards = [
  { titleKey: 'login.heroUploadTitle', copyKey: 'login.heroUploadCopy', icon: '⇧', tags: ['PNG', 'PDF'] },
  { titleKey: 'login.heroExtractTitle', copyKey: 'login.heroExtractCopy', icon: 'OCR', tags: ['PaddleOCR', 'Qwen'] },
  { titleKey: 'login.heroFindTitle', copyKey: 'login.heroFindCopy', icon: '⌕', tags: [] },
]

const trustItems = [
  { titleKey: 'login.heroSecurityTitle', copyKey: 'login.heroSecurityCopy', icon: '◇' },
  { titleKey: 'login.heroPrivacyTitle', copyKey: 'login.heroPrivacyCopy', icon: '▣' },
  { titleKey: 'login.heroSearchTitle', copyKey: 'login.heroSearchCopy', icon: 'ϟ' },
]

export default function LoginPanel({ onLogin }: { onLogin: () => void }) {
  const { language, setLanguage, t } = useI18n()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await login(username, password)
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.failed'))
    }
  }

  const shellStyle = {
    '--sliced-login-bg': `url(${atmosphereArt})`,
    '--sliced-login-hero': `url(${heroPanelArt})`,
    '--sliced-login-right-docs': `url(${rightDocsArt})`,
  } as CSSProperties

  return (
    <main className={`sliced-login-shell sliced-login-shell-${language}`} style={shellStyle}>
      <section className="sliced-login-stage" aria-label={t('login.aria')}>
        <div className="sliced-login-hero-panel" aria-hidden={language === 'en'} />
        <LiveHero />
        <div className="sliced-login-right-pane" aria-hidden="true" />
        <div className="sliced-login-right-docs" aria-hidden="true" />

        <div className="sliced-login-language" aria-label={t('language.label')}>
          <button type="button" className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')}>EN</button>
          <button type="button" className={language === 'de' ? 'active' : ''} onClick={() => setLanguage('de')}>DE</button>
        </div>

        <form className="sliced-login-card" onSubmit={submit}>
          <div className="sliced-login-heading">
            <h1>{t('login.title')}</h1>
            <p>{t('login.subtitle')}</p>
          </div>

          <div className="sliced-login-methods" aria-label={t('login.comingLater')}>
            {disabledMethods.map((method) => (
              <button key={method.labelKey} type="button" disabled title={t('login.comingLater')}>
                <span>{method.icon}</span>
                <strong>{t(method.labelKey)}</strong>
              </button>
            ))}
          </div>

          <div className="sliced-login-divider"><span>{t('login.or')}</span></div>

          <label className="sliced-login-field">
            <span>{t('login.username')}</span>
            <input
              autoComplete="username"
              placeholder={t('login.username')}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>

          <label className="sliced-login-field">
            <span>{t('login.password')}</span>
            <div className="sliced-login-password-row">
              <input
                autoComplete="current-password"
                placeholder={t('login.password')}
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? t('login.hidePasswordAria') : t('login.showPasswordAria')}>
                {showPassword ? t('login.hidePassword') : t('login.showPassword')}
              </button>
            </div>
          </label>

          <button className="sliced-login-forgot" type="button" disabled title={t('login.passwordResetUnavailable')}>
            {t('login.forgotPassword')}
          </button>

          {error && <p className="sliced-login-error" role="alert">{error}</p>}

          <button className="sliced-login-submit" type="submit">{t('login.submit')}</button>

          <p className="sliced-login-terms">
            {t('login.termsPrefix')} <span>{t('login.terms')}</span><br />
            {t('login.and')} <span>{t('login.privacy')}</span>.
          </p>
        </form>
      </section>
    </main>
  )
}

function LiveHero() {
  const { t } = useI18n()
  return (
    <section className="sliced-login-live-hero" aria-label={t('login.heroTitle')}>
      <div className="sliced-login-live-brand"><span>D</span><strong>Dok</strong></div>
      <h2>{t('login.heroTitle')}</h2>
      <p>{t('login.heroSubtitle')}</p>
      <div className="sliced-login-live-cards">
        {heroCards.map((card) => (
          <article key={card.titleKey}>
            <em>{card.icon}</em>
            <strong>{t(card.titleKey)}</strong>
            <span>{t(card.copyKey)}</span>
            {card.tags.length > 0 && <small>{card.tags.map((tag) => <b key={tag}>{tag}</b>)}</small>}
          </article>
        ))}
      </div>
      <div className="sliced-login-live-trust">
        {trustItems.map((item) => (
          <span key={item.titleKey}><i>{item.icon}</i><strong>{t(item.titleKey)}</strong><small>{t(item.copyKey)}</small></span>
        ))}
      </div>
    </section>
  )
}
