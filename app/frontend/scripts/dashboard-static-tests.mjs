import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const dashboard = readFileSync(resolve(root, 'src/pages/DashboardPage.tsx'), 'utf8')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const searchPage = readFileSync(resolve(root, 'src/pages/SearchPage.tsx'), 'utf8')
const documentsPage = readFileSync(resolve(root, 'src/pages/DocumentsPage.tsx'), 'utf8')
const collectionsPage = readFileSync(resolve(root, 'src/pages/CollectionsPage.tsx'), 'utf8')
const schemaPage = readFileSync(resolve(root, 'src/pages/SchemaPage.tsx'), 'utf8')
const adminPage = readFileSync(resolve(root, 'src/pages/AdminPage.tsx'), 'utf8')
const processingPage = readFileSync(resolve(root, 'src/pages/ProcessingPage.tsx'), 'utf8')
const styles = readFileSync(resolve(root, 'src/styles.css'), 'utf8')
const packageJson = readFileSync(resolve(root, 'package.json'), 'utf8')

const checks = [
  ['collection_name comes from record-level collectionName', dashboard, "form.set('collection_name', collectionName || 'Dokumente')"],
  ['record metadata contains shared title base', dashboard, 'shared_title_base: sharedTitle.sharedTitleBase'],
  ['record metadata contains shared title toggle', dashboard, 'apply_shared_title_to_documents: sharedTitle.applySharedTitleToDocuments'],
  ['record metadata contains folder path', dashboard, 'folder_path: folderPath'],
  ['per-file document metadata is submitted', dashboard, "form.set('document_metadata_json'"],
  ['full pipeline option is submitted', dashboard, 'auto_process: options.autoProcess'],
  ['Qwen enrichment option is submitted', dashboard, 'qwen_enrichment_enabled'],
  ['Qwen product helper explains visible metadata filling', dashboard, 'dashboard.qwenProcessingCopy'],
  ['Qwen field source badge supports evidence tooltip', dashboard, 'title={info.evidence || undefined}'],
  ['primary action is process all', dashboard, 'dashboard.processAllDocuments'],
  ['stage-only actions are advanced', dashboard, 'dashboard.advancedActions'],
  ['dashboard selected delete confirmation exists', dashboard, 'dashboard.deleteSelected'],
  ['upload does not auto-navigate to record', dashboard, 'dashboard.message.uploadedSuffix'],
  ['selected document refreshes after actions', dashboard, 'updateDraftFromDocument(document)'],
  ['Qwen option is sent to reextract endpoint', `${dashboard}\n${client}`, 'qwen_enabled'],
  ['OCR engine option is submitted', dashboard, 'ocr_engine: options.ocrEngine'],
  ['Fast OCR option is visible', dashboard, 'dashboard.fastOcr'],
  ['manual overwrite option is explicit', `${dashboard}\n${client}`, 'overwrite_manual_values'],
  ['PDF upload input is explicitly accepted', dashboard, '.pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff'],
  ['Documents page exposes delete selected action', documentsPage, 'documents.deleteSelected'],
  ['Documents page calls deleteDocument API', documentsPage, 'api.deleteDocument'],
  ['Documents bulk actions fall back to active row', documentsPage, 'selectedDocumentIdsForActions'],
  ['Documents bulk bar labels active target', documentsPage, 'documents.activeTarget'],
  ['Documents mobile row taps open documents', documentsPage, 'handleDocumentRowClick'],
  ['Documents mobile rows are focusable non-button rows', documentsPage, 'role="button"'],
  ['Documents mobile rows no longer use a button wrapper', documentsPage, '<button key={document.id}', true],
  ['Documents mobile CSS removes desktop row min-width', styles, 'Documents mobile: keep rows inside the viewport'],
  ['Documents inspector exposes delete action', documentsPage, 'onDelete'],
  ['Collections page exposes create collection action', collectionsPage, 'collections.create'],
  ['Collections page calls createCollection API', collectionsPage, 'api.createCollection'],
  ['Schemas page exposes create collection action', schemaPage, 'collections.create'],
  ['Schemas page calls createCollection API', schemaPage, 'api.createCollection'],
  ['Schemas page has dark scoped page class', schemaPage, 'className="schema-page"'],
  ['Admin page has dark scoped page class', adminPage, 'className="admin-page admin-console"'],
  ['Processing page has dark scoped page class', processingPage, 'className="processing-page"'],
  ['Dark schema overrides are present', styles, '.schema-page input'],
  ['Dark admin overrides are present', styles, '.admin-console input'],
  ['Dark processing overrides are present', styles, '.processing-page input'],
  ['Dashboard shared-title grid repair is present', styles, '.shared-title-preview {\n  grid-column: 1 / -1;'],
  ['dev preview login requires explicit true flag', `${dashboard}\n${client}`, "VITE_ALLOW_DEMO_LOGIN !== 'true'"],
  ['dev preview login is hard-disabled in production', `${dashboard}\n${client}`, 'import.meta.env.PROD'],
  ['expired stored auth token clears itself before boot', client, 'isStoredTokenExpired(token)'],
  ['API 401 expires client session globally', client, 'response.status === 401'],
  ['auth expiry notifies mounted app', client, 'AUTH_EXPIRED_EVENT'],
  ['document resource URLs do not include JWT query tokens', client, 'access_token=', true],
  ['search page does not render raw HTML snippets', searchPage, 'dangerouslySetInnerHTML', true],
  ['search page renders mark-only snippet component', searchPage, 'HighlightedSnippet'],
  ['frontend dependencies are pinned', packageJson, '"latest"', true],
]

const failures = checks.filter(([, source, needle, mustBeAbsent]) => {
  const found = source.includes(needle)
  return mustBeAbsent ? found : !found
})

if (failures.length) {
  console.error('Dashboard workflow static checks failed:')
  for (const [label, , needle, mustBeAbsent] of failures) {
    console.error(`- ${label}: missing ${needle}`)
    if (mustBeAbsent) console.error(`  forbidden substring is present: ${needle}`)
  }
  process.exit(1)
}

console.log(`Dashboard workflow static checks passed (${checks.length}).`)
