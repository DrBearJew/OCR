from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import fnmatch
import hashlib
import mimetypes
import shutil
import uuid
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Batch,
    Document,
    IngestionJob,
    IngestionJobStatus,
    IngestionSource,
    IngestionSourceType,
    Record,
    RecordGrouping,
)
from app.services.collections import create_record_for_upload, update_record_status
from app.services.converters import convert_if_needed
from app.services.document_assets import generate_thumbnail, inspect_page_count, virus_scan_placeholder
from app.services.events import record_event
from app.services.hooks import execute_hooks
from app.models import HookStage
from app.services.processing import queue_ocr, reserve_processing_task, update_batch_status
from app.services.storage import LocalStorage, safe_filename


def scan_enabled_sources(db: Session) -> dict:
    sources = db.scalars(
        select(IngestionSource)
        .where(IngestionSource.enabled.is_(True))
        .where(IngestionSource.source_type == IngestionSourceType.consume_folder)
    ).all()
    total = {"sources": len(sources), "discovered": 0, "imported": 0, "skipped": 0, "failed": 0}
    for source in sources:
        result = scan_source(db, source)
        for key in ("discovered", "imported", "skipped", "failed"):
            total[key] += result[key]
    return total


def scan_source(db: Session, source: IngestionSource) -> dict:
    root = Path(source.path or "")
    if not root.exists() or not root.is_dir():
        return {"discovered": 0, "imported": 0, "skipped": 0, "failed": 1, "error": "source path not found"}
    files = _discover_files(root, recursive=source.recursive, ignore_patterns=source.ignore_patterns or [])
    batch: Batch | None = None
    shared_record: Record | None = None
    queued_document_ids: list[uuid.UUID] = []
    created_record_ids: set[uuid.UUID] = set()
    counts = {"discovered": len(files), "imported": 0, "skipped": 0, "failed": 0}
    for file_path in files:
        job = _get_or_create_job(db, source, file_path)
        if job.status in {IngestionJobStatus.imported, IngestionJobStatus.skipped}:
            counts["skipped"] += 1
            continue
        if batch is None:
            batch = Batch(collection_name=source.collection.name, label=f"Consume: {source.name}", document_count=0)
            db.add(batch)
            db.flush()
        if source.record_grouping == RecordGrouping.one_record_per_batch and shared_record is None:
            shared_record = create_record_for_upload(db, source.collection, title=f"Consume: {source.name}")
            created_record_ids.add(shared_record.id)
        record = shared_record or create_record_for_upload(db, source.collection, title=file_path.stem)
        created_record_ids.add(record.id)
        try:
            import_job(db, job, batch, record)
            if job.status == IngestionJobStatus.imported and job.document_id is not None:
                counts["imported"] += 1
                queued_document_ids.append(job.document_id)
            elif job.status == IngestionJobStatus.skipped:
                counts["skipped"] += 1
        except Exception as exc:  # noqa: BLE001
            job.status = IngestionJobStatus.failed
            job.error_message = str(exc)
            counts["failed"] += 1
        update_record_status(db, record.id)
    if batch is not None:
        update_batch_status(db, batch.id)
        if counts["imported"] == 0 and not db.scalars(select(Document).where(Document.batch_id == batch.id)).first():
            db.delete(batch)
    for record_id in created_record_ids:
        if not db.scalars(select(Document).where(Document.record_id == record_id)).first():
            record = db.get(Record, record_id)
            if record is not None:
                db.delete(record)
    db.commit()
    for document_id in queued_document_ids:
        from app.workers.tasks import ocr_document_task, publish_document_task

        task_id = str(uuid.uuid4())
        document = db.get(Document, document_id)
        if document is not None:
            reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
            db.commit()
        publish_document_task(db, document_id, ocr_document_task, args=[str(document_id)], task_id=task_id, queue="ocr", stage="ocr")
    return counts


