import type { ReactNode } from 'react'
import { Activity, AlertTriangle, BarChart3, Bell, CircleHelp, Database, FileSearch, FileText, FolderKanban, FolderTree, Layers, ListChecks, Menu, Search, Settings, UploadCloud } from 'lucide-react'
import { api } from '../api/client'
import { useEffect, useState } from 'react'
import type { IntegrationSummary } from '../types'

type NavKey = 'dashboard' | 'collections' | 'collection' | 'folders' | 'records' | 'record' | 'documents' | 'document' | 'search' | 'processing' | 'failed' | 'schemas' | 'admin' | 'activity' | 'batches' | 'batch'

interface ShellProps {
  active: NavKey
  children: ReactNode
  onNavigate: (path: string) => void
  onLogout: () => void
}

const navItems = [
  { keys: ['dashboard'], path: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { keys: ['collections', 'collection'], path: '/collections', label: 'Collections', icon: Layers },
  { keys: ['folders'], path: '/folders', label: 'Folders', icon: FolderTree },
  { keys: ['records', 'record'], path: '/records', label: 'Records', icon: FolderKanban },
  { keys: ['documents', 'document'], path: '/documents', label: 'Documents', icon: FileText },
  { keys: ['search'], path: '/search', label: 'Search', icon: Search },
  { keys: ['processing'], path: '/processing', label: 'Processing', icon: ListChecks },
  { keys: ['failed'], path: '/failed', label: 'Failed / Needs Review', icon: AlertTriangle, count: 7 },
  { keys: ['schemas'], path: '/schemas', label: 'Schemas', icon: Database },
  { keys: ['admin'], path: '/admin', label: 'Admin', icon: Settings },
  { keys: ['activity'], path: '/activity', label: 'Activity', icon: Activity }
]

export default function AppShell({ active, children, onNavigate, onLogout }: ShellProps) {
  return (
    <div className="app-shell">
      <Sidebar active={active} onNavigate={onNavigate} onLogout={onLogout} />
      <section className="shell-main">
        <TopStatusBar onNavigate={onNavigate} />
        <div className="content">{children}</div>
      </section>
    </div>
  )
}

function Sidebar({ active, onNavigate, onLogout }: { active: NavKey; onNavigate: (path: string) => void; onLogout: () => void }) {
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
            <button key={item.label} className={item.keys.includes(active) ? 'active' : ''} onClick={() => onNavigate(item.path)}>
              <Icon size={17} />
              <span>{item.label}</span>
              {item.count && <em>{item.count}</em>}
            </button>
          )
        })}
      </nav>
      <div className="sidebar-card">
        <strong>API Access</strong>
        <span>REST API · JSON</span>
        <small><i /> Active</small>
      </div>
      <div className="sidebar-card">
        <strong>Environment</strong>
        <span>Production</span>
      </div>
      <button className="logout" onClick={onLogout}>
        <UploadCloud size={18} /> Sign out
      </button>
    </aside>
  )
}

export function TopStatusBar({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [summary, setSummary] = useState<IntegrationSummary | null>(null)

  useEffect(() => {
    api.integrations().then(setSummary).catch(() => setSummary(null))
  }, [])

  const chips = buildHealthChips(summary)
  return (
    <header className="top-status-bar">
      <button className="top-menu" title="Menu"><Menu size={20} /></button>
      <div className="health-chip-row">
        {chips.map((chip) => <StatusChip key={chip.label} {...chip} />)}
      </div>
      <div className="top-actions">
        <button title="Global search" onClick={() => onNavigate('/search')}><Search size={19} /></button>
        <button title="Notifications" className="notification-button"><Bell size={19} /><span>3</span></button>
        <button title="Help"><CircleHelp size={19} /></button>
        <button className="admin-menu"><b>AD</b><span>Admin</span></button>
      </div>
    </header>
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

function buildHealthChips(summary: IntegrationSummary | null) {
  const fallback = [
    { label: 'GLM OCR', detail: 'Checking', state: 'checking' as const },
    { label: 'Qwen Metadata', detail: 'Checking', state: 'checking' as const },
    { label: 'Llama.cpp', detail: 'Checking', state: 'checking' as const },
    { label: 'Storage', detail: 'Checking', state: 'checking' as const },
    { label: 'Worker Queue', detail: 'Checking', state: 'checking' as const },
    { label: 'API', detail: 'Online', state: 'healthy' as const }
  ]
  if (!summary) return fallback
  const byName = new Map(summary.integrations.map((item) => [item.name.toLowerCase(), item]))
  const glm = byName.get('glm_llama')
  const qwen = byName.get('qwen_llama')
  const database = byName.get('database')
  const redis = byName.get('redis')
  return fallback.map((chip) => {
    if (chip.label === 'GLM OCR') return fromIntegration(chip.label, glm)
    if (chip.label === 'Qwen Metadata') return fromIntegration(chip.label, qwen)
    if (chip.label === 'Llama.cpp') {
      if (!glm && !qwen) return chip
      if (glm?.ok && qwen?.ok) return { label: chip.label, detail: 'Healthy', state: 'healthy' as const }
      if (glm?.ok || qwen?.ok) return { label: chip.label, detail: 'Partial', state: 'warning' as const }
      return { label: chip.label, detail: 'Down', state: 'down' as const }
    }
    if (chip.label === 'Storage') return fromIntegration(chip.label, database)
    if (chip.label === 'Worker Queue') return fromIntegration(chip.label, redis, 'Healthy (Redis)')
    if (chip.label === 'API') return { label: chip.label, detail: 'Online', state: 'healthy' as const }
    return chip
  })
}

function fromIntegration(label: string, item: IntegrationSummary['integrations'][number] | undefined, healthyDetail = 'Healthy') {
  if (!item) return { label, detail: 'Checking', state: 'checking' as const }
  return { label, detail: item.ok ? healthyDetail : 'Down', state: item.ok ? 'healthy' as const : 'down' as const }
}
