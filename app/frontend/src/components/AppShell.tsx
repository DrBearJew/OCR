import type { ReactNode } from 'react'
import { Activity, AlertTriangle, BarChart3, Bell, CircleHelp, Database, FileSearch, FileText, FolderKanban, FolderTree, Layers, ListChecks, Menu, Search, Settings, UploadCloud } from 'lucide-react'
import { api } from '../api/client'
import { useEffect, useState } from 'react'
import type { IntegrationSummary } from '../types'
import { useI18n, type Language } from '../i18n'

type NavKey = 'dashboard' | 'collections' | 'collection' | 'folders' | 'records' | 'record' | 'documents' | 'document' | 'search' | 'processing' | 'failed' | 'schemas' | 'admin' | 'activity' | 'batches' | 'batch'

type TFn = (key: string, fallback?: string) => string

interface ShellProps {
  active: NavKey
  children: ReactNode
  onNavigate: (path: string) => void
  onLogout: () => void
}

const navItems = [
  { keys: ['dashboard'], path: '/dashboard', labelKey: 'nav.dashboard', icon: BarChart3 },
  { keys: ['collections', 'collection'], path: '/collections', labelKey: 'nav.collections', icon: Layers },
  { keys: ['folders'], path: '/folders', labelKey: 'nav.folders', icon: FolderTree },
  { keys: ['records', 'record'], path: '/records', labelKey: 'nav.records', icon: FolderKanban },
  { keys: ['documents', 'document'], path: '/documents', labelKey: 'nav.documents', icon: FileText },
  { keys: ['search'], path: '/search', labelKey: 'nav.search', icon: Search },
  { keys: ['processing'], path: '/processing', labelKey: 'nav.processing', icon: ListChecks },
  { keys: ['failed'], path: '/failed', labelKey: 'nav.failed', icon: AlertTriangle, count: 7 },
  { keys: ['schemas'], path: '/schemas', labelKey: 'nav.schemas', icon: Database },
  { keys: ['admin'], path: '/admin', labelKey: 'nav.admin', icon: Settings },
  { keys: ['activity'], path: '/activity', labelKey: 'nav.activity', icon: Activity }
]

export default function AppShell({ active, children, onNavigate, onLogout }: ShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar active={active} onNavigate={onNavigate} onLogout={onLogout} />
      <section className="shell-main">
        <TopStatusBar
          onNavigate={onNavigate}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        />
        <div className="content">{children}</div>
      </section>
    </div>
  )
}

function Sidebar({ active, onNavigate, onLogout }: { active: NavKey; onNavigate: (path: string) => void; onLogout: () => void }) {
  const { t } = useI18n()
  return (
    <aside className="sidebar">
      <button className="brand-button" onClick={() => onNavigate('/dashboard')}>
        <span className="brand-mark"><FileSearch size={18} /></span>
        <span>Dok OCR</span>
      </button>
      <nav>
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <button key={item.labelKey} className={item.keys.includes(active) ? 'active' : ''} onClick={() => onNavigate(item.path)}>
              <Icon size={17} />
              <span>{t(item.labelKey)}</span>
              {item.count && <em>{item.count}</em>}
            </button>
          )
        })}
      </nav>
      <div className="sidebar-card">
        <strong>{t('shell.apiAccess')}</strong>
        <span>{t('shell.apiDetail')}</span>
        <small><i /> {t('common.active')}</small>
      </div>
      <div className="sidebar-card">
        <strong>{t('shell.environment')}</strong>
        <span>{t('common.production')}</span>
      </div>
      <button className="logout" onClick={onLogout}>
        <UploadCloud size={18} /> <span>{t('shell.signOut')}</span>
      </button>
    </aside>
  )
}

