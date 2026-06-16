import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, thumbnailUrl } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { BatchDetail } from '../types'
import { useI18n } from '../i18n'

export default function BatchDetailPage({ id, onOpenDocument }: { id: string; onOpenDocument: (id: string) => void }) {
  const { t } = useI18n()
  const [batch, setBatch] = useState<BatchDetail | null>(null)
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setBatch(await api.batch(id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load batch')
    }
  }

  useEffect(() => { void load() }, [id])

  if (!batch) return <main>{error || 'Loading batch...'}</main>

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{batch.label || batch.collection_name}</h1>
          <p>{batch.document_count} documents · <StatusBadge value={batch.status} /></p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="document-grid">
        {batch.documents.map((document) => (
          <button className="doc-row" key={document.id} onClick={() => onOpenDocument(document.id)}>
            <div className="thumb-cell">
              {document.thumbnail_path ? <img src={thumbnailUrl(document.id)} alt="" /> : <span />}
            </div>
            <div>
              <strong>{document.manual_title_override || document.extracted_title || document.original_filename}</strong>
              <span>{document.original_filename}{document.duplicate_of_document_id ? ' · duplicate' : ''}</span>
            </div>
            <div>{document.collection_name}</div>
            <div>{document.page_count || 'NA'} pages</div>
            <div>{document.extracted_invoice_number || document.extracted_payment_method || 'NA'}</div>
            <div>{document.extracted_amount || 'NA'}</div>
            <StatusBadge value={document.processing_state} />
          </button>
        ))}
      </div>
    </main>
  )
}
