from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentState, StageState
from app.services.events import record_event
from app.services.collections import update_record_status
from app.services.processing import has_active_processing_lease, queue_ocr, reserve_processing_task, update_batch_status


TRANSITIONAL_STATES = {
    DocumentState.uploaded,
    DocumentState.queued_for_ocr,
    DocumentState.ocr_processing,
    DocumentState.ocr_done,
    DocumentState.metadata_processing,
}

RECONCILE_STATES = {
    *TRANSITIONAL_STATES,
    DocumentState.metadata_done,
    DocumentState.complete,
    DocumentState.needs_review,
    DocumentState.failed,
}


def reconcile_stuck_documents(db: Session, *, limit: int = 100) -> dict[str, Any]:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.stuck_document_minutes)
    stmt = (
        select(Document)
        .where(Document.processing_state.in_(RECONCILE_STATES))
        .order_by(Document.updated_at.asc())
        .limit(limit)
    )
    queued_ocr = 0
    queued_metadata = 0
    skipped = 0
    document_ids: list[str] = []
    enqueue_after_commit: list[tuple[str, str, bool, str]] = []

    for document in db.scalars(stmt).all():
        if document.deleted_at is not None:
            skipped += 1
            continue
        if document.processing_state == DocumentState.failed:
            if document.retry_after_at is None:
                skipped += 1
                continue
            retry_after = document.retry_after_at
            if retry_after.tzinfo is None:
                retry_after = retry_after.replace(tzinfo=timezone.utc)
            if retry_after > datetime.now(timezone.utc):
                skipped += 1
                continue
            if has_active_processing_lease(document):
                skipped += 1
                continue
            if queue_ocr(db, document, force=True):
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
                record_event(db, document, "reconcile_retry_failed", "Retryable failed document requeued")
                enqueue_after_commit.append(("ocr", str(document.id), True, task_id))
                queued_ocr += 1
                document_ids.append(str(document.id))
            continue

        if document.ocr_text and document.ocr_state == StageState.done and document.metadata_state not in {StageState.done, StageState.skipped}:
            if has_active_processing_lease(document):
                skipped += 1
                continue
            document.processing_state = DocumentState.ocr_done
            document.final_state = DocumentState.ocr_done
            document.metadata_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata")
            record_event(db, document, "reconcile_ocr_without_metadata", "OCR text exists but metadata is missing; metadata queued")
            enqueue_after_commit.append(("metadata", str(document.id), False, task_id))
            queued_metadata += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if document.metadata_state == StageState.done and not (document.manual_title_override or document.extracted_title):
            if has_active_processing_lease(document):
                skipped += 1
                continue
            document.processing_state = DocumentState.ocr_done
            document.final_state = DocumentState.ocr_done
            document.metadata_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata", force=True)
            record_event(db, document, "reconcile_metadata_without_title", "Metadata exists but final title is missing; metadata queued")
            enqueue_after_commit.append(("metadata", str(document.id), True, task_id))
            queued_metadata += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if document.processing_state == DocumentState.complete and not (document.metadata_json or {}).get("search_indexed"):
            document.metadata_json = {**(document.metadata_json or {}), "search_indexed": True}
            record_event(db, document, "search_indexed", "Search index marker repaired by reconciliation")
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if not _is_reconcile_stale(document, cutoff):
            skipped += 1
            continue
        if has_active_processing_lease(document):
            skipped += 1
            continue
        heartbeat = document.last_processing_heartbeat_at
        if heartbeat is not None and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        active_recently = heartbeat is not None and heartbeat > cutoff

        if document.processing_state == DocumentState.uploaded:
            if queue_ocr(db, document):
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="ocr")
                enqueue_after_commit.append(("ocr", str(document.id), False, task_id))
                queued_ocr += 1
                document_ids.append(str(document.id))
                update_batch_status(db, document.batch_id)
                update_record_status(db, document.record_id)
            continue

        if document.processing_state == DocumentState.queued_for_ocr:
            record_event(db, document, "reconcile_queued_ocr", "Reconciliation requeued OCR")
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="ocr")
            enqueue_after_commit.append(("ocr", str(document.id), False, task_id))
            queued_ocr += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if document.processing_state == DocumentState.ocr_processing:
            if active_recently:
                skipped += 1
                continue
            document.processing_state = DocumentState.queued_for_ocr
            document.final_state = DocumentState.queued_for_ocr
            document.ocr_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="ocr")
            record_event(db, document, "reconcile_stale_ocr", "Stale OCR processing reset and requeued")
            enqueue_after_commit.append(("ocr", str(document.id), False, task_id))
            queued_ocr += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if document.processing_state == DocumentState.ocr_done:
            record_event(db, document, "reconcile_queued_metadata", "Reconciliation queued metadata extraction")
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata")
            enqueue_after_commit.append(("metadata", str(document.id), False, task_id))
            queued_metadata += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if document.processing_state == DocumentState.metadata_processing:
            if active_recently:
                skipped += 1
                continue
            document.processing_state = DocumentState.ocr_done
            document.final_state = DocumentState.ocr_done
            document.metadata_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata")
            record_event(db, document, "reconcile_stale_metadata", "Stale metadata processing reset and requeued")
            enqueue_after_commit.append(("metadata", str(document.id), False, task_id))
            queued_metadata += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)

    db.commit()
    for task_name, document_id, force, task_id in enqueue_after_commit:
        if task_name == "ocr":
            try:
                _enqueue_ocr(document_id, task_id=task_id)
            except TypeError:
                _enqueue_ocr(document_id)
        else:
            try:
                _enqueue_metadata(document_id, force=force, task_id=task_id)
            except TypeError:
                _enqueue_metadata(document_id, force=force)
    return {
        "queued": queued_ocr + queued_metadata,
        "updated": queued_ocr + queued_metadata,
        "skipped": skipped,
        "details": {
            "queued_ocr": queued_ocr,
            "queued_metadata": queued_metadata,
            "document_ids": document_ids,
        },
    }


