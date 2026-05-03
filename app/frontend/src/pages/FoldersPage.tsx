import { FormEvent, useEffect, useMemo, useState } from 'react'
import { FolderPlus, FolderTree, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Document, Folder, RecordRow } from '../types'

interface Props {
  onOpenRecord: (id: string) => void
  onOpenDocument: (id: string) => void
}

export default function FoldersPage({ onOpenRecord, onOpenDocument }: Props) {
  const [folders, setFolders] = useState<Folder[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [records, setRecords] = useState<RecordRow[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const selected = useMemo(() => folders.find((folder) => folder.id === selectedId) || null, [folders, selectedId])

  useEffect(() => {
    void load()
  }, [])

  async function load(folderId = selectedId) {
    const [folderRows, recordRows, documentRows] = await Promise.all([
      api.folders(),
      api.records(),
      api.documents(folderId ? { folder_id: folderId } : {})
    ])
    setFolders(folderRows)
    setRecords(folderId ? recordRows.filter((record) => record.folder_id === folderId) : recordRows)
    setDocuments(documentRows)
  }

  async function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    const folder = await api.createFolder({ name: name.trim(), parent_id: selectedId })
    setName('')
    setSelectedId(folder.id)
    setMessage(`Created ${folder.path}`)
    await load(folder.id)
  }

  async function remove(folder: Folder) {
    if (!confirm(`Delete folder "${folder.path}"? Records and documents remain stored, but the folder will be hidden.`)) return
    await api.deleteFolder(folder.id)
    setSelectedId(null)
    setMessage(`Deleted ${folder.path}`)
    await load(null)
  }

  const breadcrumb = selected?.path?.split('/') ?? ['Home']

  return (
    <main className="page-grid folders-page">
      <section className="panel page-header-panel">
        <div>
          <h1>Folders</h1>
          <p>Windows-like structure for records and OCR documents, backed by the database.</p>
        </div>
        <button type="button" onClick={() => void load()}><RefreshCw size={16} /> Refresh</button>
      </section>

      {message && <p className="success-message">{message}</p>}

      <section className="panel folder-layout">
        <aside className="folder-tree-panel">
          <h2><FolderTree size={18} /> Folder tree</h2>
          <button className={!selectedId ? 'active' : ''} onClick={() => { setSelectedId(null); void load(null) }}>Home</button>
          {folders.map((folder) => (
            <div className="folder-row" key={folder.id}>
              <button className={folder.id === selectedId ? 'active' : ''} onClick={() => { setSelectedId(folder.id); void load(folder.id) }}>
                <span style={{ paddingLeft: `${Math.max(0, folder.path.split('/').length - 1) * 14}px` }}>{folder.name}</span>
                <small>{folder.record_count + folder.document_count}</small>
              </button>
              <button title="Delete folder" onClick={() => void remove(folder)}><Trash2 size={14} /></button>
            </div>
          ))}
          <form className="folder-create-form" onSubmit={create}>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder={selected ? `New inside ${selected.name}` : 'New folder'} />
            <button className="primary"><FolderPlus size={15} /> Create</button>
          </form>
        </aside>

        <section className="folder-content-panel">
          <div className="breadcrumb">{breadcrumb.map((part, index) => <span key={`${part}-${index}`}>{index ? ' / ' : ''}{part}</span>)}</div>
          <h2>{selected?.path || 'All folders'}</h2>
          <div className="stat-grid">
            <div><strong>{records.length}</strong><span>Records</span></div>
            <div><strong>{documents.length}</strong><span>Documents</span></div>
            <div><strong>{folders.filter((folder) => folder.parent_id === selectedId).length}</strong><span>Child folders</span></div>
          </div>
          <div className="table-card">
            <h3>Records</h3>
            {records.slice(0, 12).map((record) => (
              <button key={record.id} className="list-row" onClick={() => onOpenRecord(record.id)}>
                <span>{record.title}</span><small>{record.document_count} docs · {record.status}</small>
              </button>
            ))}
          </div>
          <div className="table-card">
            <h3>Documents</h3>
            {documents.slice(0, 12).map((document) => (
              <button key={document.id} className="list-row" onClick={() => onOpenDocument(document.id)}>
                <span>{document.manual_title_override || document.extracted_title || document.original_filename}</span>
                <small>{document.collection_name} · {document.processing_state}</small>
              </button>
            ))}
          </div>
        </section>
      </section>
    </main>
  )
}
