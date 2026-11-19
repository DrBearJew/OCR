import type { ReactNode } from 'react'
import { Activity, AlertTriangle, BarChart3, Database, FileSearch, FileText, FolderTree, Layers, ListChecks, LogOut, Menu, Search, Settings } from 'lucide-react'
import { api } from '../api/client'
import { useEffect, useState } from 'react'
import type { IntegrationSummary } from '../types'
import { useI18n, type Language } from '../i18n'

type NavKey = 'dashboard' | 'collections' | 'collection' | 'folders' | 'documents' | 'document' | 'search' | 'processing' | 'failed' | 'schemas' | 'admin' | 'activity' | 'batches' | 'batch'

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
  { keys: ['documents', 'document'], path: '/documents', labelKey: 'nav.documents', icon: FileText },
  { keys: ['search'], path: '/search', labelKey: 'nav.search', icon: Search },
  { keys: ['processing'], path: '/processing', labelKey: 'nav.processing', icon: ListChecks },
  { keys: ['failed'], path: '/failed', labelKey: 'nav.failed', icon: AlertTriangle },
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
      <button className="brand-button" aria-label={t('nav.dashboard')} onClick={() => onNavigate('/dashboard')}>
        <span className="brand-mark"><FileSearch size={18} /></span>
        <span>Dok OCR</span>
      </button>
      <nav>
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <button key={item.labelKey} className={item.keys.includes(active) ? 'active' : ''} aria-label={t(item.labelKey)} onClick={() => onNavigate(item.path)}>
              <Icon size={17} />
              <span>{t(item.labelKey)}</span>
            </button>
          )
        })}
      </nav>
      <button className="logout" onClick={onLogout}>
        <LogOut size={17} /> <span>{t('shell.signOut')}</span>
      </button>
    </aside>
  )
}

export function TopStatusBar({ onNavigate, onToggleSidebar, sidebarCollapsed }: { onNavigate: (path: string) => void; onToggleSidebar: () => void; sidebarCollapsed: boolean }) {
  const { language, setLanguage, t } = useI18n()
  const [summary, setSummary] = useState<IntegrationSummary | null>(null)

  useEffect(() => {
    let active = true
    api.integrations().then((data) => {
      if (active) setSummary(data)
    }).catch(() => {
      if (active) setSummary(null)
    })
    return () => { active = false }
  }, [])

  const status = summarizeSystemHealth(summary, t)
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
        <button
          type="button"
          className={`system-status-pill system-status-${status.state}`}
          title={status.tooltip}
          onClick={() => onNavigate('/admin')}
        >
          <i />
          <span>{status.label}</span>
        </button>
      </div>
      <div className="top-actions">
        <LanguageSwitch language={language} setLanguage={setLanguage} compact />
        <button title={t('shell.globalSearch')} aria-label={t('shell.globalSearch')} onClick={() => onNavigate('/search')}><Search size={18} /></button>
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

function summarizeSystemHealth(summary: IntegrationSummary | null, t: (key: string, fallback?: string) => string) {
  if (!summary) {
    return { state: 'checking' as const, label: t('shell.systemChecking', 'Checking…'), tooltip: t('common.checking') }
  }
  const failing = summary.integrations.filter((item) => !item.ok)
  if (!failing.length) {
    return {
      state: 'healthy' as const,
      label: t('shell.systemOk', 'System OK'),
      tooltip: summary.integrations.map((item) => `${item.name}: OK`).join('\n')
    }
  }
  const coreDown = failing.some((item) => item.name === 'database' || item.name === 'redis')
  return {
    state: coreDown ? 'down' as const : 'warning' as const,
    label: failing.length === 1
      ? `1 ${t('shell.systemIssue', 'issue')}`
      : `${failing.length} ${t('shell.systemIssues', 'issues')}`,
    tooltip: failing.map((item) => `${item.name}: ${item.detail}`).join('\n')
  }
}
