import { MouseEvent, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, ExternalLink, Minus, Plus, RotateCw } from 'lucide-react'
import { downloadUrl, previewPageUrl, previewUrl } from '../api/client'
import { useI18n } from '../i18n'

interface PdfPageViewerProps {
  documentId: string
  filename: string
  pageCount?: number | null
  height?: string
  showTools?: boolean
  className?: string
}

export default function PdfPageViewer({
  documentId,
  filename,
  pageCount,
  height = 'min(48vh, 500px)',
  showTools = true,
  className = '',
}: PdfPageViewerProps) {
  const { t } = useI18n()
  const totalPages = Math.max(1, pageCount ?? 1)
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(100)
  const [rotation, setRotation] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const surfaceRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setPage(1)
    setZoom(100)
    setRotation(0)
    setLoadFailed(false)
  }, [documentId])

  useEffect(() => {
    setLoadFailed(false)
  }, [page])

  function clampZoom(value: number) {
    return Math.max(60, Math.min(300, value))
  }

  function centerRatio() {
    const surface = surfaceRef.current
    if (!surface || !surface.scrollWidth || !surface.scrollHeight) return { x: 0.5, y: 0.5 }
    return {
      x: (surface.scrollLeft + surface.clientWidth / 2) / surface.scrollWidth,
      y: (surface.scrollTop + surface.clientHeight / 2) / surface.scrollHeight,
    }
  }

  function setZoomAround(nextZoom: number, ratio = centerRatio()) {
    const surface = surfaceRef.current
    setZoom(clampZoom(nextZoom))
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!surface) return
      surface.scrollLeft = Math.max(0, Math.min(surface.scrollWidth - surface.clientWidth, ratio.x * surface.scrollWidth - surface.clientWidth / 2))
      surface.scrollTop = Math.max(0, Math.min(surface.scrollHeight - surface.clientHeight, ratio.y * surface.scrollHeight - surface.clientHeight / 2))
    }))
  }

  function handleSurfaceClick(event: MouseEvent<HTMLDivElement>) {
    if (loadFailed) return
    const img = event.currentTarget.querySelector('img')
    if (!img) return
    const rect = img.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
    setZoomAround(zoom >= 170 ? 100 : 175, { x, y })
  }

  const pageSrc = previewPageUrl(documentId, page)
  const fullPdfUrl = `${previewUrl(documentId)}#page=${page}`

  return (
    <div className={`pdf-viewer-shell ${className}`.trim()}>
      <div className="pdf-viewer-toolbar" role="toolbar" aria-label={t('documents.preview')}>
        <div className="pdf-viewer-group">
          <button
            type="button"
            className="icon-button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            title={t('common.previous', 'Previous page')}
            aria-label={t('common.previous', 'Previous page')}
          >
            <ChevronLeft size={15} />
          </button>
          <span className="pdf-viewer-page-indicator" aria-live="polite">
            {totalPages > 1 ? (
              <>
                <input
                  type="number"
                  min={1}
                  max={totalPages}
                  value={page}
                  aria-label={t('documents.page', 'Page')}
                  onChange={(e) => {
                    const next = Number(e.target.value)
                    if (Number.isFinite(next) && next >= 1 && next <= totalPages) setPage(next)
                  }}
                />
                <span>/ {totalPages}</span>
              </>
            ) : (
              <span>1 / 1</span>
            )}
          </span>
          <button
            type="button"
            className="icon-button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            title={t('common.next', 'Next page')}
            aria-label={t('common.next', 'Next page')}
          >
            <ChevronRight size={15} />
          </button>
        </div>

        <div className="pdf-viewer-group">
          <button type="button" className="icon-button" onClick={() => setZoomAround(zoom - 25)} title={t('common.zoomOut')} aria-label={t('common.zoomOut')}><Minus size={15} /></button>
          <button type="button" className="zoom-value" onClick={() => setZoomAround(100, { x: 0.5, y: 0.5 })} title={t('common.resetZoom')}>{zoom}%</button>
          <button type="button" className="icon-button" onClick={() => setZoomAround(zoom + 25)} title={t('common.zoomIn')} aria-label={t('common.zoomIn')}><Plus size={15} /></button>
          <button type="button" className="icon-button" onClick={() => setRotation((r) => (r + 90) % 360)} title={t('dashboard.rotate', 'Rotate 90°')} aria-label={t('dashboard.rotate', 'Rotate 90°')}><RotateCw size={15} /></button>
        </div>

        {showTools && (
          <div className="pdf-viewer-group">
            <a className="icon-button" href={fullPdfUrl} target="_blank" rel="noreferrer" title={t('collectionDetail.openFullPdf', 'Open PDF in new tab')} aria-label={t('collectionDetail.openFullPdf', 'Open PDF in new tab')}><ExternalLink size={15} /></a>
            <a className="icon-button" href={downloadUrl(documentId)} title={t('common.download')} aria-label={t('common.download')}><Download size={15} /></a>
          </div>
        )}
      </div>

      <div
        ref={surfaceRef}
        className={`pdf-viewer-surface ${zoom > 100 ? 'is-zoomed' : ''}`}
        style={{ height }}
        onClick={handleSurfaceClick}
        title={t('documents.clickToZoom', 'Click page to zoom')}
      >
        {loadFailed ? (
          <div className="pdf-viewer-fallback">
            <p>{t('documents.previewUnavailable', 'Rendered page preview is unavailable.')}</p>
            <div className="button-row">
              <button type="button" onClick={() => setLoadFailed(false)}>{t('common.retry', 'Retry')}</button>
              <a className="primary-link-button" href={fullPdfUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} /> {t('collectionDetail.openFullPdf', 'Open full PDF')}</a>
            </div>
          </div>
        ) : (
          <div className="pdf-viewer-stage">
            <img
              className="pdf-viewer-page-img"
              src={pageSrc}
              alt={`${filename} — ${page}/${totalPages}`}
              style={{
                width: `${zoom}%`,
                maxWidth: zoom <= 100 ? '100%' : 'none',
                transform: rotation ? `rotate(${rotation}deg)` : undefined,
              }}
              onError={() => setLoadFailed(true)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
