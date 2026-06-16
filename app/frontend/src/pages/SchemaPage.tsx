import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { Collection, CustomFieldDefinition, CustomFieldType, PaperlessMetadata } from '../types'
import { useI18n } from '../i18n'

const fieldTypes: CustomFieldType[] = ['string', 'text', 'number', 'date', 'boolean', 'select']

export default function SchemaPage() {
  const { t } = useI18n()
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
  const [collectionForm, setCollectionForm] = useState({ name: '', slug: '', icon: '', color: '#22c55e' })
  const [error, setError] = useState('')
  const collectionNameById = useMemo(() => new Map(collections.map((item) => [item.id, item.name])), [collections])

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

  async function addCollection(event: FormEvent) {
    event.preventDefault()
    if (!collectionForm.name.trim()) return
    setError('')
    try {
      const created = await api.createCollection({
        name: collectionForm.name.trim(),
        slug: collectionForm.slug.trim() || undefined,
        icon: collectionForm.icon.trim() || undefined,
        color: collectionForm.color.trim() || undefined
      })
      setCollectionForm({ name: '', slug: '', icon: '', color: '#22c55e' })
      const rows = await api.collections()
      setCollections(rows)
      setSelected(created.id)
      setFields(await api.customFields(created.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create collection')
    }
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
    <main className="schema-page">
      <header className="page-header">
        <div>
          <h1>{t('schemas.title')}</h1>
          <p>{t('schemas.subtitle')}</p>
        </div>
        <button className="icon-button" title={t('common.refresh')} onClick={() => void load()}><RefreshCw size={18} /></button>
      </header>
      {error && <p className="error">{error}</p>}
      <form className="workflow-card create-collection-form schema-create-collection" onSubmit={addCollection}>
        <label>{t('schemas.collectionName')}<input value={collectionForm.name} onChange={(event) => setCollectionForm({ ...collectionForm, name: event.target.value })} placeholder={t('schemas.newCollection')} /></label>
        <label>{t('schemas.slug')}<input value={collectionForm.slug} onChange={(event) => setCollectionForm({ ...collectionForm, slug: event.target.value })} placeholder={t('collections.autoSlug')} /></label>
        <label>{t('schemas.icon')}<input value={collectionForm.icon} onChange={(event) => setCollectionForm({ ...collectionForm, icon: event.target.value })} placeholder="NC" maxLength={4} /></label>
        <label>{t('schemas.color')}<input type="color" value={collectionForm.color} onChange={(event) => setCollectionForm({ ...collectionForm, color: event.target.value })} /></label>
        <button className="primary"><Plus size={18} /> {t('collections.create')}</button>
      </form>
      <section className="schema-layout">
        <aside className="workflow-card schema-collections">
          <h2>{t('collections.title')}</h2>
          {collections.map((collection) => (
            <button key={collection.id} className={selected === collection.id ? 'active' : ''} onClick={() => setSelected(collection.id)}>
              <strong>{collection.name}</strong>
              <span>{collection.slug}</span>
            </button>
          ))}
        </aside>
        <section className="schema-editor-stack">
          <section className="workflow-card schema-panel">
            <h2>{t('schemas.customFields')}</h2>
            <form className="schema-form" onSubmit={addField}>
              <input placeholder={t('schemas.fieldName')} value={name} onChange={(event) => setName(event.target.value)} />
              <input placeholder={t('schemas.slug')} value={slug} onChange={(event) => setSlug(event.target.value)} />
              <select value={fieldType} onChange={(event) => setFieldType(event.target.value as CustomFieldType)}>
                {fieldTypes.map((type) => <option key={type}>{type}</option>)}
              </select>
              <input placeholder={t('schemas.enumOptions')} value={enumOptions} onChange={(event) => setEnumOptions(event.target.value)} />
              <label className="check"><input type="checkbox" checked={required} onChange={(event) => setRequired(event.target.checked)} /> {t('schemas.required')}</label>
              <label className="check"><input type="checkbox" checked={searchable} onChange={(event) => setSearchable(event.target.checked)} /> {t('schemas.searchable')}</label>
              <button className="primary"><Plus size={18} /> {t('schemas.addField')}</button>
            </form>
            <div className="table-wrap">
              <table>
                <thead><tr><th>{t('schemas.order')}</th><th>{t('schemas.name')}</th><th>{t('schemas.slug')}</th><th>{t('schemas.type')}</th><th>{t('schemas.required')}</th><th>{t('schemas.searchable')}</th></tr></thead>
                <tbody>
                  {fields.map((field) => (
                    <tr key={field.id}>
                      <td>{field.display_order}</td>
                      <td>{field.name}</td>
                      <td>{field.slug}</td>
                      <td>{field.field_type}</td>
                      <td>{field.required ? t('common.yes') : t('common.no')}</td>
                      <td>{field.searchable ? t('common.yes') : t('common.no')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="workflow-card schema-panel">
            <h2>{t('schemas.paperlessMetadata')}</h2>
            <form className="schema-form metadata-schema-form" onSubmit={addMetadata}>
              <select value={metadataKind} onChange={(event) => setMetadataKind(event.target.value as typeof metadataKind)}>
                <option value="correspondents">{t('schemas.correspondents')}</option>
                <option value="document-types">{t('schemas.documentTypes')}</option>
                <option value="tags">{t('fields.tags')}</option>
                <option value="storage-paths">{t('schemas.storagePaths')}</option>
              </select>
              <input placeholder={t('schemas.name')} value={metadataName} onChange={(event) => setMetadataName(event.target.value)} />
              <input placeholder={t('schemas.storagePathTemplate')} value={metadataTemplate} onChange={(event) => setMetadataTemplate(event.target.value)} />
              <button className="primary"><Plus size={18} /> {t('schemas.addMetadata')}</button>
            </form>
            <div className="table-wrap">
              <table>
                <thead><tr><th>{t('schemas.name')}</th><th>{t('schemas.slug')}</th><th>{t('dashboard.collection')}</th><th>{t('schemas.template')}</th></tr></thead>
                <tbody>
                  {metadataRows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td>{row.slug}</td>
                      <td>{row.collection_id ? collectionNameById.get(row.collection_id) || row.collection_id : t('schemas.global')}</td>
                      <td>{row.path_template || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </section>
      </section>
    </main>
  )
}
