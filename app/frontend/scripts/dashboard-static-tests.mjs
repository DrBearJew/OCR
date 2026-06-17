import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const dashboard = readFileSync(resolve(root, 'src/pages/DashboardPage.tsx'), 'utf8')
const client = readFileSync(resolve(root, 'src/api/client.ts'), 'utf8')
const searchPage = readFileSync(resolve(root, 'src/pages/SearchPage.tsx'), 'utf8')
const documentsPage = readFileSync(resolve(root, 'src/pages/DocumentsPage.tsx'), 'utf8')
const foldersPage = readFileSync(resolve(root, 'src/pages/FoldersPage.tsx'), 'utf8')
const collectionsPage = readFileSync(resolve(root, 'src/pages/CollectionsPage.tsx'), 'utf8')
const collectionDetailPage = readFileSync(resolve(root, 'src/pages/CollectionDetailPage.tsx'), 'utf8')
const schemaPage = readFileSync(resolve(root, 'src/pages/SchemaPage.tsx'), 'utf8')
const adminPage = readFileSync(resolve(root, 'src/pages/AdminPage.tsx'), 'utf8')
const processingPage = readFileSync(resolve(root, 'src/pages/ProcessingPage.tsx'), 'utf8')
const recordDetailPage = readFileSync(resolve(root, 'src/pages/RecordDetailPage.tsx'), 'utf8')
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
  ['Upload PDF preview uses rendered page image', dashboard, 'documentPreviewPageUrl(selected.documentId, 1)'],
  ['Client exposes PDF preview page URL', client, 'preview-page/${pageNumber}'],
  ['Upload preview fit mode uses panel width minus small gutter', dashboard, 'surface.clientWidth - 48'],
  ['Upload preview fit repair CSS is present', styles, 'Upload preview fit repair: 100% fits'],
  ['Upload PDF preview click zoom is enabled', dashboard, 'if (isPdf) return', true],
  ['Upload PDF zoomed mode is unclamped', styles, 'Upload PDF preview zoom repair'],
  ['Upload PDF preview image has explicit class', dashboard, 'upload-pdf-page-preview'],
  ['Documents page exposes delete selected action', documentsPage, 'documents.deleteSelected'],
  ['Documents page calls deleteDocument API', documentsPage, 'api.deleteDocument'],
  ['Documents bulk actions fall back to active row', documentsPage, 'selectedDocumentIdsForActions'],
  ['Documents bulk bar labels active target', documentsPage, 'documents.activeTarget'],
  ['Documents mobile row taps open documents', documentsPage, 'handleDocumentRowClick'],
  ['Documents mobile rows are focusable non-button rows', documentsPage, 'role="button"'],
  ['Documents mobile rows no longer use a button wrapper', documentsPage, '<button key={document.id}', true],
  ['Documents mobile CSS removes desktop row min-width', styles, 'Documents mobile: keep rows inside the viewport'],
  ['Documents inspector exposes delete action', documentsPage, 'onDelete'],
  ['Documents inspector does not fake sender fallback', documentsPage, "document.extracted_sender || 'Demo Ges.mbh'", true],
  ['Documents inspector does not fake invoice fallback', documentsPage, "document.extracted_invoice_number || 'PR400000005'", true],
  ['Documents inspector does not fake demo tags', documentsPage, 'supplier:demo</button>', true],
  ['Documents page uses cursor-paginated API', documentsPage, 'api.documentsPage'],
  ['Documents page exposes Load more pagination', documentsPage, 'loadMoreDocuments'],
  ["Documents page exposes all-matching filter bulk scope", documentsPage, "selection_mode: 'filters'"],
  ['Documents page caps all-matching bulk actions', documentsPage, 'DOCUMENT_BULK_FILTER_LIMIT'],
  ['Folders page uses paginated folder contents API', foldersPage, 'api.folderContents'],
  ['Folders page can load more folder contents', foldersPage, 'loadMore'],
  ['Folders Home does not load all documents by default', foldersPage, 'emptyDocumentPage'],
  ['Folders selected folders use direct document scope', foldersPage, "return 'direct'"],
  ['Folders page uses document shortcut grid', foldersPage, 'folder-shortcut-grid'],
  ['Folders shortcuts expose hover preview', foldersPage, 'folder-shortcut-preview'],
  ['Folders refresh button has designed class', foldersPage, 'folder-refresh-button'],
  ['Folders search button has designed class', foldersPage, 'folder-search-button'],
  ['Folders page does not expose record folder moves', foldersPage, 'api.moveRecordToFolder', true],
  ['Folders page can move documents', foldersPage, 'api.moveDocumentToFolder'],
  ['Folders page can delete document shortcuts', foldersPage, 'api.deleteDocument'],
  ['Folders folder delete can request content deletion', `${foldersPage}\n${client}`, 'delete_contents=true'],
  ['Folders file shortcut delete button exists', foldersPage, 'folder-shortcut-delete'],
  ['Folders page can rename or move folders', foldersPage, 'api.updateFolder'],
  ['Folders page exposes unfiled filing workflow', foldersPage, 'showUnfiledOnly'],
  ['Folders page has filing cockpit styles', styles, 'Folders page: make folders a working filing cockpit'],
  ['Collections page exposes create collection action', collectionsPage, 'collections.create'],
  ['Collections page calls createCollection API', collectionsPage, 'api.createCollection'],
  ['Schemas page exposes create collection action', schemaPage, 'collections.create'],
  ['Records page uses cursor-paginated API', `${client}\n${readFileSync(resolve(root, 'src/pages/RecordListPage.tsx'), 'utf8')}`, 'api.recordsPage'],
  ['Records page exposes Load more pagination', readFileSync(resolve(root, 'src/pages/RecordListPage.tsx'), 'utf8'), 'loadMoreRecords'],
  ['Record detail can delete a single child document', recordDetailPage, 'api.deleteDocument(document.id)'],
  ['Record detail distinguishes document delete from record delete', recordDetailPage, 'recordDetail.deleteDocumentConfirm'],
  ['Collection detail uses paginated records API', collectionDetailPage, 'api.recordsPage'],
  ['Collection detail exposes Load more pagination', collectionDetailPage, 'loadMoreCollectionRecords'],
  ['Search page uses cursor-paginated API', `${client}\n${searchPage}`, 'api.searchPage'],
  ['Search page exposes Load more pagination', searchPage, 'loadMoreSearchResults'],
  ['Schemas page calls createCollection API', schemaPage, 'api.createCollection'],
  ['Schemas page calls deleteCollection API', `${schemaPage}\n${client}`, 'api.deleteCollection'],
  ['Schemas page exposes schema delete button', schemaPage, 'schema-delete-button'],
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
