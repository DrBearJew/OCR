import { FormEvent, useEffect, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { Collection, CustomFieldDefinition, CustomFieldType, PaperlessMetadata } from '../types'

const fieldTypes: CustomFieldType[] = ['string', 'text', 'number', 'date', 'boolean', 'select']

export default function SchemaPage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selected, setSelected] = useState('')
  const [fields, setFields] = useState<CustomFieldDefinition[]>([])
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [fieldType, setFieldType] = useState<CustomFieldType>('string')
  const [required, setRequired] = useState(false)
  const [searchable, setSearchable] = useState(true)
  const [enumOptions, setEnumOptions] = useState('')
  const [metadataKind, setMetadataKind] = useState<'correspondents' | 'document-types' | 'tags' | 'storage-paths'>('correspondents')
  const [metadataRows, setMetadataRows] = useState<PaperlessMetadata[]>([])
  const [metadataName, setMetadataName] = useState('')
  const [metadataTemplate, setMetadataTemplate] = useState('{collection}/{year}')
  const [error, setError] = useState('')

  async function load() {
    setError('')
    try {
      const rows = await api.collections()
      setCollections(rows)
      const id = selected || rows[0]?.id || ''
      setSelected(id)
      if (id) setFields(await api.customFields(id))
      setMetadataRows(await api.paperlessMetadata(metadataKind))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load schemas')
    }
  }

  useEffect(() => { void load() }, [])
  useEffect(() => {
    if (selected) void api.customFields(selected).then(setFields)
  }, [selected])
  useEffect(() => {
    void api.paperlessMetadata(metadataKind).then(setMetadataRows)
  }, [metadataKind])

  async function addField(event: FormEvent) {
    event.preventDefault()
    if (!selected) return
    await api.createCustomField(selected, {
      name,
      slug,
      field_type: fieldType,
      required,
      searchable,
      enum_options: enumOptions.split(',').map((item) => item.trim()).filter(Boolean),
      display_order: fields.length + 1
    })
    setName('')
    setSlug('')
    setEnumOptions('')
    setFields(await api.customFields(selected))
  }

  async function addMetadata(event: FormEvent) {
    event.preventDefault()
    if (!metadataName.trim()) return
    await api.createPaperlessMetadata(metadataKind, {
      collection_id: selected || null,
      name: metadataName.trim(),
      path_template: metadataKind === 'storage-paths' ? metadataTemplate : null
    })
    setMetadataName('')
    setMetadataRows(await api.paperlessMetadata(metadataKind))
  }

  return (
    <main>
      <header className="page-header">
        <div>
          <h1>Schemas</h1>
          <p>Manage PocketBase-like collection schemas and custom document fields.</p>
        </div>
        <button className="icon-button" title="Refresh" onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <section className="schema-layout">
        <aside className="schema-collections">
          {collections.map((collection) => (
            <button key={collection.id} className={selected === collection.id ? 'active' : ''} onClick={() => setSelected(collection.id)}>
              <strong>{collection.name}</strong>
              <span>{collection.slug}</span>
            </button>
          ))}
        </aside>
        <section>
          <form className="schema-form" onSubmit={addField}>
            <input placeholder="Field name" value={name} onChange={(event) => setName(event.target.value)} />
            <input placeholder="slug" value={slug} onChange={(event) => setSlug(event.target.value)} />
            <select value={fieldType} onChange={(event) => setFieldType(event.target.value as CustomFieldType)}>
              {fieldTypes.map((type) => <option key={type}>{type}</option>)}
            </select>
            <input placeholder="Enum options, comma separated" value={enumOptions} onChange={(event) => setEnumOptions(event.target.value)} />
            <label className="check"><input type="checkbox" checked={required} onChange={(event) => setRequired(event.target.checked)} /> Required</label>
            <label className="check"><input type="checkbox" checked={searchable} onChange={(event) => setSearchable(event.target.checked)} /> Searchable</label>
            <button className="primary"><Plus size={18} /> Add field</button>
          </form>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Order</th><th>Name</th><th>Slug</th><th>Type</th><th>Required</th><th>Searchable</th></tr></thead>
              <tbody>
                {fields.map((field) => (
                  <tr key={field.id}>
                    <td>{field.display_order}</td>
                    <td>{field.name}</td>
                    <td>{field.slug}</td>
                    <td>{field.field_type}</td>
                    <td>{field.required ? 'yes' : 'no'}</td>
                    <td>{field.searchable ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>Paperless Metadata</h2>
          <form className="schema-form" onSubmit={addMetadata}>
            <select value={metadataKind} onChange={(event) => setMetadataKind(event.target.value as typeof metadataKind)}>
              <option value="correspondents">Correspondents</option>
              <option value="document-types">Document types</option>
              <option value="tags">Tags</option>
              <option value="storage-paths">Storage paths</option>
            </select>
            <input placeholder="Name" value={metadataName} onChange={(event) => setMetadataName(event.target.value)} />
            <input placeholder="Storage path template" value={metadataTemplate} onChange={(event) => setMetadataTemplate(event.target.value)} />
            <button className="primary"><Plus size={18} /> Add metadata</button>
          </form>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Slug</th><th>Collection</th><th>Template</th></tr></thead>
              <tbody>
                {metadataRows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>{row.slug}</td>
                    <td>{row.collection_id || 'global'}</td>
                    <td>{row.path_template || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  )
}
