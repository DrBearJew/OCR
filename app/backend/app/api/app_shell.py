from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_admin
from app.db import get_db
from app.models import (
    Collection,
    Document,
    DocumentEvent,
    DocumentState,
    IngestionJob,
    Record,
    ReviewState,
    SavedView,
    StageState,
)
from app.schemas import DocumentEventRead, DocumentRead, IngestionJobRead, RecordRead, SavedViewRead, SavedViewWrite
from app.services.collections import seed_default_collections, slugify
from app.services.diagnostics import document_completion_diagnostics
from app.services.integrations import check_celery_workers
from app.services.processing import is_stale


router = APIRouter(prefix="/api", tags=["app-shell"], dependencies=[Depends(require_admin)])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    seed_default_collections(db)
    live_docs = Document.deleted_at.is_(None)
    status_counts = {_enum_value(state): count for state, count in db.execute(select(Document.processing_state, func.count(Document.id)).where(live_docs).group_by(Document.processing_state)).all()}
    review_counts = {_enum_value(state): count for state, count in db.execute(select(Document.review_state, func.count(Document.id)).where(live_docs).group_by(Document.review_state)).all()}
    collection_counts = [
        {"collection": name, "documents": count}
        for name, count in db.execute(select(Document.collection_name, func.count(Document.id)).where(live_docs).group_by(Document.collection_name).order_by(Document.collection_name.asc())).all()
    ]
    recent_records = db.scalars(
        select(Record)
        .where(Record.deleted_at.is_(None))
        .options(selectinload(Record.collection), selectinload(Record.documents))
        .order_by(Record.updated_at.desc())
        .limit(8)
    ).all()
    failed_documents = db.scalars(
        select(Document)
        .where(Document.processing_state == DocumentState.failed)
        .where(live_docs)
        .order_by(Document.updated_at.desc())
        .limit(8)
    ).all()
    completed_documents = db.scalars(
        select(Document)
        .where(Document.processing_state == DocumentState.complete)
        .where(live_docs)
        .order_by(Document.completed_at.desc().nullslast(), Document.updated_at.desc())
        .limit(8)
    ).all()
    return {
        "status_counts": status_counts,
        "review_counts": review_counts,
        "collection_counts": collection_counts,
        "recent_records": [RecordRead.model_validate(row).model_dump(mode="json") for row in recent_records],
        "failed_documents": [_document_summary(row) for row in failed_documents],
        "completed_documents": [_document_summary(row) for row in completed_documents],
    }


@router.get("/activity")
def activity(
    document_id: uuid.UUID | None = None,
    record_id: uuid.UUID | None = None,
    event_type: str | None = None,
    source: str | None = None,
    actor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(DocumentEvent, Document).join(Document, Document.id == DocumentEvent.document_id).where(Document.deleted_at.is_(None))
    if document_id:
        stmt = stmt.where(DocumentEvent.document_id == document_id)
    if record_id:
        stmt = stmt.where(Document.record_id == record_id)
    if event_type:
        stmt = stmt.where(DocumentEvent.event_type == event_type)
    if source:
        stmt = stmt.where(DocumentEvent.source == source)
    if actor:
        stmt = stmt.where(DocumentEvent.actor == actor)
    if date_from:
        stmt = stmt.where(func.date(DocumentEvent.created_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(DocumentEvent.created_at) <= date_to)
    rows = db.execute(stmt.order_by(DocumentEvent.created_at.desc()).limit(min(limit, 500))).all()
    return [
        {
            **DocumentEventRead.model_validate(event).model_dump(mode="json"),
            "record_id": str(document.record_id) if document.record_id else None,
            "document_title": document.display_title,
            "original_filename": document.original_filename,
            "collection_name": document.collection_name,
        }
        for event, document in rows
    ]


@router.get("/processing")
def processing(db: Session = Depends(get_db)) -> dict:
    active_states = {
        DocumentState.uploaded,
        DocumentState.queued_for_ocr,
        DocumentState.ocr_processing,
        DocumentState.ocr_done,
        DocumentState.metadata_processing,
    }
    documents = db.scalars(select(Document).where(Document.processing_state.in_(active_states)).where(Document.deleted_at.is_(None)).order_by(Document.updated_at.desc()).limit(200)).all()
    jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.updated_at.desc()).limit(100)).all()
    queued_docs = [row for row in documents if row.processing_state == DocumentState.queued_for_ocr]
    oldest_queued = min((row.updated_at for row in queued_docs if row.updated_at is not None), default=None)
    worker_status = check_celery_workers()
    return {
        "documents": [_document_summary(row, include_diagnostics=True) for row in documents],
        "stuck_documents": [_document_summary(row, include_diagnostics=True) for row in documents if is_stale(row)],
        "ingestion_jobs": [IngestionJobRead.model_validate(row).model_dump(mode="json") for row in jobs],
        "worker_status": worker_status.as_dict(),
        "summary": {
            "queued": sum(1 for row in documents if row.processing_state == DocumentState.queued_for_ocr),
            "ocr_running": sum(1 for row in documents if row.ocr_state == StageState.processing),
            "metadata_running": sum(1 for row in documents if row.metadata_state == StageState.processing),
            "oldest_queued_at": oldest_queued.isoformat() if oldest_queued else None,
            "ocr_queue_length": (worker_status.metadata or {}).get("queues", {}).get("ocr"),
            "active_ocr_tasks": sum(
                1
                for tasks in (worker_status.metadata or {}).get("active_tasks", {}).values()
                for item in tasks
                if item.get("name") in {"app.workers.tasks.ocr_document_task", "app.workers.tasks.process_document_task"}
            ),
        },
    }


