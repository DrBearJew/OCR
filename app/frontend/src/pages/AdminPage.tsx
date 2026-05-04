import { useEffect, useState } from 'react'
import { RefreshCw, RotateCcw, Wrench } from 'lucide-react'
import { api } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { Collection, Document, IngestionJob, IngestionSource, IntegrationSummary, JobInfo, ProcessingHook } from '../types'

export default function AdminPage({ onOpenDocument }: { onOpenDocument: (id: string) => void }) {
  const [jobs, setJobs] = useState<JobInfo[]>([])
  const [failed, setFailed] = useState<JobInfo[]>([])
  const [duplicates, setDuplicates] = useState<Document[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [sources, setSources] = useState<IngestionSource[]>([])
  const [ingestionJobs, setIngestionJobs] = useState<IngestionJob[]>([])
  const [hooks, setHooks] = useState<ProcessingHook[]>([])
  const [integrations, setIntegrations] = useState<IntegrationSummary | null>(null)
  const [collection, setCollection] = useState('Belege')
  const [sourceForm, setSourceForm] = useState({ name: '', path: '', collection_id: '', recursive: false })
  const [hookForm, setHookForm] = useState({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      const [recentJobs, failedDocs, duplicateDocs, integrationStatus, collectionRows, sourceRows, ingestionRows, hookRows] = await Promise.all([
        api.jobs(),
        api.failed(),
        api.duplicates(),
        api.integrations(),
        api.collections(),
        api.ingestionSources(),
        api.ingestionJobs(),
        api.hooks()
      ])
      setJobs(recentJobs)
      setFailed(failedDocs)
      setDuplicates(duplicateDocs)
      setIntegrations(integrationStatus)
      setCollections(collectionRows)
      setSources(sourceRows)
      setIngestionJobs(ingestionRows)
      setHooks(hookRows)
      if (!sourceForm.collection_id && collectionRows[0]) setSourceForm((form) => ({ ...form, collection_id: collectionRows[0].id }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load admin data')
    }
  }

  async function retry(id: string) {
    await api.retryDocument(id)
    await load()
  }

  async function runAction(action: () => Promise<unknown>) {
    await action()
    await load()
  }

  async function addSource() {
    await api.createIngestionSource({
      name: sourceForm.name,
      source_type: 'consume_folder',
      path: sourceForm.path,
      enabled: true,
      collection_id: sourceForm.collection_id || collections[0]?.id,
      record_grouping: 'one_record_per_file',
      polling_interval_seconds: 300,
      ignore_patterns: ['.*', '*.tmp'],
      recursive: sourceForm.recursive,
      ocr_config_json: { ocr_mode: 'redo', language: 'deu+eng' }
    })
    setSourceForm({ name: '', path: '', collection_id: collections[0]?.id || '', recursive: false })
    await load()
  }

  async function addHook() {
    await api.createHook({
      name: hookForm.name,
      stage: hookForm.stage as 'pre_consume' | 'post_consume',
      hook_kind: hookForm.hook_kind as 'command' | 'webhook',
      enabled: true,
      blocking: hookForm.blocking,
      command: hookForm.command || null,
      webhook_url: hookForm.webhook_url || null,
      timeout_seconds: 30,
      env_json: {}
    })
    setHookForm({ name: '', stage: 'pre_consume', hook_kind: 'command', command: '', webhook_url: '', blocking: true })
    await load()
  }

  useEffect(() => { void load() }, [])

  return (
    <main className="admin-page">
      <header className="page-header">
        <div>
          <h1>Admin</h1>
          <p>Recent jobs and failed documents.</p>
        </div>
        <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="admin-actions">
        <button onClick={() => void runAction(api.reconcile)}><Wrench size={18} /> Reconcile stuck docs</button>
        <button onClick={() => void runAction(api.retryFailed)}><RotateCcw size={18} /> Retry failed docs</button>
        <select value={collection} onChange={(event) => setCollection(event.target.value)}>
          <option>Belege</option>
          <option>Eingangsrechnung</option>
          <option>Ausgangsrechnung</option>
        </select>
        <button onClick={() => void runAction(() => api.reextractCollection(collection, false))}>Reextract collection</button>
      </div>
      <h2>Integrations</h2>
      <div className="admin-list">
        {integrations?.integrations.map((item) => (
          <div key={item.name} className="admin-row">
            <strong>{item.name}</strong>
            <StatusBadge value={item.ok ? 'complete' : 'failed'} />
            <span>{item.detail}</span>
            <span>{item.latency_ms ?? ''}{item.latency_ms !== null ? ' ms' : ''}</span>
          </div>
        ))}
      </div>
      <h2>Ingestion</h2>
      <div className="admin-actions">
        <input placeholder="Source name" value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} />
        <input placeholder="Consume folder path" value={sourceForm.path} onChange={(event) => setSourceForm({ ...sourceForm, path: event.target.value })} />
        <select value={sourceForm.collection_id} onChange={(event) => setSourceForm({ ...sourceForm, collection_id: event.target.value })}>
          {collections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={sourceForm.recursive} onChange={(event) => setSourceForm({ ...sourceForm, recursive: event.target.checked })} /> Recursive</label>
        <button onClick={() => void addSource()}>Add source</button>
        <button onClick={() => void runAction(api.scanAllIngestionSources)}>Scan all</button>
      </div>
      <div className="admin-list">
        {sources.map((source) => (
          <div key={source.id} className="admin-row">
            <strong>{source.name}</strong>
            <StatusBadge value={source.enabled ? 'complete' : 'failed'} />
            <span>{source.path} · {source.record_grouping}</span>
            <button onClick={() => void runAction(() => api.scanIngestionSource(source.id))}>Scan</button>
          </div>
        ))}
      </div>
      <h2>Ingestion Jobs</h2>
      <div className="admin-list">
        {ingestionJobs.slice(0, 20).map((job) => (
          <div key={job.id} className="admin-row">
            <button disabled={!job.document_id} onClick={() => job.document_id && onOpenDocument(job.document_id)}>{job.discovered_path}</button>
            <StatusBadge value={job.status === 'imported' || job.status === 'skipped' ? 'complete' : job.status === 'failed' ? 'failed' : 'processing'} />
            <span>{job.error_message || job.sha256 || ''}</span>
            <button onClick={() => void runAction(() => api.retryIngestionJob(job.id))}>Retry</button>
          </div>
        ))}
      </div>
      <h2>Hooks</h2>
      <div className="admin-actions">
        <input placeholder="Hook name" value={hookForm.name} onChange={(event) => setHookForm({ ...hookForm, name: event.target.value })} />
        <select value={hookForm.stage} onChange={(event) => setHookForm({ ...hookForm, stage: event.target.value })}>
          <option value="pre_consume">pre_consume</option>
          <option value="post_consume">post_consume</option>
        </select>
        <select value={hookForm.hook_kind} onChange={(event) => setHookForm({ ...hookForm, hook_kind: event.target.value })}>
          <option value="command">command</option>
          <option value="webhook">webhook</option>
        </select>
        <input placeholder="Command" value={hookForm.command} onChange={(event) => setHookForm({ ...hookForm, command: event.target.value })} />
        <input placeholder="Webhook URL" value={hookForm.webhook_url} onChange={(event) => setHookForm({ ...hookForm, webhook_url: event.target.value })} />
        <label className="check"><input type="checkbox" checked={hookForm.blocking} onChange={(event) => setHookForm({ ...hookForm, blocking: event.target.checked })} /> Blocking</label>
        <button onClick={() => void addHook()}>Add hook</button>
      </div>
      <div className="admin-list">
        {hooks.map((hook) => (
          <div key={hook.id} className="admin-row">
            <strong>{hook.name}</strong>
            <StatusBadge value={hook.enabled ? 'complete' : 'failed'} />
            <span>{hook.stage} · {hook.hook_kind}</span>
            <button onClick={() => void runAction(() => api.testHook(hook.id))}>Test</button>
          </div>
        ))}
      </div>
      <h2>Duplicates</h2>
      <div className="admin-list">
        {duplicates.map((doc) => (
          <div key={doc.id} className="admin-row">
            <button onClick={() => onOpenDocument(doc.id)}>{doc.manual_title_override || doc.extracted_title || doc.original_filename}</button>
            <StatusBadge value={doc.processing_state} />
            <span>Duplicate of {doc.duplicate_of_document_id}</span>
            <button className="icon-button" title="Force retry OCR" onClick={() => void retry(doc.id)}><RotateCcw size={18} /></button>
          </div>
        ))}
      </div>
      <h2>Failed</h2>
      <div className="admin-list">
        {failed.map((job) => (
          <div key={job.document_id} className="admin-row">
            <button onClick={() => onOpenDocument(job.document_id)}>{job.title || job.filename}</button>
            <StatusBadge value={job.state} />
            <span>{job.error_message}</span>
            <button className="icon-button" title="Retry" onClick={() => void retry(job.document_id)}><RotateCcw size={18} /></button>
          </div>
        ))}
      </div>
      <h2>Recent Jobs</h2>
      <div className="admin-list">
        {jobs.map((job) => (
          <div key={job.document_id} className="admin-row">
            <button onClick={() => onOpenDocument(job.document_id)}>{job.title || job.filename}</button>
            <StatusBadge value={job.state} />
            <span>{new Date(job.updated_at).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </main>
  )
}
