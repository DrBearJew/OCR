import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const dashboard = readFileSync(resolve(root, 'src/pages/DashboardPage.tsx'), 'utf8')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const searchPage = readFileSync(resolve(root, 'src/pages/SearchPage.tsx'), 'utf8')
const packageJson = readFileSync(resolve(root, 'package.json'), 'utf8')

const checks = [
  ['collection_name comes from record-level collectionName', "form.set('collection_name', collectionName || 'Dokumente')"],
  ['record metadata contains shared title base', 'shared_title_base: sharedTitle.sharedTitleBase'],
  ['record metadata contains shared title toggle', 'apply_shared_title_to_documents: sharedTitle.applySharedTitleToDocuments'],
  ['record metadata contains folder path', 'folder_path: folderPath'],
  ['per-file document metadata is submitted', "form.set('document_metadata_json'"],
  ['full pipeline option is submitted', 'auto_process: options.autoProcess'],
  ['Qwen enrichment option is submitted', 'qwen_enrichment_enabled'],
  ['Qwen product helper explains visible metadata filling', 'Qwen fills missing metadata, tags, folders, and search hints from OCR. Locked manual fields are preserved.'],
  ['Qwen field source badge supports evidence tooltip', 'title={info.evidence || undefined}'],
  ['primary action is process all', 'Process All Documents'],
  ['stage-only actions are advanced', 'Advanced stage-only actions'],
  ['selected delete confirmation exists', 'Delete selected'],
  ['upload does not auto-navigate to record', 'Select a file to inspect OCR and metadata.'],
  ['selected document refreshes after actions', 'updateDraftFromDocument(document)'],
  ['Qwen option is sent to reextract endpoint', 'qwen_enabled'],
  ['manual overwrite option is explicit', 'overwrite_manual_values'],
  ['PDF upload input is explicitly accepted', '.pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff'],
  ['dev preview login requires explicit true flag', "VITE_ALLOW_DEMO_LOGIN !== 'true'"],
  ['dev preview login is hard-disabled in production', 'import.meta.env.PROD'],
  ['document resource URLs do not include JWT query tokens', 'access_token='],
  ['search page does not render raw HTML snippets', 'dangerouslySetInnerHTML'],
  ['search page renders mark-only snippet component', 'HighlightedSnippet'],
  ['frontend dependencies are pinned', '"latest"'],
]

const failures = checks.filter(([, needle]) => {
  const source = needle.includes('VITE_ALLOW_DEMO_LOGIN') || needle.includes('import.meta.env.PROD') || needle.includes('qwen_enabled') || needle.includes('overwrite_manual_values') ? `${dashboard}\n${client}` : dashboard
  if (needle === 'access_token=') return client.includes(needle)
  if (needle === 'dangerouslySetInnerHTML') return searchPage.includes(needle)
  if (needle === 'HighlightedSnippet') return !searchPage.includes(needle)
  if (needle === '"latest"') return packageJson.includes(needle)
  return !source.includes(needle)
})

if (failures.length) {
  console.error('Dashboard workflow static checks failed:')
  for (const [label, needle] of failures) {
    console.error(`- ${label}: missing ${needle}`)
  }
  process.exit(1)
}

console.log(`Dashboard workflow static checks passed (${checks.length}).`)
