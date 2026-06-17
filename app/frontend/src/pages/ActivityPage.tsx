import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { ActivityItem } from '../types'
import { useI18n } from '../i18n'

export default function ActivityPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
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
            <strong>{translateActivityEvent(row.event_type, t)}</strong>
            <span>{new Date(row.created_at).toLocaleString(language === 'de' ? 'de-DE' : undefined)} · {translateActivityActor(row.actor, t)} · {translateActivitySource(row.source, t)}</span>
            <p>{translateActivityMessage(row.message || row.document_title || '', t)}</p>
            <div className="button-row">
              <button onClick={() => onOpenDocument(row.document_id)}>{t('common.document')}</button>
            </div>
          </div>
        ))}
      </section>
    </main>
  )
}


function translateActivityEvent(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.event.${value}`, value.replace(/_/g, ' '))
}

function translateActivityActor(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.actor.${value}`, value)
}

function translateActivitySource(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.source.${value}`, value)
}

function translateActivityMessage(value: string, t: (key: string, fallback?: string) => string) {
  const key = ACTIVITY_MESSAGE_KEYS[value]
  return key ? t(key, value) : value
}

const ACTIVITY_MESSAGE_KEYS: Record<string, string> = {
  'Deterministic extraction completed': 'activity.message.deterministicDone',
  'Document complete after OCR, metadata, title, and DB update': 'activity.message.documentComplete',
  'Final title and metadata generated': 'activity.message.titleGenerated',
  'Full OCR and metadata are searchable in the app database': 'activity.message.searchIndexed',
  'Mapped correspondent, document type, and storage path metadata': 'activity.message.paperlessMapped',
  'OCR completed': 'activity.message.ocrCompleted',
  'OCR started': 'activity.message.ocrStarted',
  'Metadata extraction started': 'activity.message.metadataStarted',
  'Document queued for OCR': 'activity.message.queuedForOcr',
  'Document uploaded': 'activity.message.uploaded',
  'Original file stored on local filesystem': 'activity.message.stored',
  'Qwen metadata brain started': 'activity.message.qwenStarted',
  'Qwen metadata candidates generated': 'activity.message.qwenCandidates',
  'Qwen metadata, search, tag, and folder candidates generated': 'activity.message.qwenDone',
  'Qwen metadata brain disabled by processing options': 'activity.message.qwenSkipped',
  'Document metadata saved but requires review': 'activity.message.needsReview',
  'Full document processing started': 'activity.message.processStarted',
  'Existing OCR reused for full processing': 'activity.message.ocrReused',
  'Existing metadata reused for full processing': 'activity.message.metadataReused',
  'Document soft-deleted': 'activity.message.documentDeleted',
  'Document restored': 'activity.message.documentRestored',
  'Review state updated': 'activity.message.reviewUpdated',
  'OCR pipeline settings updated': 'activity.message.ocrSettingsUpdated',
  'Manual metadata re-extract requested': 'activity.message.manualReextract',
  'Search index marker refreshed': 'activity.message.searchRefreshed'
}
