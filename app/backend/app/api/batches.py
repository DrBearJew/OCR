from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_admin
from app.config import get_settings
from app.db import get_db
from app.models import Batch, Document, FieldValueSource, Folder
from app.schemas import BatchDetail, BatchRead
from app.services.document_assets import generate_thumbnail, inspect_page_count, virus_scan_placeholder
from app.services.events import record_event
from app.services.collections import create_record_for_upload, ensure_collection, update_record_status, upsert_custom_field_value
from app.services.folders import ensure_folder_path
from app.services.processing import mark_duplicate_document, queue_full_process, queue_ocr, reserve_processing_task, update_batch_status
from app.services.storage import LocalStorage
from app.workers.tasks import ocr_document_task, process_document_task, publish_document_task


router = APIRouter(prefix="/api/batches", tags=["batches"], dependencies=[Depends(require_admin)])


@router.post("/upload", response_model=BatchDetail, status_code=status.HTTP_201_CREATED)
async def upload_batch(
    collection_name: str | None = Form(None),
    label: str | None = Form(None),
    document_metadata_json: str | None = Form(None),
    processing_options_json: str | None = Form(None),
    record_metadata_json: str | None = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> BatchDetail:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    settings = get_settings()
    if len(files) > settings.max_upload_files_per_batch:
        raise HTTPException(status_code=413, detail=f"Too many files. Max files per batch is {settings.max_upload_files_per_batch}.")
    _validate_known_upload_sizes(files, settings)
    collection_name = (collection_name or "Dokumente").strip() or "Dokumente"
    document_metadata = _load_document_metadata(document_metadata_json, len(files))
    processing_options = _load_json_object(processing_options_json)
    record_metadata = _load_json_object(record_metadata_json)
    batch = Batch(collection_name=collection_name, label=label, document_count=len(files))
    db.add(batch)
    db.flush()
    collection = ensure_collection(db, collection_name)
    shared_title_base = str(record_metadata.get("shared_title_base") or "").strip()[:255]
    apply_shared_title = bool(record_metadata.get("apply_shared_title_to_documents"))
    record_title = label or (f"{shared_title_base} upload" if shared_title_base else f"{collection_name} upload")
    record = create_record_for_upload(db, collection, title=record_title)
    record.shared_title_base = shared_title_base or None
    record.apply_shared_title_to_documents = apply_shared_title
    folder = _folder_from_record_metadata(db, record_metadata, collection.id)
    if folder is not None:
        record.folder_id = folder.id
    if record_metadata:
        record.summary_metadata = record_metadata

    storage = LocalStorage()
    queued_document_ids: list[tuple[uuid.UUID, str]] = []
    process_document_ids: list[tuple[uuid.UUID, str]] = []
    stored_paths: list[str] = []
    total_size = 0
    try:
        for index, upload in enumerate(files):
            stored = await storage.save_upload(upload, batch.id)
            stored_paths.append(stored["path"])
            total_size += int(stored["size"])
            if total_size > settings.max_upload_batch_bytes:
                raise ValueError(f"Upload too large. Max file size is {settings.max_upload_file_size_mb} MB and max batch size is {settings.max_upload_batch_size_mb} MB.")
            virus_scan_placeholder(stored["path"])
            page_count = inspect_page_count(stored["path"], upload.content_type)
            metadata = document_metadata[index] if index < len(document_metadata) else {}
            document = Document(
                batch_id=batch.id,
                record_id=record.id,
                collection_name=collection_name,
                original_filename=upload.filename or "document",
                storage_path=stored["path"],
                mime_type=upload.content_type,
                file_size=stored["size"],
                sha256=stored["sha256"],
                page_count=page_count,
                processing_options_json=processing_options,
                ocr_config_json=_ocr_config_from_processing_options(processing_options),
                folder_id=record.folder_id,
            )
            db.add(document)
            db.flush()
            _apply_manual_upload_metadata(db, document, collection, metadata)
            document.thumbnail_path = generate_thumbnail(stored["path"], upload.content_type, document.id)
            record_event(db, document, "uploaded", "Document uploaded", metadata={"page_count": page_count})
            record_event(db, document, "stored", "Original file stored on local filesystem", metadata={"storage_path": stored["path"], "sha256": stored["sha256"], "size": stored["size"]})

            duplicate = db.scalars(
                select(Document)
                .where(Document.sha256 == stored["sha256"])
                .where(Document.deleted_at.is_(None))
                .where(Document.id != document.id)
                .order_by(Document.created_at.asc())
            ).first()
            if duplicate is not None:
                mark_duplicate_document(db, document, duplicate)
            elif processing_options.get("auto_process"):
                queue_full_process(db, document)
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="process")
                process_document_ids.append((document.id, task_id))
            elif processing_options.get("auto_ocr", True):
                queue_ocr(db, document)
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="ocr")
                queued_document_ids.append((document.id, task_id))
            else:
                record_event(db, document, "auto_ocr_disabled", "Document stored without automatic OCR", metadata={"processing_options": processing_options})
        update_batch_status(db, batch.id)
        update_record_status(db, record.id)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        for path in stored_paths:
            Path(path).unlink(missing_ok=True)
        if "Upload too large" in str(exc):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for document_id, task_id in queued_document_ids:
        publish_document_task(db, document_id, ocr_document_task, args=[str(document_id)], task_id=task_id, queue="ocr", stage="ocr")
    for document_id, task_id in process_document_ids:
        publish_document_task(db, document_id, process_document_task, args=[str(document_id)], task_id=task_id, queue="ocr", stage="process")

    stmt = select(Batch).where(Batch.id == batch.id).options(selectinload(Batch.documents))
    created = db.scalars(stmt).one()
    return BatchDetail.model_validate(created)


