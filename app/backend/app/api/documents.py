from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import Collection, CustomFieldDefinition, Document, DocumentCustomFieldValue, DocumentEvent, DocumentPage, Folder
from app.models import DocumentState, OCRMode, ReviewState, StageState, Tag
from app.schemas import (
    AdminActionResult,
    DocumentBulkAction,
    DocumentCustomFieldValueRead,
    DocumentCustomFieldValueWrite,
    DocumentEventRead,
    DocumentPageRead,
    DocumentPatch,
    DocumentRead,
    OCRSettingsPatch,
)
from app.services.collections import create_record_for_upload, update_record_status, upsert_custom_field_value
from app.services.diagnostics import extraction_preview, document_completion_diagnostics
from app.services.events import record_event
from app.services.ocr_pipeline import resolve_ocr_config
from app.services.folders import purge_document_storage, restore_document, soft_delete_document
from app.services.processing import queue_full_process, queue_ocr, reserve_processing_task
from app.services.storage import LocalStorage
from app.workers.tasks import extract_metadata_task, ocr_document_task, process_document_task, publish_document_task


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents(
    batch_id: uuid.UUID | None = None,
    record_id: uuid.UUID | None = None,
    collection_name: str | None = None,
    state: DocumentState | None = None,
    review_state: ReviewState | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    filename: str | None = None,
    title: str | None = None,
    correspondent_id: uuid.UUID | None = None,
    document_type_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
    storage_path_id: uuid.UUID | None = None,
    folder_id: uuid.UUID | None = None,
    ocr_mode: OCRMode | None = None,
    include_deleted: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> list[dict]:
    stmt = select(Document).order_by(Document.created_at.desc())
    if not include_deleted:
        stmt = stmt.where(Document.deleted_at.is_(None))
    if batch_id:
        stmt = stmt.where(Document.batch_id == batch_id)
    if record_id:
        stmt = stmt.where(Document.record_id == record_id)
    if collection_name:
        stmt = stmt.where(Document.collection_name == collection_name)
    if state:
        stmt = stmt.where(Document.processing_state == state)
    if review_state:
        stmt = stmt.where(Document.review_state == review_state)
    if date_from:
        stmt = stmt.where(func.date(Document.created_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(Document.created_at) <= date_to)
    if filename:
        stmt = stmt.where(func.lower(Document.original_filename).like(f"%{filename.lower()}%"))
    if title:
        stmt = stmt.where(func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")).like(f"%{title.lower()}%"))
    if correspondent_id:
        stmt = stmt.where(Document.correspondent_id == correspondent_id)
    if document_type_id:
        stmt = stmt.where(Document.document_type_id == document_type_id)
    if storage_path_id:
        stmt = stmt.where(Document.storage_path_id == storage_path_id)
    if folder_id:
        stmt = stmt.where(Document.folder_id == folder_id)
    if ocr_mode:
        stmt = stmt.where(Document.ocr_mode == ocr_mode)
    if tag_id:
        stmt = stmt.join(Document.tags).where(Tag.id == tag_id)
    return [_document_summary(row) for row in db.scalars(stmt.limit(min(limit, 500))).all()]


@router.get("/duplicates")
def duplicate_documents(
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> list[dict]:
    stmt = (
        select(Document)
        .where(Document.duplicate_of_document_id.is_not(None))
        .where(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    return [_document_summary(row) for row in db.scalars(stmt).all()]


@router.post("/bulk")
def bulk_documents(
    payload: DocumentBulkAction,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    documents = db.scalars(select(Document).where(Document.id.in_(payload.document_ids))).all()
    if not documents:
        return {"ok": True, "updated": 0, "queued": 0, "skipped": len(payload.document_ids), "details": {}}
    updated = 0
    queued = 0
    skipped = 0
    enqueue_ocr_after_commit: list[tuple[str, str]] = []
    enqueue_metadata_after_commit: list[tuple[str, bool, str]] = []

    if payload.action == "export":
        return {
            "ok": True,
            "updated": 0,
            "queued": 0,
            "skipped": 0,
            "documents": [DocumentRead.model_validate(document).model_dump(mode="json") for document in documents],
        }

    if payload.action == "set_tag":
        if payload.tag_id is None:
            raise HTTPException(status_code=400, detail="tag_id is required")
        tag = db.get(Tag, payload.tag_id)
        if tag is None:
            raise HTTPException(status_code=404, detail="Tag not found")
    else:
        tag = None

    if payload.action == "move_collection":
        collection = db.get(Collection, payload.collection_id) if payload.collection_id else None
        if collection is None and payload.collection_name:
            collection = db.scalars(select(Collection).where(Collection.name == payload.collection_name)).first()
        if collection is None:
            raise HTTPException(status_code=404, detail="Target collection not found")

    for document in documents:
        if payload.action == "retry":
            if queue_ocr(db, document, force=payload.force):
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="ocr", force=payload.force)
                queued += 1
                enqueue_ocr_after_commit.append((str(document.id), task_id))
            else:
                skipped += 1
        elif payload.action == "reextract":
            if document.ocr_state not in {StageState.done, StageState.skipped}:
                skipped += 1
                record_event(db, document, "bulk_reextract_skipped", "Bulk reextract skipped because OCR is not done", actor="admin", source="manual")
                continue
            document.processing_state = DocumentState.ocr_done
            document.final_state = DocumentState.ocr_done
            document.metadata_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata", force=payload.force)
            record_event(db, document, "bulk_reextract", "Bulk metadata reextract requested", actor="admin", source="manual", metadata={"force": payload.force})
            enqueue_metadata_after_commit.append((str(document.id), payload.force, task_id))
            queued += 1
        elif payload.action == "set_review_state":
            if payload.review_state is None:
                raise HTTPException(status_code=400, detail="review_state is required")
            old_value = {"review_state": document.review_state.value, "review_reason": document.review_reason}
            document.review_state = payload.review_state
            document.review_reason = payload.review_reason
            if payload.review_state == ReviewState.reviewed:
                document.reviewed_by = "admin"
                document.reviewed_at = datetime.now(timezone.utc)
            record_event(db, document, "review_state_updated", "Review state updated", actor="admin", source="manual", old_value=old_value, new_value={"review_state": payload.review_state.value, "review_reason": payload.review_reason})
            update_record_status(db, document.record_id)
            updated += 1
        elif payload.action == "set_tag":
            if tag and tag not in document.tags:
                document.tags.append(tag)
                record_event(db, document, "tag_added", "Tag added by bulk action", actor="admin", source="manual", new_value={"tag_id": str(tag.id), "tag": tag.name})
                updated += 1
            else:
                skipped += 1
        elif payload.action == "move_collection":
            collection = db.get(Collection, payload.collection_id) if payload.collection_id else db.scalars(select(Collection).where(Collection.name == payload.collection_name)).first()
            if collection is None:
                skipped += 1
                continue
            old_value = {"collection_name": document.collection_name, "record_id": str(document.record_id) if document.record_id else None}
            record = create_record_for_upload(db, collection, document.manual_title_override or document.extracted_title or document.original_filename)
            document.collection_name = collection.name
            document.record_id = record.id
            record_event(db, document, "collection_moved", "Document moved to collection", actor="admin", source="manual", old_value=old_value, new_value={"collection_name": collection.name, "record_id": str(record.id)})
            update_record_status(db, record.id)
            updated += 1
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported bulk action: {payload.action}")

    db.commit()
    for document_id, task_id in enqueue_ocr_after_commit:
        publish_document_task(db, document_id, ocr_document_task, args=[document_id], task_id=task_id, queue="ocr", stage="ocr")
    for document_id, force, task_id in enqueue_metadata_after_commit:
        publish_document_task(db, document_id, extract_metadata_task, args=[document_id], kwargs={"force": force}, task_id=task_id, queue="metadata", stage="metadata")
    return AdminActionResult(ok=True, updated=updated, queued=queued, skipped=skipped).model_dump()


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentRead.model_validate(document)


@router.patch("/{document_id}", response_model=DocumentRead)
def patch_document(
    document_id: uuid.UUID,
    payload: DocumentPatch,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    updates = payload.model_dump(exclude_unset=True)
    if "folder_id" in updates and updates["folder_id"] is not None:
        folder = db.get(Folder, updates["folder_id"])
        if folder is None or folder.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Folder not found")
        collection_id = document.record.collection_id if document.record else None
        if folder.collection_id is not None and collection_id is not None and folder.collection_id != collection_id:
            raise HTTPException(status_code=400, detail="Folder belongs to a different collection")
    old_value = {key: getattr(document, key) for key in updates}
    for key, value in updates.items():
        setattr(document, key, value)
    _mark_manual_sources(document, updates)
    if updates.get("review_state") == ReviewState.reviewed:
        document.reviewed_by = "admin"
        document.reviewed_at = datetime.now(timezone.utc)
    if "review_state" in updates:
        update_record_status(db, document.record_id)
    record_event(
        db,
        document,
        "manual_edit",
        "Manual document metadata edit",
        actor="admin",
        source="manual",
        old_value=old_value,
        new_value=updates,
    )
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/retry", response_model=DocumentRead)
def retry_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    task_id = str(uuid.uuid4())
    queue_ocr(db, document, force=True)
    reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
    db.commit()
    publish_document_task(db, document.id, ocr_document_task, args=[str(document.id)], task_id=task_id, queue="ocr", stage="ocr")
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/process", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def process_document(
    document_id: uuid.UUID,
    force: bool = False,
    qwen_enabled: bool | None = None,
    overwrite_manual_values: bool | None = None,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    options = dict(document.processing_options_json or {})
    if qwen_enabled is not None:
        options["qwen_enabled"] = qwen_enabled
        options["qwen_enrichment_enabled"] = qwen_enabled
    if overwrite_manual_values is not None:
        options["overwrite_manual_values"] = overwrite_manual_values
    document.processing_options_json = options
    task_id = str(uuid.uuid4())
    if not queue_full_process(db, document, force=force):
        db.commit()
        db.refresh(document)
        return DocumentRead.model_validate(document)
    reserve_processing_task(document, task_id=task_id, stage="process", force=force)
    db.commit()
    publish_document_task(db, document.id, process_document_task, args=[str(document.id)], kwargs={"force": force}, task_id=task_id, queue="ocr", stage="process")
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.get("/{document_id}/diagnostics")
def document_diagnostics(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document_completion_diagnostics(document)


@router.post("/{document_id}/extraction-preview")
def preview_document_extraction(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return extraction_preview(document)


@router.post("/{document_id}/extraction-preview/apply", response_model=DocumentRead)
def apply_document_extraction_preview(
    document_id: uuid.UUID,
    force: bool = False,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    preview = extraction_preview(document)
    locks = document.field_locks_json or {}
    sources = dict(document.metadata_sources_json or {})
    field_map = {
        "title": "extracted_title",
        "sender": "extracted_sender",
        "recipient": "extracted_recipient",
        "invoice_number": "extracted_invoice_number",
        "date": "extracted_date",
        "amount": "extracted_amount",
        "payment_method": "extracted_payment_method",
    }
    applied: dict[str, dict] = {}
    for field, value in preview["proposed"].items():
        if not force and (document.metadata_locked or locks.get(field)):
            continue
        current_source = sources.get(field) if isinstance(sources.get(field), dict) else {}
        if not force and current_source.get("source") == "manual":
            continue
        attr = field_map[field]
        old = getattr(document, attr)
        setattr(document, attr, value)
        sources[field] = {"source": "deterministic", "confidence": 90, "evidence": "dry-run preview applied"}
        applied[field] = {"old": old, "new": value}
    document.metadata_sources_json = sources
    document.metadata_json = {
        **(document.metadata_json or {}),
        "last_extraction_preview": preview,
    }
    record_event(
        db,
        document,
        "extraction_preview_applied",
        "Dry-run extraction preview applied",
        old_value=preview["current"],
        new_value=applied,
        actor="admin",
        source="manual",
        metadata={"force": force},
    )
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.patch("/{document_id}/ocr-settings", response_model=DocumentRead)
def update_ocr_settings(
    document_id: uuid.UUID,
    payload: OCRSettingsPatch,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.ocr_mode is not None:
        document.ocr_mode = payload.ocr_mode
    document.ocr_config_json = {**(document.ocr_config_json or {}), **payload.ocr_config_json}
    record_event(db, document, "ocr_settings_updated", "OCR pipeline settings updated", actor="admin", source="manual", new_value={"ocr_mode": str(document.ocr_mode), "ocr_config_json": document.ocr_config_json})
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/ocr", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def run_document_ocr(
    document_id: uuid.UUID,
    ocr_mode: str | None = None,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if ocr_mode:
        try:
            document.ocr_mode = OCRMode(ocr_mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid OCR mode") from exc
    task_id = str(uuid.uuid4())
    queue_ocr(db, document, force=True)
    reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
    db.commit()
    publish_document_task(db, document.id, ocr_document_task, args=[str(document.id)], task_id=task_id, queue="ocr", stage="ocr")
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.get("/{document_id}/pipeline")
def document_pipeline(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> dict:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": str(document.id),
        "effective_ocr_config": resolve_ocr_config(document).as_dict(),
        "prompt_trace": document.prompt_trace_json,
        "model_trace": document.model_trace_json,
        "events": [
            {"event_type": event.event_type, "message": event.message, "created_at": event.created_at}
            for event in document.events
            if "hook" in event.event_type or event.event_type.startswith("ocr")
        ],
    }


@router.post("/{document_id}/reextract", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def reextract_document(
    document_id: uuid.UUID,
    force: bool = False,
    qwen_enabled: bool | None = None,
    overwrite_manual_values: bool | None = None,
    skip_metadata: bool | None = None,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    existing = db.get(Document, document_id)
    if existing is None or existing.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if existing.ocr_state not in {StageState.done, StageState.skipped}:
        raise HTTPException(status_code=409, detail="OCR must finish before metadata can be re-extracted")
    existing.processing_state = DocumentState.ocr_done
    existing.final_state = DocumentState.ocr_done
    existing.metadata_state = StageState.pending
    options = dict(existing.processing_options_json or {})
    if qwen_enabled is not None:
        options["qwen_enabled"] = qwen_enabled
        options["qwen_enrichment_enabled"] = qwen_enabled
    if overwrite_manual_values is not None:
        options["overwrite_manual_values"] = overwrite_manual_values
    if skip_metadata is not None:
        options["skip_metadata"] = skip_metadata
    existing.processing_options_json = options
    task_id = str(uuid.uuid4())
    reserve_processing_task(existing, task_id=task_id, stage="metadata", force=force)
    record_event(db, existing, "manual_reextract", "Manual metadata re-extract requested", actor="admin", source="manual", metadata={"force": force})
    db.commit()
    publish_document_task(db, existing.id, extract_metadata_task, args=[str(existing.id)], kwargs={"force": force}, task_id=task_id, queue="metadata", stage="metadata")
    db.refresh(existing)
    return DocumentRead.model_validate(existing)


@router.post("/{document_id}/reindex", response_model=DocumentRead)
def reindex_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    document.metadata_json = {**(document.metadata_json or {}), "search_indexed": True}
    record_event(db, document, "search_indexed", "Search index marker refreshed", actor="admin", source="manual")
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", response_model=DocumentRead)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    soft_delete_document(db, document)
    update_record_status(db, document.record_id)
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/restore", response_model=DocumentRead)
def restore_deleted_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    restore_document(db, document)
    update_record_status(db, document.record_id)
    db.commit()
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.post("/{document_id}/purge")
def purge_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> AdminActionResult:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    record_id = document.record_id
    purge_document_storage(document)
    db.delete(document)
    db.commit()
    if record_id:
        update_record_status(db, record_id)
        db.commit()
    return AdminActionResult(ok=True, updated=1)


def _mark_manual_sources(document: Document, updates: dict) -> None:
    source_fields = {
        "manual_title_override": "title",
        "extracted_title": "title",
        "extracted_sender": "sender",
        "extracted_recipient": "recipient",
        "extracted_invoice_number": "invoice_number",
        "extracted_date": "date",
        "extracted_amount": "amount",
        "extracted_payment_method": "payment_method",
    }
    sources = dict(document.metadata_sources_json or {})
    for attr, source_key in source_fields.items():
        if attr in updates and updates[attr] not in {None, ""}:
            sources[source_key] = {"source": "manual", "confidence": 100}
    if sources:
        document.metadata_sources_json = sources


def _document_summary(document: Document) -> dict:
    data = DocumentRead.model_validate(document).model_dump(mode="json")
    text = document.ocr_text or ""
    data["ocr_text"] = None
    data["ocr_snippet"] = " ".join(text.split())[:500]
    data["raw_ocr_json"] = {}
    data["qwen_response_text"] = None
    data["llm_raw_response"] = {}
    return data


@router.get("/{document_id}/events", response_model=list[DocumentEventRead])
def document_events(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> list[DocumentEventRead]:
    stmt = (
        select(DocumentEvent)
        .where(DocumentEvent.document_id == document_id)
        .order_by(DocumentEvent.created_at.asc())
    )
    return [DocumentEventRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.get("/{document_id}/pages", response_model=list[DocumentPageRead])
def document_pages(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> list[DocumentPageRead]:
    stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
    )
    return [DocumentPageRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.get("/{document_id}/custom-fields", response_model=list[DocumentCustomFieldValueRead])
def document_custom_fields(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> list[DocumentCustomFieldValueRead]:
    stmt = (
        select(DocumentCustomFieldValue)
        .where(DocumentCustomFieldValue.document_id == document_id)
        .order_by(DocumentCustomFieldValue.updated_at.desc())
    )
    return [DocumentCustomFieldValueRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.put("/{document_id}/custom-fields", response_model=DocumentCustomFieldValueRead)
def upsert_document_custom_field(
    document_id: uuid.UUID,
    payload: DocumentCustomFieldValueWrite,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> DocumentCustomFieldValueRead:
    document = db.get(Document, document_id)
    field = db.get(CustomFieldDefinition, payload.custom_field_definition_id)
    if document is None or field is None:
        raise HTTPException(status_code=404, detail="Document or field not found")
    if document.record and document.record.collection_id != field.collection_id:
        raise HTTPException(status_code=400, detail="Field belongs to a different collection")
    value = upsert_custom_field_value(
        db,
        document,
        field,
        payload.raw_value,
        source=payload.source,
        confidence=payload.confidence,
        force=payload.force,
    )
    if payload.locked is not None:
        value.locked = payload.locked
    db.commit()
    db.refresh(value)
    return DocumentCustomFieldValueRead.model_validate(value)


@router.get("/{document_id}/thumbnail")
def thumbnail_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> FileResponse:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None or not document.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    path = LocalStorage().resolve(document.thumbnail_path)
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> FileResponse:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = LocalStorage().resolve(document.storage_path)
    return FileResponse(path, media_type=document.mime_type, filename=document.original_filename)


@router.get("/{document_id}/preview")
def preview_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> FileResponse:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = LocalStorage().resolve(document.storage_path)
    return FileResponse(path, media_type=document.mime_type or "application/octet-stream")