def retry_ingestion_job(db: Session, job: IngestionJob) -> IngestionJob:
    collection = job.source.collection
    batch = Batch(collection_name=collection.name, label=f"Retry consume: {job.source.name}", document_count=1)
    db.add(batch)
    db.flush()
    record = create_record_for_upload(db, collection, title=Path(job.discovered_path).stem)
    import_job(db, job, batch, record)
    has_document = db.scalars(select(Document).where(Document.batch_id == batch.id)).first() is not None
    if has_document:
        update_batch_status(db, batch.id)
        update_record_status(db, record.id)
    else:
        db.delete(record)
        db.delete(batch)
    queued_document_id = job.document_id if job.status == IngestionJobStatus.imported else None
    db.commit()
    if queued_document_id is not None:
        from app.workers.tasks import ocr_document_task, publish_document_task

        task_id = str(uuid.uuid4())
        document = db.get(Document, queued_document_id)
        if document is not None:
            reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
            db.commit()
        publish_document_task(db, queued_document_id, ocr_document_task, args=[str(queued_document_id)], task_id=task_id, queue="ocr", stage="ocr")
    return job


def import_job(db: Session, job: IngestionJob, batch: Batch, record: Record) -> IngestionJob:
    source_path = Path(job.discovered_path)
    job.status = IngestionJobStatus.processing
    job.attempts += 1
    job.error_message = None
    db.flush()

    digest = _sha256(source_path)
    job.sha256 = digest
    if db.scalars(select(Document).where(Document.sha256 == digest).where(Document.deleted_at.is_(None))).first() is not None:
        job.status = IngestionJobStatus.skipped
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = "duplicate hash already imported"
        return job

    converted_path = convert_if_needed(str(source_path))
    storage = LocalStorage()
    mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    storage.validate_upload(SimpleNamespace(filename=source_path.name, content_type=mime_type))
    virus_scan_placeholder(converted_path)
    execute_hooks(db, HookStage.pre_consume, ingestion_job=job, context={"source_path": str(source_path)})

    target = _copy_to_storage(Path(converted_path), batch.id)
    page_count = inspect_page_count(str(target), mime_type)
    document = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name=job.source.collection.name,
        original_filename=source_path.name,
        storage_path=str(target),
        mime_type=mime_type,
        file_size=target.stat().st_size,
        sha256=digest,
        page_count=page_count,
        ocr_config_json={**(job.source.ocr_config_json or {})},
        legacy_source="consume_folder",
        legacy_document_id=str(source_path),
    )
    db.add(document)
    db.flush()
    job.batch_id = batch.id
    job.record_id = record.id
    job.document_id = document.id
    document.thumbnail_path = generate_thumbnail(str(target), mime_type, document.id)
    record_event(db, document, "ingested", "Document ingested from consume folder", metadata={"source_id": str(job.source_id), "source_path": str(source_path)})
    queue_ocr(db, document)
    job.status = IngestionJobStatus.imported
    job.completed_at = datetime.now(timezone.utc)
    db.flush()
    return job


def _discover_files(root: Path, *, recursive: bool, ignore_patterns: list) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.glob("*")
    files: list[Path] = []
    for path in iterator:
        if not path.is_file():
            continue
        if any(fnmatch.fnmatch(path.name, str(pattern)) for pattern in ignore_patterns):
            continue
        files.append(path)
    return sorted(files)


def _get_or_create_job(db: Session, source: IngestionSource, path: Path) -> IngestionJob:
    job = db.scalars(
        select(IngestionJob)
        .where(IngestionJob.source_id == source.id)
        .where(IngestionJob.discovered_path == str(path))
    ).first()
    if job:
        return job
    job = IngestionJob(source_id=source.id, discovered_path=str(path), status=IngestionJobStatus.pending)
    db.add(job)
    db.flush()
    return job


def _copy_to_storage(path: Path, batch_id: uuid.UUID) -> Path:
    settings = get_settings()
    target_dir = Path(settings.storage_root) / str(batch_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4()}_{safe_filename(path.name)}"
    shutil.copy2(path, target)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
