from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import Document, Folder, Record
from app.schemas import DocumentRead, FolderMovePayload, FolderRead, FolderWrite, RecordRead
from app.services.folders import create_folder, folder_counts, move_folder, rename_folder


router = APIRouter(prefix="/api/folders", tags=["folders"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[FolderRead])
def list_folders(
    parent_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
) -> list[FolderRead]:
    stmt = select(Folder).order_by(Folder.path.asc())
    if parent_id:
        stmt = stmt.where(Folder.parent_id == parent_id)
    if collection_id:
        stmt = stmt.where(Folder.collection_id == collection_id)
    if not include_deleted:
        stmt = stmt.where(Folder.deleted_at.is_(None))
    return [_folder_read(db, folder) for folder in db.scalars(stmt).all()]


@router.post("", response_model=FolderRead)
def create_folder_endpoint(payload: FolderWrite, db: Session = Depends(get_db)) -> FolderRead:
    folder = create_folder(db, payload.name, parent_id=payload.parent_id, collection_id=payload.collection_id)
    db.commit()
    db.refresh(folder)
    return _folder_read(db, folder)


@router.patch("/{folder_id}", response_model=FolderRead)
def update_folder(folder_id: uuid.UUID, payload: FolderWrite, db: Session = Depends(get_db)) -> FolderRead:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Folder not found")
    rename_folder(db, folder, payload.name)
    if payload.parent_id != folder.parent_id:
        try:
            move_folder(db, folder, payload.parent_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.collection_id is not None:
        folder.collection_id = payload.collection_id
    db.commit()
    db.refresh(folder)
    return _folder_read(db, folder)


@router.delete("/{folder_id}", response_model=FolderRead)
def delete_folder(folder_id: uuid.UUID, db: Session = Depends(get_db)) -> FolderRead:
    folder = db.get(Folder, folder_id)
    if folder is None or folder.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Folder not found")
    doc_count, record_count = _subtree_counts(db, folder)
    if doc_count or record_count:
        raise HTTPException(status_code=409, detail="Folder contains records or documents")
    _soft_delete_folder(folder)
    db.commit()
    db.refresh(folder)
    return _folder_read(db, folder)


@router.post("/{folder_id}/restore", response_model=FolderRead)
def restore_folder(folder_id: uuid.UUID, db: Session = Depends(get_db)) -> FolderRead:
    folder = db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    _restore_folder(folder)
    db.commit()
    db.refresh(folder)
    return _folder_read(db, folder)


@router.post("/move-document/{document_id}", response_model=DocumentRead)
def move_document_to_folder(document_id: uuid.UUID, payload: FolderMovePayload, db: Session = Depends(get_db)) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.folder_id:
        folder = db.get(Folder, payload.folder_id)
        if folder is None or folder.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Folder not found")
        if folder.collection_id is not None and document.record and folder.collection_id != document.record.collection_id:
            raise HTTPException(status_code=400, detail="Folder belongs to a different collection")
    document.folder_id = payload.folder_id
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/move-record/{record_id}", response_model=RecordRead)
def move_record_to_folder(record_id: uuid.UUID, payload: FolderMovePayload, db: Session = Depends(get_db)) -> RecordRead:
    record = db.get(Record, record_id)
    if record is None or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Record not found")
    if payload.folder_id:
        folder = db.get(Folder, payload.folder_id)
        if folder is None or folder.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Folder not found")
        if folder.collection_id is not None and folder.collection_id != record.collection_id:
            raise HTTPException(status_code=400, detail="Folder belongs to a different collection")
    record.folder_id = payload.folder_id
    db.commit()
    db.refresh(record)
    return RecordRead.model_validate(record)


def _folder_read(db: Session, folder: Folder) -> FolderRead:
    document_count, record_count = folder_counts(db, folder, recursive=True)
    return FolderRead(
        id=folder.id,
        parent_id=folder.parent_id,
        collection_id=folder.collection_id,
        name=folder.name,
        path=folder.path,
        document_count=document_count,
        record_count=record_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        deleted_at=folder.deleted_at,
    )


def _soft_delete_folder(folder: Folder) -> None:
    folder.deleted_at = datetime.now(timezone.utc)
    for child in folder.children:
        _soft_delete_folder(child)


def _restore_folder(folder: Folder) -> None:
    folder.deleted_at = None
    for child in folder.children:
        _restore_folder(child)


def _subtree_counts(db: Session, folder: Folder) -> tuple[int, int]:
    document_count, record_count = folder_counts(db, folder)
    for child in folder.children:
        child_docs, child_records = _subtree_counts(db, child)
        document_count += child_docs
        record_count += child_records
    return document_count, record_count
