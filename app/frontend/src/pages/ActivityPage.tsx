import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { ActivityItem } from '../types'
import { useI18n } from '../i18n'

export default function ActivityPage({ onOpenDocument, onOpenRecord }: { onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void }) {
  const { t } = useI18n()
  const [rows, setRows] = useState<ActivityItem[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load(next = filters) {
    setError('')
    try {
      setRows(await api.activity(next))
    } catch (err) {
      setError(err instanceof Error ? err.message : t('activity.loadError'))
    }
  }

  useEffect(() => { void load() }, [])

  function updateFilter(key: string, value: string) {
    const next = { ...filters, [key]: value }
    if (!value) delete next[key]
    setFilters(next)
    void load(next)
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{t('activity.title')}</h1>
          <p>{t('activity.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="filter-row">
        <input placeholder={t('activity.eventType')} value={filters.event_type || ''} onChange={(event) => updateFilter('event_type', event.target.value)} />
        <input placeholder={t('activity.source')} value={filters.source || ''} onChange={(event) => updateFilter('source', event.target.value)} />
        <input placeholder={t('activity.actor')} value={filters.actor || ''} onChange={(event) => updateFilter('actor', event.target.value)} />
        <input type="date" value={filters.date_from || ''} onChange={(event) => updateFilter('date_from', event.target.value)} />
        <input type="date" value={filters.date_to || ''} onChange={(event) => updateFilter('date_to', event.target.value)} />
      </section>
      <section className="timeline">
        {rows.map((row) => (
          <div className="timeline-row" key={row.id}>
            <strong>{row.event_type}</strong>
            <span>{new Date(row.created_at).toLocaleString()} · {row.actor} · {row.source}</span>
            <p>{row.message || row.document_title}</p>
            <div className="button-row">
              <button onClick={() => onOpenDocument(row.document_id)}>{t('common.document')}</button>
              {row.record_id && <button onClick={() => onOpenRecord(row.record_id!)}>{t('common.record')}</button>}
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}
