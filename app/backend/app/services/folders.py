from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, Folder, Record
from app.services.events import record_event
from app.services.storage import LocalStorage


def sanitize_folder_segment(value: str) -> str:
    segment = re.sub(r"[\\/:*?\"<>|]+", "-", value or "")
    segment = re.sub(r"\s+", " ", segment).strip(" .")
    return segment[:120] or "Unsorted"


def recompute_folder_path(db: Session, folder: Folder) -> str:
    parent_path = ""
    if folder.parent_id:
        parent = db.get(Folder, folder.parent_id)
        parent_path = parent.path if parent else ""
    folder.path = "/".join(part for part in [parent_path, sanitize_folder_segment(folder.name)] if part)
    return folder.path


def create_folder(db: Session, name: str, parent_id: uuid.UUID | None = None, collection_id: uuid.UUID | None = None) -> Folder:
    folder = Folder(parent_id=parent_id, collection_id=collection_id, name=sanitize_folder_segment(name), path="")
    recompute_folder_path(db, folder)
    db.add(folder)
    db.flush()
    return folder


def rename_folder(db: Session, folder: Folder, name: str) -> Folder:
    folder.name = sanitize_folder_segment(name)
    recompute_folder_path(db, folder)
    for child in folder.children:
        _recompute_descendants(db, child)
    return folder


def move_folder(db: Session, folder: Folder, parent_id: uuid.UUID | None) -> Folder:
    if parent_id == folder.id:
        raise ValueError("Folder cannot be its own parent")
    ancestor_id = parent_id
    while ancestor_id is not None:
        if ancestor_id == folder.id:
            raise ValueError("Folder cannot be moved under one of its descendants")
        parent = db.get(Folder, ancestor_id)
        ancestor_id = parent.parent_id if parent else None
    folder.parent_id = parent_id
    recompute_folder_path(db, folder)
    for child in folder.children:
        _recompute_descendants(db, child)
    return folder


def ensure_folder_path(db: Session, path: str, collection_id: uuid.UUID | None = None) -> Folder:
    parts = [sanitize_folder_segment(part) for part in path.split("/") if part.strip()]
    if not parts:
        parts = ["Unsorted"]
    parent_id: uuid.UUID | None = None
    current: Folder | None = None
    for part in parts:
        current = db.scalars(
            select(Folder)
            .where(Folder.parent_id == parent_id)
            .where(Folder.name == part)
            .where(Folder.deleted_at.is_(None))
        ).first()
        if current is None:
            current = create_folder(db, part, parent_id=parent_id, collection_id=collection_id)
        parent_id = current.id
    assert current is not None
    return current


def folder_counts(db: Session, folder: Folder) -> tuple[int, int]:
    documents = db.scalar(select(func.count()).select_from(Document).where(Document.folder_id == folder.id).where(Document.deleted_at.is_(None))) or 0
    records = db.scalar(select(func.count()).select_from(Record).where(Record.folder_id == folder.id).where(Record.deleted_at.is_(None))) or 0
    return int(documents), int(records)


def soft_delete_document(db: Session, document: Document, actor: str = "admin") -> None:
    document.deleted_at = datetime.now(timezone.utc)
    document.deleted_by = actor
    record_event(db, document, "document_deleted", "Document soft-deleted", actor=actor, source="manual")


def restore_document(db: Session, document: Document, actor: str = "admin") -> None:
    document.deleted_at = None
    document.deleted_by = None
    record_event(db, document, "document_restored", "Document restored", actor=actor, source="manual")


def soft_delete_record(db: Session, record: Record, actor: str = "admin") -> None:
    record.deleted_at = datetime.now(timezone.utc)
    record.deleted_by = actor
    for document in record.documents:
        soft_delete_document(db, document, actor=actor)


def restore_record(db: Session, record: Record, actor: str = "admin") -> None:
    record.deleted_at = None
    record.deleted_by = None
    for document in record.documents:
        restore_document(db, document, actor=actor)


def purge_document_storage(document: Document) -> None:
    storage = LocalStorage()
    for raw_path in [document.storage_path, document.thumbnail_path]:
        _unlink_storage_path(storage, raw_path)
    for page in document.pages:
        _unlink_storage_path(storage, page.rendered_image_path)


def auto_folder_path_for_document(document: Document) -> str:
    date_value = document.extracted_date or ""
    year = ""
    month = ""
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_value)
    if match:
        _, month, year = match.groups()
    else:
        created = document.created_at
        year = f"{created.year:04d}" if created else "unknown"
        month = f"{created.month:02d}" if created else "00"
    if document.collection_name == "Eingangsrechnung":
        sender = sanitize_folder_segment(document.extracted_sender or "Unsorted")
        return f"Eingangsrechnung/{sender}/{year}"
    if document.collection_name == "Ausgangsrechnung":
        return f"Ausgangsrechnung/{year}/{month}"
    if document.collection_name == "Belege":
        return f"Belege/{year}/{month}"
    return f"{sanitize_folder_segment(document.collection_name)}/{year}/{month}"


def _recompute_descendants(db: Session, folder: Folder) -> None:
    recompute_folder_path(db, folder)
    for child in folder.children:
        _recompute_descendants(db, child)


def _unlink_storage_path(storage: LocalStorage, raw_path: str | None) -> None:
    if not raw_path:
        return
    try:
        path = storage.resolve(raw_path)
    except Exception:  # noqa: BLE001
        path = Path(raw_path)
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        return