@router.get("/failed")
def failed_and_review(db: Session = Depends(get_db)) -> dict:
    failed_documents = db.scalars(
        select(Document)
        .where(Document.processing_state == DocumentState.failed)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.updated_at.desc())
        .limit(200)
    ).all()
    needs_review = db.scalars(
        select(Document)
        .where(or_(Document.review_state == ReviewState.needs_review, Document.duplicate_of_document_id.is_not(None)))
        .where(Document.deleted_at.is_(None))
        .order_by(Document.updated_at.desc())
        .limit(200)
    ).all()
    missing_required = db.scalars(
        select(Document)
        .where(Document.processing_state == DocumentState.complete)
        .where(Document.deleted_at.is_(None))
        .where(or_(Document.extracted_title.is_(None), Document.extracted_title == ""))
        .order_by(Document.updated_at.desc())
        .limit(200)
    ).all()
    return {
        "failed_documents": [_document_summary(row) for row in failed_documents],
        "needs_review_documents": [_document_summary(row) for row in needs_review],
        "missing_required_documents": [_document_summary(row) for row in missing_required],
    }


@router.get("/collection-summaries")
def collection_summaries(db: Session = Depends(get_db)) -> list[dict]:
    seed_default_collections(db)
    collections = db.scalars(select(Collection).order_by(Collection.name.asc())).all()
    rows: list[dict] = []
    for collection in collections:
        records = db.scalars(select(Record).where(Record.collection_id == collection.id).where(Record.deleted_at.is_(None))).all()
        document_count = db.scalar(select(func.count(Document.id)).where(Document.collection_name == collection.name).where(Document.deleted_at.is_(None))) or 0
        rows.append(
            {
                "collection": {
                    "id": str(collection.id),
                    "name": collection.name,
                    "slug": collection.slug,
                    "icon": collection.icon,
                    "color": collection.color,
                },
                "record_count": len(records),
                "document_count": document_count,
                "status_counts": _status_counts_for_collection(db, collection.name),
            }
        )
    return rows


@router.get("/collection-pages/{slug}")
def collection_page(slug: str, db: Session = Depends(get_db)) -> dict:
    collection = db.scalars(select(Collection).where(Collection.slug == slug)).first()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    record_count = db.scalar(select(func.count(Record.id)).where(Record.collection_id == collection.id).where(Record.deleted_at.is_(None))) or 0
    return {
        "collection": {
            "id": str(collection.id),
            "name": collection.name,
            "slug": collection.slug,
            "icon": collection.icon,
            "color": collection.color,
            "display_config": collection.display_config,
        },
        "records": [],
        "limit": 0,
        "next_cursor": None,
        "total_estimate": int(record_count),
        "status_counts": _status_counts_for_collection(db, collection.name),
    }


@router.get("/saved-views", response_model=list[SavedViewRead])
def list_saved_views(section: str | None = None, db: Session = Depends(get_db)) -> list[SavedViewRead]:
    stmt = select(SavedView).order_by(SavedView.section.asc(), SavedView.name.asc())
    if section:
        stmt = stmt.where(SavedView.section == section)
    return [SavedViewRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.post("/saved-views", response_model=SavedViewRead, status_code=status.HTTP_201_CREATED)
def create_saved_view(payload: SavedViewWrite, db: Session = Depends(get_db)) -> SavedViewRead:
    row = SavedView(
        name=payload.name,
        slug=payload.slug or slugify(f"{payload.section}-{payload.name}"),
        section=payload.section,
        filters_json=payload.filters_json,
        sort_json=payload.sort_json,
        display_json=payload.display_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SavedViewRead.model_validate(row)


@router.patch("/saved-views/{view_id}", response_model=SavedViewRead)
def update_saved_view(view_id: uuid.UUID, payload: SavedViewWrite, db: Session = Depends(get_db)) -> SavedViewRead:
    row = db.get(SavedView, view_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Saved view not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "slug" and not value:
            value = slugify(f"{payload.section}-{payload.name}")
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return SavedViewRead.model_validate(row)


@router.delete("/saved-views/{view_id}")
def delete_saved_view(view_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    row = db.get(SavedView, view_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Saved view not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


def _status_counts_for_collection(db: Session, collection_name: str) -> dict:
    return {
        _enum_value(state): count
        for state, count in db.execute(
            select(Document.processing_state, func.count(Document.id))
            .where(Document.collection_name == collection_name)
            .where(Document.deleted_at.is_(None))
            .group_by(Document.processing_state)
        ).all()
    }


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _document_summary(document: Document, *, include_diagnostics: bool = False) -> dict:
    data = DocumentRead.model_validate(document).model_dump(mode="json")
    text = document.ocr_text or ""
    data["ocr_text"] = None
    data["ocr_snippet"] = " ".join(text.split())[:500]
    data["raw_ocr_json"] = {}
    data["qwen_response_text"] = None
    data["llm_raw_response"] = {}
    if include_diagnostics:
        data["diagnostics"] = document_completion_diagnostics(document)
    return data
