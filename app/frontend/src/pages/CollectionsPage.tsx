import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Plus, RefreshCw, Search, Settings2 } from 'lucide-react'
import type { CSSProperties } from 'react'
import { api } from '../api/client'
import type { CollectionSummary } from '../types'
import { useI18n } from '../i18n'

interface CollectionsPageProps {
  onOpenCollection: (slug: string) => void
  onSchemas: () => void
}

const curatedCollectionColors: Record<string, string> = {
  eingangsrechnung: '#145946',
  ausgangsrechnung: '#2563eb',
  belege: '#b45309',
  dokumente: '#6d28d9',
}

function resolveCollectionColor(slug: string, rawColor?: string | null): string {
  const key = slug.trim().toLowerCase()
  const normalized = (rawColor || '').trim().toLowerCase()
  if (!normalized || normalized === '#22c55e' || normalized === '#145946') {
    return curatedCollectionColors[key] || normalized || '#145946'
  }
  return rawColor!.trim()
}

export default function CollectionsPage({ onOpenCollection, onSchemas }: CollectionsPageProps) {
  const { t } = useI18n()
  const [collections, setCollections] = useState<CollectionSummary[]>([])
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newCollection, setNewCollection] = useState({ name: '', slug: '', icon: '', color: '#145946' })
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
      setNewCollection({ name: '', slug: '', icon: '', color: '#145946' })
      setCreateOpen(false)
      await load()
      onOpenCollection(created.slug)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('collections.createError'))
    }
  }

  return (
    <main className="collections-console sheet-page">
      <header className="sheet-header">
        <div className="sheet-title-block">
          <h1>{t('collections.title')}</h1>
          <div className="sheet-summary-line">
            <span><strong>{totals.collections.toLocaleString()}</strong> {t('nav.collections')}</span>
            <span aria-hidden="true">·</span>
            <span><strong>{totals.documents.toLocaleString()}</strong> {t('nav.documents')}</span>
            {totals.needsReview > 0 && (
              <>
                <span aria-hidden="true">·</span>
                <span className="tone-orange"><strong>{totals.needsReview.toLocaleString()}</strong> {t('common.needsReview')}</span>
              </>
            )}
          </div>
        </div>
        <div className="button-row">
          <button type="button" onClick={onSchemas}><Settings2 size={15} /> {t('collections.manageSchemas')}</button>
          <button type="button" className="primary" onClick={() => setCreateOpen((value) => !value)}><Plus size={15} /> {t('collections.create')}</button>
          <button type="button" className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={15} /></button>
        </div>
      </header>

      {error && <p className="warning">{error}</p>}

      {createOpen && (
        <form className="sheet-inline-form create-collection-form" onSubmit={createCollection}>
          <label>Name<input value={newCollection.name} onChange={(event) => setNewCollection({ ...newCollection, name: event.target.value })} placeholder="Steuer" autoFocus /></label>
          <label>Slug<input value={newCollection.slug} onChange={(event) => setNewCollection({ ...newCollection, slug: event.target.value })} placeholder={t('collections.autoSlug')} /></label>
          <label>Icon<input value={newCollection.icon} onChange={(event) => setNewCollection({ ...newCollection, icon: event.target.value })} placeholder="ST" maxLength={4} /></label>
          <label>Color<input type="color" value={newCollection.color} onChange={(event) => setNewCollection({ ...newCollection, color: event.target.value })} /></label>
          <button className="primary"><Plus size={15} /> Save collection</button>
          <button type="button" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</button>
        </form>
      )}

      <div className="sheet-filter-strip">
        <label className="toolbar-search">
          <Search size={15} />
          <input placeholder={t('collections.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>

      <section className="collection-binder-grid" aria-label={t('collections.title')}>
        {filtered.map((item) => {
          const accent = resolveCollectionColor(item.collection.slug, item.collection.color)
          const complete = item.status_counts.complete || 0
          const needsReview = item.status_counts.needs_review || 0
          const processing = item.status_counts.processing || 0
          const failed = item.status_counts.partially_failed || 0
          const pct = item.document_count > 0 ? Math.round((complete / item.document_count) * 100) : 0
          return (
            <article
              className="collection-binder-card"
              key={item.collection.id}
              style={{ '--binder-color': accent } as CSSProperties}
              onClick={() => onOpenCollection(item.collection.slug)}
            >
              <div className="binder-top">
                <span className="binder-monogram">
                  {item.collection.icon || item.collection.name.slice(0, 2).toUpperCase()}
                </span>
                <div className="binder-title-wrap">
                  <h2>{item.collection.name}</h2>
                  {item.collection.slug.toLowerCase() !== item.collection.name.toLowerCase() && (
                    <small>{item.collection.slug}</small>
                  )}
                </div>
                <span className="binder-arrow" aria-hidden="true"><ArrowUpRight size={17} /></span>
              </div>

              <div className="binder-metric-block">
                <div className="binder-count">
                  <strong>{item.document_count.toLocaleString()}</strong>
                  <span>{t('common.documents')}</span>
                </div>
                <div className="binder-progress-track" aria-hidden="true">
                  <span style={{ width: `${pct}%` }} />
                </div>
              </div>

              <div className="binder-status-row">
                {complete > 0 && <span className="badge badge-complete">{complete} {t('common.complete')}</span>}
                {needsReview > 0 && <span className="badge badge-needs-review">{needsReview} {t('common.needsReview')}</span>}
                {processing > 0 && <span className="badge badge-processing">{processing} {t('common.processing')}</span>}
                {failed > 0 && <span className="badge badge-failed">{failed} {t('common.failed')}</span>}
                {item.document_count === 0 && <span className="binder-empty-hint">{t('common.empty', 'Empty collection')}</span>}
              </div>

              <div className="binder-footer" onClick={(event) => event.stopPropagation()}>
                <button type="button" onClick={onSchemas}>{t('common.schema')}</button>
                <button type="button" className="binder-open-btn" onClick={() => onOpenCollection(item.collection.slug)}>
                  {t('common.open')} <ArrowUpRight size={14} />
                </button>
              </div>
            </article>
          )
        })}
      </section>
    </main>
  )
}

const demoCollections: CollectionSummary[] = [
  {
    collection: { id: 'demo-belege', name: 'Belege', slug: 'belege', icon: 'BL', color: '#b45309' },
    record_count: 42,
    document_count: 67,
    status_counts: { complete: 51, processing: 7, needs_review: 6, partially_failed: 3 }
  },
  {
    collection: { id: 'demo-eingang', name: 'Eingangsrechnung', slug: 'eingangsrechnung', icon: 'ER', color: '#145946' },
    record_count: 86,
    document_count: 124,
    status_counts: { complete: 109, processing: 8, needs_review: 5, partially_failed: 2 }
  },
  {
    collection: { id: 'demo-ausgang', name: 'Ausgangsrechnung', slug: 'ausgangsrechnung', icon: 'AR', color: '#2563eb' },
    record_count: 31,
    document_count: 39,
    status_counts: { complete: 35, needs_review: 2, processing: 1, partially_failed: 1 }
  },
  {
    collection: { id: 'demo-dok', name: 'Dokumente', slug: 'dokumente', icon: 'DK', color: '#6d28d9' },
    record_count: 18,
    document_count: 22,
    status_counts: { complete: 16, processing: 4, needs_review: 2 }
  }
]
