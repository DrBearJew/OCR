import { FormEvent, useEffect, useState } from 'react'
import { Bookmark, Check, Plus, X } from 'lucide-react'
import { api } from '../api/client'
import type { SavedView } from '../types'
import { useI18n } from '../i18n'

export default function SavedViewsBar({ section, filters, onApply }: { section: string; filters: Record<string, string>; onApply: (filters: Record<string, string>) => void }) {
  const { t } = useI18n()
  const [views, setViews] = useState<SavedView[]>([])
  const [name, setName] = useState('')
  const [savingOpen, setSavingOpen] = useState(false)

  async function load() {
    setViews(await api.savedViews(section))
  }

  useEffect(() => { void load() }, [section])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    await api.createSavedView({ name: name.trim(), section, filters_json: filters })
    setName('')
    setSavingOpen(false)
    await load()
  }

  return (
    <form className="saved-views" onSubmit={save}>
      <Bookmark size={14} className="saved-views-icon" />
      <select
        aria-label={t('savedViews.placeholder')}
        onChange={(event) => {
          const view = views.find((item) => item.id === event.target.value)
          if (view) onApply(view.filters_json as Record<string, string>)
        }}
        defaultValue=""
      >
        <option value="">{t('savedViews.placeholder')}</option>
        {views.map((view) => <option key={view.id} value={view.id}>{view.name}</option>)}
      </select>
      {savingOpen ? (
        <>
          <input
            autoFocus
            placeholder={t('savedViews.saveAs')}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button type="submit" className="icon-button" title={t('savedViews.saveView')}><Check size={14} /></button>
          <button type="button" className="icon-button" title={t('common.cancel')} onClick={() => { setSavingOpen(false); setName('') }}><X size={14} /></button>
        </>
      ) : (
        <button type="button" className="icon-button" title={t('savedViews.saveView')} onClick={() => setSavingOpen(true)}>
          <Plus size={14} />
        </button>
      )}
    </form>
  )
}
