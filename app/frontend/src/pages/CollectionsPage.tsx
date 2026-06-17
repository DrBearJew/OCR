import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Database, FileText, Plus, RefreshCw, Search, Settings2 } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { api } from '../api/client'
import type { CollectionSummary } from '../types'
import { useI18n } from '../i18n'

interface CollectionsPageProps {
  onOpenCollection: (slug: string) => void
  onSchemas: () => void
}

export default function CollectionsPage({ onOpenCollection, onSchemas }: CollectionsPageProps) {
  const { t } = useI18n()
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
      setError(t('collections.demoWarning'))
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
      setError(err instanceof Error ? err.message : t('collections.createError'))
    }
  }

  return (
    <main className="collections-console">
      <header className="page-header console-header">
        <div>
          <h1>{t('collections.title')}</h1>
          <p>{t('collections.subtitle')}</p>
        </div>
        <div className="button-row">
          <button className="primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={17} /> {t('collections.create')}</button>
          <button onClick={onSchemas}><Settings2 size={17} /> {t('collections.manageSchemas')}</button>
          <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
        </div>
      </header>
      {error && <p className="warning">{error}</p>}
      {createOpen && (
        <form className="workflow-card create-collection-form" onSubmit={createCollection}>
          <label>Name<input value={newCollection.name} onChange={(event) => setNewCollection({ ...newCollection, name: event.target.value })} placeholder="Steuer" autoFocus /></label>
          <label>Slug<input value={newCollection.slug} onChange={(event) => setNewCollection({ ...newCollection, slug: event.target.value })} placeholder={t('collections.autoSlug')} /></label>
          <label>Icon<input value={newCollection.icon} onChange={(event) => setNewCollection({ ...newCollection, icon: event.target.value })} placeholder="ST" maxLength={4} /></label>
          <label>Color<input type="color" value={newCollection.color} onChange={(event) => setNewCollection({ ...newCollection, color: event.target.value })} /></label>
          <button className="primary"><Plus size={17} /> Save collection</button>
          <button type="button" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</button>
        </form>
      )}

      <section className="collections-summary-grid">
        <SummaryCard icon={<Database size={23} />} label={t('nav.collections')} value={totals.collections} detail={t('collections.schemaBuckets')} />
        <SummaryCard icon={<FileText size={23} />} label={t('nav.documents')} value={totals.documents} detail={t('collections.ocrUnits')} />
        <SummaryCard icon={<Settings2 size={23} />} label={t('common.needsReview')} value={totals.needsReview} detail={t('collections.acrossSchemas')} tone="orange" />
      </section>

      <section className="workflow-card collection-browser">
        <div className="document-toolbar">
          <label className="toolbar-search">
            <Search size={17} />
            <input placeholder={t('collections.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <button onClick={onSchemas}><Settings2 size={17} /> {t('collections.schemaEditor')}</button>
          <button onClick={() => setCreateOpen(true)}><Plus size={17} /> {t('collections.new')}</button>
          <button className="primary" onClick={() => onOpenCollection('eingangsrechnung')}>{t('collections.openInvoices')}</button>
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
                <span><strong>{item.document_count}</strong> {t('common.documents')}</span>
                <span><strong>{item.status_counts.complete || 0}</strong> {t('common.complete')}</span>
              </div>

              <StatusPills counts={item.status_counts} />

              <div className="collection-schema-strip">
                <span className="schema-field-pill">{t('collections.titleRule')}</span>
                <span className="schema-field-pill">{t('collections.customFields')}</span>
                <span className="schema-field-pill">{t('collections.ocrConfig')}</span>
                <span className="schema-field-pill">{t('collections.searchDefaults')}</span>
              </div>

              <div className="collection-mini-docs" aria-label={`${item.collection.name} recent documents`}>
                <MiniDocument label="PDF" status="complete" />
                <MiniDocument label="OCR" status={item.status_counts.processing ? 'processing' : 'complete'} />
                <MiniDocument label="META" status={item.status_counts.needs_review ? 'review' : 'complete'} />
                <span className="add-mini-doc">+</span>
              </div>

              <div className="collection-actions">
                <button onClick={onSchemas}>{t('common.schema')}</button>
                <button className="primary" onClick={() => onOpenCollection(item.collection.slug)}>{t('common.open')}</button>
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
  const { t } = useI18n()
  const entries = [
    ['complete', t('status.complete')],
    ['processing', t('status.processing')],
    ['needs_review', t('status.needs_review')],
    ['partially_failed', t('status.partially_failed')]
  ].filter(([key]) => counts[key])
  if (!entries.length) entries.push(['pending', t('status.pending')])
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