def _load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON form field: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="JSON form field must be an object")
    return parsed


def _validate_known_upload_sizes(files: list[UploadFile], settings) -> None:
    known_total = 0
    for upload in files:
        size = getattr(upload, "size", None)
        if size is None:
            continue
        known_total += int(size)
        if int(size) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"Upload too large. Max file size is {settings.max_upload_file_size_mb} MB and max batch size is {settings.max_upload_batch_size_mb} MB.")
    if known_total and known_total > settings.max_upload_batch_bytes:
        raise HTTPException(status_code=413, detail=f"Upload too large. Max file size is {settings.max_upload_file_size_mb} MB and max batch size is {settings.max_upload_batch_size_mb} MB.")


def _load_document_metadata(value: str | None, expected_count: int) -> list[dict[str, Any]]:
    if not value:
        return [{} for _ in range(expected_count)]
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid document_metadata_json: {exc.msg}") from exc
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="document_metadata_json must be an object or array")
    result: list[dict[str, Any]] = []
    for item in parsed:
        result.append(item if isinstance(item, dict) else {})
    while len(result) < expected_count:
        result.append({})
    return result[:expected_count]


def _apply_manual_upload_metadata(db: Session, document: Document, collection, metadata: dict[str, Any]) -> None:
    field_map = {
        "title": "manual_title_override",
        "manual_title_override": "manual_title_override",
        "sender": "extracted_sender",
        "correspondent": "extracted_sender",
        "recipient": "extracted_recipient",
        "customer": "extracted_recipient",
        "invoice_number": "extracted_invoice_number",
        "invoiceNo": "extracted_invoice_number",
        "date": "extracted_date",
        "created_date": "extracted_date",
        "amount": "extracted_amount",
        "payment_method": "extracted_payment_method",
    }
    sources = dict(document.metadata_sources_json or {})
    for key, attr in field_map.items():
        value = metadata.get(key)
        if value is None or str(value).strip() == "":
            continue
        setattr(document, attr, str(value).strip())
        source_key = "title" if attr == "manual_title_override" else attr.replace("extracted_", "")
        sources[source_key] = {"source": "manual", "confidence": 100}
    if metadata.get("metadata_locked") is not None:
        document.metadata_locked = bool(metadata.get("metadata_locked"))
    locks = metadata.get("field_locks_json") or metadata.get("field_locks") or {}
    if isinstance(locks, dict):
        document.field_locks_json = locks
    custom_fields = metadata.get("custom_fields") or metadata.get("customFields") or {}
    if isinstance(custom_fields, dict) and custom_fields:
        fields_by_slug = {field.slug: field for field in collection.custom_fields}
        fields_by_name = {field.name: field for field in collection.custom_fields}
        for raw_key, raw_value in custom_fields.items():
            if raw_value is None or str(raw_value).strip() == "":
                continue
            field = fields_by_slug.get(str(raw_key)) or fields_by_name.get(str(raw_key))
            if field is None:
                continue
            upsert_custom_field_value(
                db,
                document,
                field,
                raw_value,
                source=FieldValueSource.manual,
                confidence=100,
                force=True,
            )
    extra = {key: value for key, value in metadata.items() if key not in field_map and key not in {"custom_fields", "customFields", "metadata_locked", "field_locks_json", "field_locks"}}
    if extra:
        document.metadata_json = {**(document.metadata_json or {}), "manual_upload_metadata": extra}
    document.metadata_sources_json = sources


def _ocr_config_from_processing_options(options: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if options.get("language"):
        config["language"] = options["language"]
    if options.get("page_limit"):
        config["page_limit"] = options["page_limit"]
    if options.get("ocr_mode"):
        config["ocr_mode"] = options["ocr_mode"]
    if options.get("ocr_engine"):
        config["ocr_engine"] = options["ocr_engine"]
    return config


def _folder_from_record_metadata(db: Session, metadata: dict[str, Any], collection_id: uuid.UUID) -> Folder | None:
    raw_folder_id = metadata.get("folder_id")
    if raw_folder_id:
        try:
            folder_id = uuid.UUID(str(raw_folder_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid folder_id") from exc
        folder = db.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder
    folder_path = str(metadata.get("folder_path") or "").strip()
    if folder_path:
        return ensure_folder_path(db, folder_path, collection_id=collection_id)
    return None


@router.get("", response_model=list[BatchRead])
def list_batches(
    collection_name: str | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
) -> list[BatchRead]:
    stmt = select(Batch).order_by(Batch.created_at.desc())
    if collection_name:
        stmt = stmt.where(Batch.collection_name == collection_name)
    if status_filter:
        stmt = stmt.where(Batch.status == status_filter)
    return [BatchRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db)) -> BatchDetail:
    stmt = select(Batch).where(Batch.id == batch_id).options(selectinload(Batch.documents))
    batch = db.scalars(stmt).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchDetail.model_validate(batch)