export function TopStatusBar({ onNavigate, onToggleSidebar, sidebarCollapsed }: { onNavigate: (path: string) => void; onToggleSidebar: () => void; sidebarCollapsed: boolean }) {
  const { language, setLanguage, t } = useI18n()
  const [summary, setSummary] = useState<IntegrationSummary | null>(null)

  useEffect(() => {
    api.integrations().then(setSummary).catch(() => setSummary(null))
  }, [])

  const chips = buildHealthChips(summary, t)
  return (
    <header className="top-status-bar">
      <button
        className={`top-menu ${sidebarCollapsed ? 'active' : ''}`}
        title={sidebarCollapsed ? t('shell.expandNav') : t('shell.collapseNav')}
        aria-label={sidebarCollapsed ? t('shell.expandNav') : t('shell.collapseNav')}
        aria-pressed={sidebarCollapsed}
        onClick={onToggleSidebar}
      >
        <Menu size={20} />
      </button>
      <div className="health-chip-row">
        {chips.map((chip) => <StatusChip key={chip.label} {...chip} />)}
      </div>
      <div className="top-actions">
        <LanguageSwitch language={language} setLanguage={setLanguage} compact />
        <button title={t('shell.globalSearch')} aria-label={t('shell.globalSearch')} onClick={() => onNavigate('/search')}><Search size={19} /></button>
        <button title={t('shell.needsReview')} aria-label={t('shell.openNeedsReview')} className="notification-button" onClick={() => onNavigate('/failed')}><Bell size={19} /><span>3</span></button>
        <button title={t('shell.activity')} aria-label={t('shell.openActivity')} onClick={() => onNavigate('/activity')}><CircleHelp size={19} /></button>
        <button className="admin-menu" title={t('shell.adminSettings')} aria-label={t('shell.openAdminSettings')} onClick={() => onNavigate('/admin')}><b>AD</b><span>{t('nav.admin')}</span></button>
      </div>
    </header>
  )
}

function LanguageSwitch({ language, setLanguage, compact = false }: { language: Language; setLanguage: (language: Language) => void; compact?: boolean }) {
  const { t } = useI18n()
  return (
    <div className={`language-switch ${compact ? 'language-switch-compact' : ''}`} aria-label={t('language.label')}>
      <button type="button" className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')}>EN</button>
      <button type="button" className={language === 'de' ? 'active' : ''} onClick={() => setLanguage('de')}>DE</button>
    </div>
  )
}

export function StatusChip({ label, detail, state = 'healthy' }: { label: string; detail: string; state?: 'healthy' | 'warning' | 'down' | 'checking' }) {
  return (
    <span className={`status-chip status-chip-${state}`}>
      <i />
      <span><strong>{label}</strong><small>{detail}</small></span>
    </span>
  )
}

function buildHealthChips(summary: IntegrationSummary | null, t: TFn) {
  const fallback = [
    { label: t('health.paddle'), detail: t('common.checking'), state: 'checking' as const, key: 'paddle' },
    { label: t('health.qwen'), detail: t('common.checking'), state: 'checking' as const, key: 'qwen' },
    { label: t('health.llama'), detail: t('common.checking'), state: 'checking' as const, key: 'llama' },
    { label: t('health.storage'), detail: t('common.checking'), state: 'checking' as const, key: 'storage' },
    { label: t('health.workerQueue'), detail: t('common.checking'), state: 'checking' as const, key: 'worker' },
    { label: t('health.api'), detail: t('common.online'), state: 'healthy' as const, key: 'api' }
  ]
  if (!summary) return fallback
  const byName = new Map(summary.integrations.map((item) => [item.name.toLowerCase(), item]))
  const paddle = byName.get('paddle_vl_llama')
  const glm = byName.get('glm_llama')
  const qwen = byName.get('qwen_llama')
  const database = byName.get('database')
  const redis = byName.get('redis')
  return fallback.map((chip) => {
    if (chip.key === 'paddle') return fromIntegration(chip.label, paddle || glm, t)
    if (chip.key === 'qwen') return fromIntegration(chip.label, qwen, t)
    if (chip.key === 'llama') {
      const ocrOk = Boolean(paddle?.ok || glm?.ok)
      if (!paddle && !glm && !qwen) return chip
      if (ocrOk && qwen?.ok) return { label: chip.label, detail: t('common.healthy'), state: 'healthy' as const, key: chip.key }
      if (ocrOk || qwen?.ok) return { label: chip.label, detail: t('common.partial'), state: 'warning' as const, key: chip.key }
      return { label: chip.label, detail: t('common.down'), state: 'down' as const, key: chip.key }
    }
    if (chip.key === 'storage') return fromIntegration(chip.label, database, t)
    if (chip.key === 'worker') return fromIntegration(chip.label, redis, t, t('common.healthyRedis'))
    if (chip.key === 'api') return { label: chip.label, detail: t('common.online'), state: 'healthy' as const, key: chip.key }
    return chip
  })
}

function fromIntegration(label: string, item: IntegrationSummary['integrations'][number] | undefined, t: TFn, healthyDetail?: string) {
  if (!item) return { label, detail: t('common.checking'), state: 'checking' as const }
  return { label, detail: item.ok ? healthyDetail ?? t('common.healthy') : t('common.down'), state: item.ok ? 'healthy' as const : 'down' as const }
}
