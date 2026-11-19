import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, ChevronDown, ChevronRight, RefreshCw, SlidersHorizontal } from 'lucide-react'
import { api } from '../api/client'
import type { ActivityItem } from '../types'
import { useI18n } from '../i18n'

const ACTIVITY_PAGE_LIMIT_OPTIONS = [50, 100, 200]
const BURST_WINDOW_MS = 3 * 60 * 1000

interface ActivityEntryGroup {
  key: string
  primary: ActivityItem
  steps: ActivityItem[]
  dayKey: string
  dayLabel: string
}

export default function ActivityPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const { t, language } = useI18n()
  const [rows, setRows] = useState<ActivityItem[]>([])
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [pageLimit, setPageLimit] = useState(100)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [totalEstimate, setTotalEstimate] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [groupedMode, setGroupedMode] = useState(true)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [error, setError] = useState('')

  const isDe = language === 'de'
  const locale = isDe ? 'de-DE' : 'en-US'

  async function load(next = filters, append = false, cursor: string | null = null, limit = pageLimit) {
    setError('')
    try {
      const params: Record<string, string> = { ...next, limit: String(limit) }
      if (cursor) params.cursor = cursor
      const page = await api.activityPage(params)
      setRows((current) => append ? [...current, ...page.items] : page.items)
      setNextCursor(page.next_cursor)
      setTotalEstimate(page.total_estimate)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('activity.loadError'))
      if (!append) {
        setRows([])
        setNextCursor(null)
        setTotalEstimate(0)
      }
    }
  }

  useEffect(() => { void load() }, [])

  function updateFilter(key: string, value: string) {
    const next = { ...filters, [key]: value }
    if (!value) delete next[key]
    setFilters(next)
    void load(next, false, null)
  }

  function applyQuickSource(source: '' | 'manual' | 'automatic') {
    const next = { ...filters }
    if (source) next.source = source
    else delete next.source
    setFilters(next)
    void load(next, false, null)
  }

  function clearFilters() {
    setFilters({})
    void load({}, false, null)
  }

  function updatePageLimit(value: number) {
    setPageLimit(value)
    void load(filters, false, null, value)
  }

  async function loadMoreActivity() {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      await load(filters, true, nextCursor)
    } finally {
      setLoadingMore(false)
    }
  }

  function toggleGroup(key: string) {
    setExpandedGroups((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const daySections = useMemo(() => {
    const entries: ActivityEntryGroup[] = []
    for (const row of rows) {
      const dt = new Date(row.created_at)
      const dayKey = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
      const dayLabel = dt.toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })

      const prev = entries[entries.length - 1]
      const canMerge =
        groupedMode &&
        prev &&
        prev.dayKey === dayKey &&
        prev.primary.document_id === row.document_id &&
        prev.primary.source === 'automatic' &&
        row.source === 'automatic' &&
        Math.abs(new Date(prev.primary.created_at).getTime() - dt.getTime()) <= BURST_WINDOW_MS

      if (canMerge) {
        prev.steps.push(row)
      } else {
        entries.push({
          key: row.id,
          primary: row,
          steps: [row],
          dayKey,
          dayLabel,
        })
      }
    }

    const byDay: Array<{ dayKey: string; dayLabel: string; items: ActivityEntryGroup[] }> = []
    for (const entry of entries) {
      const bucket = byDay[byDay.length - 1]
      if (bucket && bucket.dayKey === entry.dayKey) bucket.items.push(entry)
      else byDay.push({ dayKey: entry.dayKey, dayLabel: entry.dayLabel, items: [entry] })
    }
    return byDay
  }, [rows, groupedMode, locale])

  const activeAdvancedCount = ['event_type', 'actor', 'date_from', 'date_to'].filter((k) => Boolean(filters[k])).length
  const activeSource = filters.source || ''

  return (
    <main className="activity-console sheet-page">
      <header className="sheet-header">
        <div className="sheet-title-block">
          <h1>{t('activity.title')}</h1>
          <div className="sheet-summary-line">
            <span><strong>{(totalEstimate || rows.length).toLocaleString()}</strong> {t('nav.activity')}</span>
            <span aria-hidden="true">·</span>
            <span>{t('activity.subtitle')}</span>
          </div>
        </div>
        <div className="button-row">
          <div className="activity-view-toggle" role="group" aria-label={isDe ? 'Ansicht' : 'View'}>
            <button type="button" className={groupedMode ? 'active' : ''} onClick={() => setGroupedMode(true)}>
              {isDe ? 'Gruppiert' : 'Grouped'}
            </button>
            <button type="button" className={!groupedMode ? 'active' : ''} onClick={() => setGroupedMode(false)}>
              {isDe ? 'Alle Schritte' : 'All events'}
            </button>
          </div>
          <button type="button" className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={15} /></button>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <div className="activity-toolbar">
        <div className="activity-quick-pills" role="group" aria-label={t('activity.source')}>
          <button type="button" className={activeSource === '' ? 'active' : ''} onClick={() => applyQuickSource('')}>
            {isDe ? 'Alle' : 'All'}
          </button>
          <button type="button" className={activeSource === 'manual' ? 'active' : ''} onClick={() => applyQuickSource('manual')}>
            {translateActivitySource('manual', t)}
          </button>
          <button type="button" className={activeSource === 'automatic' ? 'active' : ''} onClick={() => applyQuickSource('automatic')}>
            {translateActivitySource('automatic', t)}
          </button>
        </div>

        <div className="activity-toolbar-right">
          {Object.keys(filters).length > 0 && (
            <button type="button" className="ghost-accent" onClick={clearFilters}>
              {isDe ? 'Filter zurücksetzen' : 'Clear filters'}
            </button>
          )}
          <button
            type="button"
            className={filtersOpen || activeAdvancedCount > 0 ? 'active-filter-btn' : ''}
            onClick={() => setFiltersOpen((v) => !v)}
          >
            <SlidersHorizontal size={14} />
            <span>{isDe ? 'Filter' : 'Filters'}{activeAdvancedCount > 0 ? ` (${activeAdvancedCount})` : ''}</span>
          </button>
        </div>
      </div>

      {filtersOpen && (
        <section className="activity-advanced-filters">
          <label>
            <span>{t('activity.eventType')}</span>
            <input placeholder="ocr_completed, manual_edit…" value={filters.event_type || ''} onChange={(event) => updateFilter('event_type', event.target.value)} />
          </label>
          <label>
            <span>{t('activity.actor')}</span>
            <input placeholder="Admin, System…" value={filters.actor || ''} onChange={(event) => updateFilter('actor', event.target.value)} />
          </label>
          <label>
            <span>{isDe ? 'Von' : 'From'}</span>
            <input type="date" value={filters.date_from || ''} onChange={(event) => updateFilter('date_from', event.target.value)} />
          </label>
          <label>
            <span>{isDe ? 'Bis' : 'To'}</span>
            <input type="date" value={filters.date_to || ''} onChange={(event) => updateFilter('date_to', event.target.value)} />
          </label>
        </section>
      )}

      <section className="activity-feed" aria-label={t('activity.title')}>
        {daySections.map((section) => (
          <div className="activity-day-group" key={section.dayKey}>
            <div className="activity-day-label">
              <span>{section.dayLabel}</span>
              <small>{section.items.length}</small>
            </div>

            <div className="activity-day-list">
              {section.items.map((entry) => {
                const { primary, steps } = entry
                const hasBurst = steps.length > 1
                const isExpanded = expandedGroups.has(entry.key)
                const tone = toneForEvent(primary.event_type, primary.source)
                const docLabel = primary.document_title || primary.original_filename || t('common.document')
                const timeText = new Date(primary.created_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

                return (
                  <article className={`activity-entry ${isExpanded ? 'is-expanded' : ''}`} key={entry.key}>
                    <div className="activity-entry-main">
                      <span className={`activity-dot tone-${tone}`} aria-hidden="true" />
                      <time className="activity-time" dateTime={primary.created_at}>{timeText}</time>

                      <div className="activity-entry-body">
                        <div className="activity-entry-headline">
                          <strong>{translateActivityEvent(primary.event_type, t, isDe)}</strong>
                          <button
                            type="button"
                            className="activity-doc-link"
                            onClick={() => onOpenDocument(primary.document_id)}
                            title={primary.original_filename || docLabel}
                          >
                            <span>{docLabel}</span>
                            <ArrowUpRight size={13} />
                          </button>
                        </div>
                        {primary.message && primary.message !== docLabel && (
                          <p className="activity-entry-msg">{translateActivityMessage(primary.message, t, isDe)}</p>
                        )}
                      </div>

                      <div className="activity-entry-meta">
                        {hasBurst && (
                          <button
                            type="button"
                            className="activity-burst-toggle"
                            aria-expanded={isExpanded}
                            onClick={() => toggleGroup(entry.key)}
                          >
                            {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                            <span>{steps.length} {isDe ? 'Schritte' : 'steps'}</span>
                          </button>
                        )}
                        <span className={`activity-source-tag source-${primary.source === 'manual' ? 'manual' : 'auto'}`}>
                          {translateActivityActor(primary.actor, t)} · {translateActivitySource(primary.source, t)}
                        </span>
                      </div>
                    </div>

                    {hasBurst && isExpanded && (
                      <ol className="activity-substeps">
                        {steps.map((step) => (
                          <li key={step.id}>
                            <time>{new Date(step.created_at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>
                            <strong>{translateActivityEvent(step.event_type, t, isDe)}</strong>
                            <span>{translateActivityMessage(step.message || '', t, isDe)}</span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </article>
                )
              })}
            </div>
          </div>
        ))}

        {!rows.length && !error && (
          <p className="tab-empty activity-empty">{t('activity.noEvents', 'No activity events match the current filters.')}</p>
        )}
      </section>

      <div className="pagination-footer">
        <span>{t('common.showing', 'Showing')} {rows.length} / {totalEstimate || rows.length} {t('nav.activity').toLowerCase()}</span>
        <label className="list-limit-control">{t('common.rowsPerPage', 'Rows per page')}
          <select value={pageLimit} onChange={(event) => updatePageLimit(Number(event.target.value) || 100)}>
            {ACTIVITY_PAGE_LIMIT_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        {nextCursor && <button type="button" className="primary" disabled={loadingMore} onClick={() => void loadMoreActivity()}>{t('common.loadMore', 'Load more')}</button>}
      </div>
    </main>
  )
}

function toneForEvent(eventType: string, source: string): 'ok' | 'manual' | 'warn' | 'err' | 'info' {
  const lower = eventType.toLowerCase()
  if (lower.includes('fail') || lower.includes('error') || lower.includes('delete')) return 'err'
  if (lower.includes('review')) return 'warn'
  if (source === 'manual' || lower.includes('manual')) return 'manual'
  if (lower.includes('complete') || lower.includes('finish') || lower.includes('restore')) return 'ok'
  return 'info'
}

function translateActivityEvent(value: string, t: (key: string, fallback?: string) => string, isDe: boolean) {
  const extra = isDe ? EXTRA_EVENT_DE[value] : EXTRA_EVENT_EN[value]
  return t(`activity.event.${value}`, extra || value.replace(/_/g, ' '))
}

function translateActivityActor(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.actor.${value}`, value)
}

function translateActivitySource(value: string, t: (key: string, fallback?: string) => string) {
  return t(`activity.source.${value}`, value)
}

function translateActivityMessage(value: string, t: (key: string, fallback?: string) => string, isDe: boolean) {
  const key = ACTIVITY_MESSAGE_KEYS[value]
  if (key) return t(key, value)
  if (isDe && EXTRA_MESSAGE_DE[value]) return EXTRA_MESSAGE_DE[value]
  return value
}

const EXTRA_EVENT_DE: Record<string, string> = {
  manual_edit: 'Manuelle Bearbeitung',
  process_finished: 'Verarbeitung abgeschlossen',
  process_queued: 'In Warteschlange',
  qwen_metadata_brain_single_pass: 'Metadaten-Extraktion',
  financial_review_required: 'Finanzprüfung erforderlich',
}

const EXTRA_EVENT_EN: Record<string, string> = {
  manual_edit: 'Manual edit',
  process_finished: 'Processing finished',
  process_queued: 'Processing queued',
  qwen_metadata_brain_single_pass: 'Metadata extraction',
  financial_review_required: 'Financial review required',
}

const EXTRA_MESSAGE_DE: Record<string, string> = {
  'Manual document metadata edit': 'Dokument-Metadaten manuell bearbeitet',
  'Full document processing finished': 'Vollständige Dokumentverarbeitung abgeschlossen',
  'Full document processing queued from existing OCR': 'Verarbeitung mit vorhandener OCR eingereiht',
  'Financial values require scan verification': 'Finanzbeträge müssen anhand des Scans geprüft werden',
  'Mapped correspondent, document type, tag, and storage path metadata': 'Korrespondent, Dokumenttyp, Tags und Speicherpfad zugeordnet',
  'Qwen metadata, search, tag, and folder candidates were handled in the metadata stage': 'Metadaten-, Such-, Tag- und Ordnervorschläge verarbeitet',
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
