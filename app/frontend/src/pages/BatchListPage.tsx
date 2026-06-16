import { FormEvent, useEffect, useState } from 'react'
import { RefreshCw, Upload } from 'lucide-react'
import { api } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Batch } from '../types'
import { useI18n } from '../i18n'

const collections = ['Belege', 'Eingangsrechnung', 'Ausgangsrechnung']

export default function BatchListPage({ onOpenBatch }: { onOpenBatch: (id: string) => void }) {
  const { t } = useI18n()
  const [batches, setBatches] = useState<Batch[]>([])
  const [collection, setCollection] = useState(collections[0])
  const [label, setLabel] = useState('')
  const [files, setFiles] = useState<FileList | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      setBatches(await api.batches())
    } catch (err) {
      setError(err instanceof Error ? err.message : t('batches.loadError'))
    }
  }

  useEffect(() => { void load() }, [])

  async function upload(event: FormEvent) {
    event.preventDefault()
    if (!files?.length) return
    setBusy(true)
    setError('')
    const form = new FormData()
    form.set('collection_name', collection)
    if (label.trim()) form.set('label', label.trim())
    Array.from(files).forEach((file) => form.append('files', file))
    try {
      const created = await api.uploadBatch(form)
      setLabel('')
      setFiles(null)
      await load()
      onOpenBatch(created.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.uploadFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>{t('batches.title')}</h1>
          <p>{t('batches.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>

      <form className="upload-band" onSubmit={upload}>
        <select value={collection} onChange={(event) => setCollection(event.target.value)}>
          {collections.map((item) => <option key={item}>{item}</option>)}
        </select>
        <input placeholder={t('batches.labelPlaceholder')} value={label} onChange={(event) => setLabel(event.target.value)} />
        <input type="file" multiple onChange={(event) => setFiles(event.target.files)} />
        <button className="primary" disabled={busy || !files?.length}>
          <Upload size={18} /> {t('common.upload')}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('common.collection')}</th>
              <th>{t('common.label')}</th>
              <th>{t('common.documents')}</th>
              <th>{t('common.status')}</th>
              <th>{t('common.created')}</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => (
              <tr key={batch.id} onClick={() => onOpenBatch(batch.id)}>
                <td>{batch.collection_name}</td>
                <td>{batch.label ?? ''}</td>
                <td>{batch.document_count}</td>
                <td><StatusBadge value={batch.status} /></td>
                <td>{new Date(batch.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  )
}

