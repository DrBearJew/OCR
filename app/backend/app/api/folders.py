from __future__ import annotations

from datetime import datetime, timezone
import base64
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import Collection, Document, Folder, Record
from app.schemas import DocumentRead, FolderContentsItem, FolderContentsPage, FolderMovePayload, FolderRead, FolderWrite, RecordRead
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


@router.get("/contents", response_model=FolderContentsPage)
def folder_contents(
    kind: str = "records",
    scope: str = "all",
    folder_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db),
) -> FolderContentsPage:
    if kind not in {"records", "documents"}:
        raise HTTPException(status_code=422, detail="kind must be records or documents")
    if scope not in {"all", "direct", "subtree", "unfiled"}:
        raise HTTPException(status_code=422, detail="scope must be all, direct, subtree, or unfiled")
    if scope in {"direct", "subtree"} and folder_id is None:
        raise HTTPException(status_code=422, detail="folder_id is required for direct or subtree scope")
    if folder_id is not None and db.get(Folder, folder_id) is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    normalized_limit = max(1, min(limit, 200))
    if kind == "records":
        items, total, next_cursor = _folder_record_contents(db, scope, folder_id, q, normalized_limit, cursor)
    else:
        items, total, next_cursor = _folder_document_contents(db, scope, folder_id, q, normalized_limit, cursor)
    return FolderContentsPage(
        kind=kind,
        scope=scope,
        folder_id=folder_id,
        limit=normalized_limit,
        next_cursor=next_cursor,
        total_estimate=total,
        items=items,
    )


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


def _folder_record_contents(
    db: Session,
    scope: str,
    folder_id: uuid.UUID | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[FolderContentsItem], int, str | None]:
    stmt = (
        select(Record, Collection.name, Folder.path)
        .join(Collection, Record.collection_id == Collection.id)
        .outerjoin(Folder, Record.folder_id == Folder.id)
        .where(Record.deleted_at.is_(None))
    )
    stmt = _apply_folder_scope(stmt, Record.folder_id, scope, folder_id, db)
    stmt = _apply_record_query(stmt, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = _apply_cursor(stmt, Record, cursor)
    stmt = stmt.order_by(Record.updated_at.desc(), Record.id.desc()).limit(limit + 1)
    rows = db.execute(stmt).all()
    page_rows = rows[:limit]
    items = [
        FolderContentsItem(
            kind="record",
            id=record.id,
            folder_id=record.folder_id,
            folder_path=folder_path,
            collection_id=record.collection_id,
            collection_name=collection_name,
            title=record.title,
            subtitle=f"{record.document_count} document{'s' if record.document_count != 1 else ''}",
            status=record.status.value,
            document_count=record.document_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record, collection_name, folder_path in page_rows
    ]
    next_cursor = _encode_cursor(page_rows[-1][0]) if len(rows) > limit and page_rows else None
    return items, total, next_cursor


def _folder_document_contents(
    db: Session,
    scope: str,
    folder_id: uuid.UUID | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[FolderContentsItem], int, str | None]:
    stmt = (
        select(Document, Folder.path, Record.collection_id)
        .outerjoin(Folder, Document.folder_id == Folder.id)
        .outerjoin(Record, Document.record_id == Record.id)
        .where(Document.deleted_at.is_(None))
    )
    stmt = _apply_folder_scope(stmt, Document.folder_id, scope, folder_id, db)
    stmt = _apply_document_query(stmt, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = _apply_cursor(stmt, Document, cursor)
    stmt = stmt.order_by(Document.updated_at.desc(), Document.id.desc()).limit(limit + 1)
    rows = db.execute(stmt).all()
    page_rows = rows[:limit]
    items = [
        FolderContentsItem(
            kind="document",
            id=document.id,
            record_id=document.record_id,
            folder_id=document.folder_id,
            folder_path=folder_path,
            collection_id=collection_id,
            collection_name=document.collection_name,
            title=document.manual_title_override or document.extracted_title or document.original_filename,
            subtitle=document.original_filename,
            status=document.processing_state.value,
            review_state=document.review_state.value,
            original_filename=document.original_filename,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        for document, folder_path, collection_id in page_rows
    ]
    next_cursor = _encode_cursor(page_rows[-1][0]) if len(rows) > limit and page_rows else None
    return items, total, next_cursor


def _apply_folder_scope(stmt, folder_column, scope: str, folder_id: uuid.UUID | None, db: Session):
    if scope == "all":
        return stmt
    if scope == "unfiled":
        return stmt.where(folder_column.is_(None))
    if scope == "direct":
        return stmt.where(folder_column == folder_id)
    folder_ids = _subtree_folder_ids(db, folder_id)
    return stmt.where(folder_column.in_(folder_ids))


def _subtree_folder_ids(db: Session, folder_id: uuid.UUID | None) -> list[uuid.UUID]:
    if folder_id is None:
        return []
    folder = db.get(Folder, folder_id)
    if folder is None:
        return []
    prefix = f"{folder.path}/%"
    return list(db.scalars(select(Folder.id).where(Folder.deleted_at.is_(None)).where(or_(Folder.id == folder_id, Folder.path.like(prefix)))).all())


def _apply_record_query(stmt, q: str | None):
    needle = (q or "").strip().lower()
    if not needle:
        return stmt
    like = f"%{needle}%"
    return stmt.where(or_(
        func.lower(func.coalesce(Record.title, "")).like(like),
        func.lower(func.coalesce(Collection.name, "")).like(like),
        func.lower(func.coalesce(Folder.path, "")).like(like),
    ))


def _apply_document_query(stmt, q: str | None):
    needle = (q or "").strip().lower()
    if not needle:
        return stmt
    like = f"%{needle}%"
    return stmt.where(or_(
        func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, Document.original_filename, "")).like(like),
        func.lower(func.coalesce(Document.original_filename, "")).like(like),
        func.lower(func.coalesce(Document.collection_name, "")).like(like),
        func.lower(func.coalesce(Folder.path, "")).like(like),
    ))


def _apply_cursor(stmt, model, cursor: str | None):
    decoded = _decode_cursor(cursor)
    if decoded is None:
        return stmt
    updated_at, row_id = decoded
    return stmt.where(or_(model.updated_at < updated_at, and_(model.updated_at == updated_at, model.id < row_id)))


def _encode_cursor(row: Record | Document) -> str:
    payload = {"updated_at": row.updated_at.isoformat(), "id": str(row.id)}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        row_id = uuid.UUID(str(payload["id"]))
        return updated_at, row_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc
