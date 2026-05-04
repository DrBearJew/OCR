import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Database, FileText, Plus, RefreshCw, Search, Settings2, SlidersHorizontal } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { api } from '../api/client'
import type { CollectionSummary } from '../types'

interface CollectionsPageProps {
  onOpenCollection: (slug: string) => void
  onSchemas: () => void
}

export default function CollectionsPage({ onOpenCollection, onSchemas }: CollectionsPageProps) {
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newCollection, setNewCollection] = useState({ name: '', slug: '', icon: '', color: '#22c55e' })
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      const rows = await api.collectionSummaries()
      setCollections(rows.length ? rows : demoCollections)
    } catch {
      setError('Backend API is unavailable; showing sample collection layout data.')
      setCollections(demoCollections)
    }
  }

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return collections
    return collections.filter(({ collection }) =>
      collection.name.toLowerCase().includes(needle) || collection.slug.toLowerCase().includes(needle)
    )
  }, [collections, query])

  const totals = useMemo(() => ({
    collections: collections.length,
    records: collections.reduce((sum, item) => sum + item.record_count, 0),
    documents: collections.reduce((sum, item) => sum + item.document_count, 0),
    needsReview: collections.reduce((sum, item) => sum + (item.status_counts.needs_review || 0), 0)
  }), [collections])

  async function createCollection(event: FormEvent) {
    event.preventDefault()
    if (!newCollection.name.trim()) return
    setError('')
    try {
      const created = await api.createCollection({
        name: newCollection.name.trim(),
        slug: newCollection.slug.trim() || undefined,
        icon: newCollection.icon.trim() || undefined,
        color: newCollection.color.trim() || undefined
      })
      setNewCollection({ name: '', slug: '', icon: '', color: '#22c55e' })
      setCreateOpen(false)
      await load()
      onOpenCollection(created.slug)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create collection')
    }
  }

  return (
    <main className="collections-console">
      <header className="page-header console-header">
        <div>
          <h1>Collections</h1>
          <p>PocketBase-style schema buckets with document-true records, fields, and OCR workflows.</p>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={17} /> Create collection</button>
          <button onClick={onSchemas}><Settings2 size={17} /> Manage Schemas</button>
          <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="warning">{error}</p>}
      {createOpen && (
        <form className="workflow-card create-collection-form" onSubmit={createCollection}>
          <label>Name<input value={newCollection.name} onChange={(event) => setNewCollection({ ...newCollection, name: event.target.value })} placeholder="Steuer" autoFocus /></label>
          <label>Slug<input value={newCollection.slug} onChange={(event) => setNewCollection({ ...newCollection, slug: event.target.value })} placeholder="auto-generated if empty" /></label>
          <label>Icon<input value={newCollection.icon} onChange={(event) => setNewCollection({ ...newCollection, icon: event.target.value })} placeholder="ST" maxLength={4} /></label>
          <label>Color<input type="color" value={newCollection.color} onChange={(event) => setNewCollection({ ...newCollection, color: event.target.value })} /></label>
          <button className="primary"><Plus size={17} /> Save collection</button>
          <button type="button" onClick={() => setCreateOpen(false)}>Cancel</button>
        </form>
      )}

      <section className="collections-summary-grid">
        <SummaryCard icon={<Database size={23} />} label="Collections" value={totals.collections} detail="schema buckets" />
        <SummaryCard icon={<SlidersHorizontal size={23} />} label="Records" value={totals.records} detail="browseable rows" />
        <SummaryCard icon={<FileText size={23} />} label="Documents" value={totals.documents} detail="OCR units" />
        <SummaryCard icon={<Settings2 size={23} />} label="Needs Review" value={totals.needsReview} detail="across schemas" tone="orange" />
      </section>

      <section className="workflow-card collection-browser">
        <div className="document-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder="Search collections, slugs, document types..." value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <button onClick={onSchemas}><Settings2 size={17} /> Schema Editor</button>
          <button onClick={() => setCreateOpen(true)}><Plus size={17} /> New collection</button>
          <button className="primary" onClick={() => onOpenCollection('eingangsrechnung')}>Open invoices</button>
        </div>

        <div className="collection-card-grid">
          {filtered.map((item) => (
            <article className="collection-admin-card" key={item.collection.id}>
              <div className="collection-card-head">
                <span className="collection-icon" style={{ '--collection-color': item.collection.color || '#22c55e' } as CSSProperties}>
                  {item.collection.icon || item.collection.name.slice(0, 2).toUpperCase()}
                </span>
                <div>
                  <h2>{item.collection.name}</h2>
                  <p>{item.collection.slug}</p>
                </div>
              </div>

              <div className="collection-meter-row">
                <span><strong>{item.record_count}</strong> Records</span>
                <span><strong>{item.document_count}</strong> Documents</span>
                <span><strong>{item.status_counts.complete || 0}</strong> Complete</span>
              </div>

              <StatusPills counts={item.status_counts} />

              <div className="collection-schema-strip">
                <span className="schema-field-pill">title rule</span>
                <span className="schema-field-pill">custom fields</span>
                <span className="schema-field-pill">OCR config</span>
                <span className="schema-field-pill">search defaults</span>
              </div>

              <div className="collection-mini-docs" aria-label={`${item.collection.name} recent documents`}>
                <MiniDocument label="PDF" status="complete" />
                <MiniDocument label="OCR" status={item.status_counts.processing ? 'processing' : 'complete'} />
                <MiniDocument label="META" status={item.status_counts.needs_review ? 'review' : 'complete'} />
                <span className="add-mini-doc">+</span>
              </div>

              <div className="collection-actions">
                <button onClick={onSchemas}>Schema</button>
                <button onClick={() => onOpenCollection(item.collection.slug)}>Records</button>
                <button className="primary" onClick={() => onOpenCollection(item.collection.slug)}>Open</button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  )
}

function SummaryCard({ icon, label, value, detail, tone = 'green' }: { icon: ReactNode; label: string; value: number; detail: string; tone?: string }) {
  return (
    <div className={`collection-summary-card collection-summary-${tone}`}>
      <span>{icon}</span>
      <div>
        <strong>{value.toLocaleString()}</strong>
        <small>{label}</small>
        <em>{detail}</em>
      </div>
    </div>
  )
}

function StatusPills({ counts }: { counts: Record<string, number> }) {
  const entries = [
    ['complete', 'Complete'],
    ['processing', 'Processing'],
    ['needs_review', 'Needs review'],
    ['partially_failed', 'Partial fail']
  ].filter(([key]) => counts[key])
  if (!entries.length) entries.push(['pending', 'Pending'])
  return (
    <div className="status-pill-row">
      {entries.map(([key, label]) => <span className={`status-pill status-pill-${key}`} key={key}>{label}: {counts[key] || 0}</span>)}
    </div>
  )
}

function MiniDocument({ label, status }: { label: string; status: 'complete' | 'processing' | 'review' }) {
  return (
    <span className={`mini-document mini-document-${status}`}>
      <FileText size={18} />
      <small>{label}</small>
      <i />
    </span>
  )
}

const demoCollections: CollectionSummary[] = [
  {
    collection: { id: 'demo-belege', name: 'Belege', slug: 'belege', icon: 'BL', color: '#38bdf8' },
    record_count: 42,
    document_count: 67,
    status_counts: { complete: 51, processing: 7, needs_review: 6, partially_failed: 3 }
  },
  {
    collection: { id: 'demo-eingang', name: 'Eingangsrechnung', slug: 'eingangsrechnung', icon: 'ER', color: '#22c55e' },
    record_count: 86,
    document_count: 124,
    status_counts: { complete: 109, processing: 8, needs_review: 5, partially_failed: 2 }
  },
  {
    collection: { id: 'demo-ausgang', name: 'Ausgangsrechnung', slug: 'ausgangsrechnung', icon: 'AR', color: '#a78bfa' },
    record_count: 31,
    document_count: 39,
    status_counts: { complete: 35, needs_review: 2, processing: 1, partially_failed: 1 }
  },
  {
    collection: { id: 'demo-dok', name: 'Dokumente', slug: 'dokumente', icon: 'DK', color: '#f59e0b' },
    record_count: 18,
    document_count: 22,
    status_counts: { complete: 16, processing: 4, needs_review: 2 }
  }
]
