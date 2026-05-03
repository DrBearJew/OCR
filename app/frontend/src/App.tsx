import { useEffect, useState } from 'react'
import { getToken, setToken } from './api/client'
import AppShell from './components/AppShell'
import LoginPanel from './components/LoginPanel'
import BatchListPage from './pages/BatchListPage'
import BatchDetailPage from './pages/BatchDetailPage'
import DocumentDetailPage from './pages/DocumentDetailPage'
import SearchPage from './pages/SearchPage'
import AdminPage from './pages/AdminPage'
import RecordListPage from './pages/RecordListPage'
import RecordDetailPage from './pages/RecordDetailPage'
import SchemaPage from './pages/SchemaPage'
import DashboardPage from './pages/DashboardPage'
import CollectionsPage from './pages/CollectionsPage'
import CollectionDetailPage from './pages/CollectionDetailPage'
import DocumentsPage from './pages/DocumentsPage'
import ProcessingPage from './pages/ProcessingPage'
import FailedReviewPage from './pages/FailedReviewPage'
import ActivityPage from './pages/ActivityPage'
import FoldersPage from './pages/FoldersPage'

type Route =
  | { name: 'dashboard' }
  | { name: 'collections' }
  | { name: 'collection'; slug: string }
  | { name: 'folders' }
  | { name: 'batches' }
  | { name: 'batch'; id: string }
  | { name: 'records' }
  | { name: 'record'; id: string }
  | { name: 'documents' }
  | { name: 'document'; id: string }
  | { name: 'search' }
  | { name: 'processing' }
  | { name: 'failed' }
  | { name: 'schemas' }
  | { name: 'admin' }
  | { name: 'activity' }

function parseRoute(): Route {
  const path = window.location.pathname.replace(/^\/+/, '')
  const [name, id] = path.split('/')
  if (!name || name === 'dashboard') return { name: 'dashboard' }
  if (name === 'collections' && id) return { name: 'collection', slug: decodeURIComponent(id) }
  if (name === 'collections') return { name: 'collections' }
  if (name === 'folders') return { name: 'folders' }
  if (name === 'batches' && id) return { name: 'batch', id }
  if (name === 'batches') return { name: 'batches' }
  if (name === 'records' && id) return { name: 'record', id }
  if (name === 'records') return { name: 'records' }
  if (name === 'documents' && id) return { name: 'document', id }
  if (name === 'documents') return { name: 'documents' }
  if (name === 'search') return { name: 'search' }
  if (name === 'processing') return { name: 'processing' }
  if (name === 'failed') return { name: 'failed' }
  if (name === 'schemas') return { name: 'schemas' }
  if (name === 'admin') return { name: 'admin' }
  if (name === 'activity') return { name: 'activity' }
  return { name: 'dashboard' }
}

function navigate(path: string) {
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute())
  const [authed, setAuthed] = useState(Boolean(getToken()))

  useEffect(() => {
    const onRoute = () => setRoute(parseRoute())
    window.addEventListener('popstate', onRoute)
    return () => window.removeEventListener('popstate', onRoute)
  }, [])

  if (!authed) return <LoginPanel onLogin={() => setAuthed(true)} />

  return (
    <AppShell active={route.name} onNavigate={navigate} onLogout={() => { setToken(null); setAuthed(false) }}>
        {route.name === 'dashboard' && <DashboardPage onOpenRecord={(id) => navigate(`/records/${id}`)} onOpenDocument={(id) => navigate(`/documents/${id}`)} onSearch={() => navigate('/search')} />}
        {route.name === 'collections' && <CollectionsPage onOpenCollection={(slug) => navigate(`/collections/${slug}`)} onSchemas={() => navigate('/schemas')} />}
        {route.name === 'collection' && <CollectionDetailPage slug={route.slug} onOpenRecord={(id) => navigate(`/records/${id}`)} />}
        {route.name === 'folders' && <FoldersPage onOpenRecord={(id) => navigate(`/records/${id}`)} onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'records' && <RecordListPage onOpenRecord={(id) => navigate(`/records/${id}`)} />}
        {route.name === 'batches' && <BatchListPage onOpenBatch={(id) => navigate(`/batches/${id}`)} />}
        {route.name === 'batch' && <BatchDetailPage id={route.id} onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'record' && <RecordDetailPage id={route.id} onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'documents' && <DocumentsPage onOpenDocument={(id) => navigate(`/documents/${id}`)} onOpenRecord={(id) => navigate(`/records/${id}`)} />}
        {route.name === 'document' && <DocumentDetailPage id={route.id} />}
        {route.name === 'search' && <SearchPage onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'processing' && <ProcessingPage onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'failed' && <FailedReviewPage onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'schemas' && <SchemaPage />}
        {route.name === 'admin' && <AdminPage onOpenDocument={(id) => navigate(`/documents/${id}`)} />}
        {route.name === 'activity' && <ActivityPage onOpenDocument={(id) => navigate(`/documents/${id}`)} onOpenRecord={(id) => navigate(`/records/${id}`)} />}
    </AppShell>
  )
}
