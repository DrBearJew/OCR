from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentPage


def scan_storage_integrity(db: Session) -> dict[str, Any]:
    root = Path(get_settings().storage_root)
    documents = db.query(Document).all()
    pages = db.query(DocumentPage).all()
    referenced = {Path(document.storage_path).resolve() for document in documents if document.storage_path}
    referenced.update(Path(document.thumbnail_path).resolve() for document in documents if document.thumbnail_path)
    referenced.update(Path(page.rendered_image_path).resolve() for page in pages if page.rendered_image_path)

    missing_files = [
        {"document_id": str(document.id), "path": document.storage_path}
        for document in documents
        if document.storage_path and not Path(document.storage_path).exists()
    ]
    missing_thumbnails = [
        {"document_id": str(document.id), "path": document.thumbnail_path}
        for document in documents
        if document.thumbnail_path and not Path(document.thumbnail_path).exists()
    ]
    missing_page_renders = [
        {"document_page_id": str(page.id), "document_id": str(page.document_id), "path": page.rendered_image_path}
        for page in pages
        if page.rendered_image_path and not Path(page.rendered_image_path).exists()
    ]
    orphan_files: list[str] = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and path.resolve() not in referenced:
                orphan_files.append(str(path))
    soft_deleted_pending_purge = [
        {"document_id": str(document.id), "path": document.storage_path}
        for document in documents
        if document.deleted_at is not None and document.storage_path and Path(document.storage_path).exists()
    ]
    return {
        "missing_files": missing_files,
        "missing_thumbnails": missing_thumbnails,
        "missing_page_renders": missing_page_renders,
        "orphan_files": orphan_files[:500],
        "soft_deleted_pending_purge": soft_deleted_pending_purge,
        "ok": not (missing_files or missing_thumbnails or missing_page_renders),
    }