def retry_failed_documents(db: Session, *, limit: int = 100) -> dict[str, Any]:
    stmt = (
        select(Document)
        .where(Document.processing_state == DocumentState.failed)
        .order_by(Document.updated_at.asc())
        .limit(limit)
    )
    queued = 0
    enqueue_after_commit: list[tuple[str, str]] = []
    for document in db.scalars(stmt).all():
        if queue_ocr(db, document, force=True):
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
            record_event(db, document, "retry_failed", "Failed document queued for retry")
            enqueue_after_commit.append((str(document.id), task_id))
            queued += 1
    db.commit()
    for document_id, task_id in enqueue_after_commit:
        try:
            _enqueue_ocr(document_id, task_id=task_id)
        except TypeError:
            _enqueue_ocr(document_id)
    return {"queued": queued, "updated": queued, "skipped": 0, "details": {}}


def reextract_collection(db: Session, collection_name: str, *, force: bool = False, limit: int = 500) -> dict[str, Any]:
    stmt = (
        select(Document)
        .where(Document.collection_name == collection_name)
        .where(Document.ocr_state.in_([StageState.done, StageState.skipped]))
        .where(Document.processing_state.in_([DocumentState.ocr_done, DocumentState.complete, DocumentState.needs_review]))
        .limit(limit)
    )
    queued = 0
    skipped = 0
    enqueue_after_commit: list[tuple[str, bool, str]] = []
    for document in db.scalars(stmt).all():
        if document.metadata_locked and not force:
            record_event(db, document, "reextract_collection_skipped_locked", "Collection reextract skipped locked document")
            skipped += 1
            continue
        document.processing_state = DocumentState.ocr_done
        document.final_state = DocumentState.ocr_done
        document.metadata_state = StageState.pending
        task_id = str(uuid.uuid4())
        reserve_processing_task(document, task_id=task_id, stage="metadata", force=force)
        record_event(db, document, "reextract_collection_queued", "Collection metadata reextract queued", metadata={"force": force})
        update_batch_status(db, document.batch_id)
        enqueue_after_commit.append((str(document.id), force, task_id))
        queued += 1
    db.commit()
    for document_id, force_value, task_id in enqueue_after_commit:
        try:
            _enqueue_metadata(document_id, force=force_value, task_id=task_id)
        except TypeError:
            _enqueue_metadata(document_id, force=force_value)
    return {"queued": queued, "updated": queued, "skipped": skipped, "details": {"collection_name": collection_name}}


def _enqueue_ocr(document_id, *, task_id: str | None = None) -> None:
    from app.workers.tasks import ocr_document_task, publish_task

    publish_task(ocr_document_task, args=[str(document_id)], task_id=task_id, queue="ocr")


def _enqueue_metadata(document_id, *, force: bool = False, task_id: str | None = None) -> None:
    from app.workers.tasks import extract_metadata_task, publish_task

    publish_task(extract_metadata_task, args=[str(document_id)], kwargs={"force": force}, task_id=task_id, queue="metadata")


def _is_reconcile_stale(document: Document, cutoff: datetime) -> bool:
    heartbeat = document.last_processing_heartbeat_at
    if heartbeat is not None:
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        return heartbeat <= cutoff
    updated = document.updated_at or document.created_at
    if updated is None:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated <= cutoff
