import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { ActivityItem } from '../types'

export default function ActivityPage({ onOpenDocument, onOpenRecord }: { onOpenDocument: (id: string) => void; onOpenRecord: (id: string) => void }) {
  const [rows, setRows] = useState<ActivityItem[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [error, setError] = useState('')

  async function load(next = filters) {
    setError('')
    try {
      setRows(await api.activity(next))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load activity')
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
          <h1>Audit / Activity</h1>
          <p>Manual edits, automatic processing steps, reprocessing events, and state changes.</p>
        </div>
        <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="filter-row">
        <input placeholder="Event type" value={filters.event_type || ''} onChange={(event) => updateFilter('event_type', event.target.value)} />
        <input placeholder="Source" value={filters.source || ''} onChange={(event) => updateFilter('source', event.target.value)} />
        <input placeholder="Actor" value={filters.actor || ''} onChange={(event) => updateFilter('actor', event.target.value)} />
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
              <button onClick={() => onOpenDocument(row.document_id)}>Document</button>
              {row.record_id && <button onClick={() => onOpenRecord(row.record_id!)}>Record</button>}
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}
