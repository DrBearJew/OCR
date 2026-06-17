from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload, with_loader_criteria

from app.auth import require_admin
from app.db import get_db
from app.models import Collection, Document, Folder, Record
from app.schemas import AdminActionResult, RecordPatch, RecordRead
from app.services.collections import seed_default_collections, update_record_status
from app.services.events import record_event
from app.services.folders import purge_document_storage, restore_record, soft_delete_record
from app.services.processing import queue_full_process, reserve_processing_task
from app.services.shared_titles import apply_shared_title_base
from app.workers.tasks import process_document_task, publish_document_task


router = APIRouter(prefix="/api/records", tags=["records"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[RecordRead])
def list_records(
    collection_id: uuid.UUID | None = None,
    collection_slug: str | None = None,
    collection: str | None = None,
    folder_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
) -> list[RecordRead]:
    seed_default_collections(db)
    stmt = (
        select(Record)
        .options(selectinload(Record.collection), selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
        .order_by(Record.updated_at.desc())
    )
    if not include_deleted:
        stmt = stmt.where(Record.deleted_at.is_(None))
    if collection_id:
        stmt = stmt.where(Record.collection_id == collection_id)
    if collection_slug:
        stmt = stmt.join(Collection).where(Collection.slug == collection_slug)
    if collection:
        needle_collection = collection.strip().lower()
        stmt = stmt.where(Record.collection.has(or_(
            func.lower(Collection.name).like(f"%{needle_collection}%"),
            func.lower(Collection.slug).like(f"%{needle_collection}%"),
        )))
    if folder_id:
        stmt = stmt.where(Record.folder_id == folder_id)
    if status_filter:
        stmt = stmt.where(Record.status == status_filter)
    rows = db.scalars(stmt).all()
    return [RecordRead.model_validate(row) for row in rows]


@router.get("/page")
def list_records_page(
    collection_id: uuid.UUID | None = None,
    collection_slug: str | None = None,
    collection: str | None = None,
    folder_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    q: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    seed_default_collections(db)
    normalized_limit = max(1, min(limit, 200))
    base_stmt = _record_list_stmt(collection_id, collection_slug, collection, folder_id, status_filter, q, include_deleted)
    total = db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    stmt = _apply_record_cursor(base_stmt, cursor)
    stmt = stmt.options(selectinload(Record.collection), selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
    rows = db.scalars(stmt.order_by(Record.updated_at.desc(), Record.id.desc()).limit(normalized_limit + 1)).all()
    page_rows = rows[:normalized_limit]
    return {
        "items": [RecordRead.model_validate(row).model_dump(mode="json") for row in page_rows],
        "limit": normalized_limit,
        "next_cursor": _encode_record_cursor(page_rows[-1]) if len(rows) > normalized_limit and page_rows else None,
        "total_estimate": int(total),
    }


def _record_list_stmt(
    collection_id: uuid.UUID | None,
    collection_slug: str | None,
    collection: str | None,
    folder_id: uuid.UUID | None,
    status_filter: str | None,
    q: str | None,
    include_deleted: bool,
):
    stmt = select(Record)
    if not include_deleted:
        stmt = stmt.where(Record.deleted_at.is_(None))
    if collection_id:
        stmt = stmt.where(Record.collection_id == collection_id)
    if collection_slug:
        stmt = stmt.join(Collection).where(Collection.slug == collection_slug)
    if collection:
        needle_collection = collection.strip().lower()
        stmt = stmt.where(Record.collection.has(or_(
            func.lower(Collection.name).like(f"%{needle_collection}%"),
            func.lower(Collection.slug).like(f"%{needle_collection}%"),
        )))
    if folder_id:
        stmt = stmt.where(Record.folder_id == folder_id)
    if status_filter:
        stmt = stmt.where(Record.status == status_filter)
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(or_(
            func.lower(func.coalesce(Record.title, "")).like(like),
            Record.collection.has(func.lower(Collection.name).like(like)),
            Record.documents.any(and_(
                Document.deleted_at.is_(None),
                or_(
                    func.lower(Document.original_filename).like(like),
                    func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")).like(like),
                ),
            )),
        ))
    return stmt


def _apply_record_cursor(stmt, cursor: str | None):
    decoded = _decode_record_cursor(cursor)
    if decoded is None:
        return stmt
    updated_at, row_id = decoded
    return stmt.where(or_(Record.updated_at < updated_at, and_(Record.updated_at == updated_at, Record.id < row_id)))


def _encode_record_cursor(record: Record) -> str:
    payload = {"updated_at": record.updated_at.isoformat(), "id": str(record.id)}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


def _decode_record_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        row_id = uuid.UUID(str(payload["id"]))
        return updated_at, row_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


@router.get("/{record_id}", response_model=RecordRead)
def get_record(record_id: uuid.UUID, db: Session = Depends(get_db)) -> RecordRead:
    stmt = (
        select(Record)
        .where(Record.id == record_id)
        .where(Record.deleted_at.is_(None))
        .options(selectinload(Record.collection), selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
    )
    record = db.scalars(stmt).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return RecordRead.model_validate(record)


@router.patch("/{record_id}", response_model=RecordRead)
def patch_record(record_id: uuid.UUID, payload: RecordPatch, db: Session = Depends(get_db)) -> RecordRead:
    record = db.get(Record, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    updates = payload.model_dump(exclude_unset=True)
    if "folder_id" in updates and updates["folder_id"] is not None:
        folder = db.get(Folder, updates["folder_id"])
        if folder is None or folder.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Folder not found")
        if folder.collection_id is not None and folder.collection_id != record.collection_id:
            raise HTTPException(status_code=400, detail="Folder belongs to a different collection")
    for key, value in updates.items():
        if key == "shared_title_base" and value is not None:
            value = str(value).strip()[:255] or None
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return RecordRead.model_validate(record)


@router.post("/{record_id}/process-all", response_model=AdminActionResult, status_code=status.HTTP_202_ACCEPTED)
def process_record_documents(
    record_id: uuid.UUID,
    force: bool = False,
    qwen_enabled: bool | None = None,
    overwrite_manual_values: bool | None = None,
    db: Session = Depends(get_db),
) -> AdminActionResult:
    stmt = (
        select(Record)
        .where(Record.id == record_id)
        .where(Record.deleted_at.is_(None))
        .options(selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
    )
    record = db.scalars(stmt).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    queued = 0
    skipped = 0
    enqueue_after_commit: list[tuple[str, str]] = []
    for document in record.documents:
        if document.deleted_at is not None:
            skipped += 1
            continue
        options = dict(document.processing_options_json or {})
        if qwen_enabled is not None:
            options["qwen_enabled"] = qwen_enabled
            options["qwen_enrichment_enabled"] = qwen_enabled
        if overwrite_manual_values is not None:
            options["overwrite_manual_values"] = overwrite_manual_values
        document.processing_options_json = options
        if queue_full_process(db, document, force=force):
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="process", force=force)
            enqueue_after_commit.append((str(document.id), task_id))
            queued += 1
        else:
            skipped += 1
    db.commit()
    for document_id, task_id in enqueue_after_commit:
        publish_document_task(db, document_id, process_document_task, args=[document_id], kwargs={"force": force}, task_id=task_id, queue="ocr", stage="process")
    return AdminActionResult(ok=True, queued=queued, skipped=skipped, details={"record_id": str(record.id), "task": "process_documents"})


@router.delete("/{record_id}", response_model=RecordRead)
def delete_record(record_id: uuid.UUID, db: Session = Depends(get_db)) -> RecordRead:
    stmt = select(Record).where(Record.id == record_id).options(selectinload(Record.collection), selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
    record = db.scalars(stmt).first()
    if record is None or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Record not found")
    soft_delete_record(db, record)
    update_record_status(db, record.id)
    db.commit()
    db.refresh(record)
    return RecordRead.model_validate(record)


@router.post("/{record_id}/restore", response_model=RecordRead)
def restore_deleted_record(record_id: uuid.UUID, db: Session = Depends(get_db)) -> RecordRead:
    stmt = select(Record).where(Record.id == record_id).options(selectinload(Record.collection), selectinload(Record.documents))
    record = db.scalars(stmt).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    restore_record(db, record)
    update_record_status(db, record.id)
    db.commit()
    db.refresh(record)
    return RecordRead.model_validate(record)


@router.post("/{record_id}/purge", response_model=AdminActionResult)
def purge_record(record_id: uuid.UUID, db: Session = Depends(get_db)) -> AdminActionResult:
    stmt = select(Record).where(Record.id == record_id).options(selectinload(Record.documents))
    record = db.scalars(stmt).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    count = len(record.documents)
    for document in list(record.documents):
        purge_document_storage(document)
    db.delete(record)
    db.commit()
    return AdminActionResult(ok=True, updated=count + 1, details={"record_id": str(record_id)})


@router.post("/{record_id}/apply-shared-title", response_model=RecordRead)
def apply_record_shared_title(
    record_id: uuid.UUID,
    only_unlocked: bool = True,
    db: Session = Depends(get_db),
) -> RecordRead:
    stmt = (
        select(Record)
        .where(Record.id == record_id)
        .options(selectinload(Record.collection), selectinload(Record.documents), with_loader_criteria(Document, Document.deleted_at.is_(None)))
    )
    record = db.scalars(stmt).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    before = {document.id: document.extracted_title for document in record.documents}
    updated = apply_shared_title_base(record, record.documents, only_unlocked=only_unlocked)
    for document in record.documents:
        if before.get(document.id) == document.extracted_title:
            continue
        record_event(
            db,
            document,
            "shared_title_base_applied",
            "Shared record title base applied to unlocked document",
            old_value={"title": before.get(document.id)},
            new_value={"title": document.extracted_title},
            metadata={"record_id": str(record.id), "only_unlocked": only_unlocked},
        )
    update_record_status(db, record.id)
    db.commit()
    db.refresh(record)
    if updated:
        stmt = (
            select(Record)
            .where(Record.id == record_id)
            .options(selectinload(Record.collection), selectinload(Record.documents))
        )
        record = db.scalars(stmt).one()
    return RecordRead.model_validate(record)
