from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentState, ReviewState, StageState
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
    queued_metadata_repair = 0
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

        if metadata_quality_needs_repair(document):
            if has_active_processing_lease(document):
                skipped += 1
                continue
            document.processing_state = DocumentState.ocr_done
            document.final_state = DocumentState.ocr_done
            document.metadata_state = StageState.pending
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata", force=True)
            record_event(
                db,
                document,
                "reconcile_metadata_quality_repair",
                "Suspicious or stale metadata detected; metadata repair queued",
                metadata={"reasons": metadata_quality_repair_reasons(document)},
            )
            enqueue_after_commit.append(("metadata", str(document.id), True, task_id))
            queued_metadata += 1
            queued_metadata_repair += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
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

        if (
            document.processing_state == DocumentState.queued_for_ocr
            and not has_active_processing_lease(document)
            and _looks_orphaned_from_publish_or_expired_lease(document)
        ):
            record_event(db, document, "reconcile_orphaned_queued_ocr", "Queued OCR document had no active task lease; requeued immediately")
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="ocr", force=True)
            enqueue_after_commit.append(("ocr", str(document.id), False, task_id))
            queued_ocr += 1
            document_ids.append(str(document.id))
            update_batch_status(db, document.batch_id)
            update_record_status(db, document.record_id)
            continue

        if (
            document.processing_state == DocumentState.ocr_done
            and document.metadata_state not in {StageState.done, StageState.skipped}
            and not has_active_processing_lease(document)
            and _looks_orphaned_from_publish_or_expired_lease(document)
        ):
            record_event(db, document, "reconcile_orphaned_queued_metadata", "OCR-done document had no active metadata task lease; metadata requeued immediately")
            task_id = str(uuid.uuid4())
            reserve_processing_task(document, task_id=task_id, stage="metadata", force=True)
            enqueue_after_commit.append(("metadata", str(document.id), False, task_id))
            queued_metadata += 1
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
            "queued_metadata_repair": queued_metadata_repair,
            "document_ids": document_ids,
        },
    }


METADATA_REPAIR_REVIEW_PREFIXES = (
    "Qwen metadata brain",
    "Qwen disagrees with deterministic",
    "Fallback title",
    "Suspicious",
)

BAD_METADATA_PARTY_TOKENS = {
    "leistungszeitraum",
    "vertragslaufzeit",
    "rechnungsbetrag",
    "zahlenderbetrag",
    "falligam",
    "faelligam",
}


def metadata_quality_repair_reasons(document: Document) -> list[str]:
    reasons: list[str] = []
    if document.deleted_at is not None or document.metadata_locked:
        return reasons
    if document.ocr_state not in {StageState.done, StageState.skipped} or not document.ocr_text:
        return reasons
    if document.processing_state not in {DocumentState.complete, DocumentState.needs_review, DocumentState.metadata_done}:
        return reasons
    metadata = document.metadata_json or {}
    refinement = metadata.get("qwen_refinement") if isinstance(metadata.get("qwen_refinement"), dict) else {}
    qwen_error = str(refinement.get("error") or "")
    qwen_transient_failure = _qwen_transient_failure_error(qwen_error)
    review_reason = str(document.review_reason or "")
    if document.review_state == ReviewState.needs_review and review_reason.startswith(METADATA_REPAIR_REVIEW_PREFIXES):
        if not qwen_transient_failure:
            reasons.append("auto_review_reason")
    if qwen_error and ("invalid metadata candidate JSON" in qwen_error or "invalid" in qwen_error.lower()):
        reasons.append("qwen_invalid_json")
    if _bad_metadata_party(document.extracted_sender):
        reasons.append("bad_sender_token")
    if _suspicious_year_amount(document.extracted_amount):
        reasons.append("suspicious_year_amount")
    title = str(document.extracted_title or "")
    if any(token in title.lower() for token in BAD_METADATA_PARTY_TOKENS):
        reasons.append("bad_title_token")
    if re.search(r"_(?:19|20)\d{2},00$", title):
        reasons.append("title_year_amount")
    warnings = metadata.get("review_warnings") if isinstance(metadata.get("review_warnings"), list) else []
    if any(str(item).startswith(METADATA_REPAIR_REVIEW_PREFIXES) for item in warnings):
        if not qwen_transient_failure:
            reasons.append("auto_review_warning")
    return sorted(set(reasons))


def _qwen_transient_failure_error(error: str) -> bool:
    value = (error or "").lower()
    return any(
        marker in value
        for marker in (
            "timed out",
            "timeout",
            "read timed out",
            "model gateway lock timeout",
            "qwen request failed",
            "http 503",
            "503 service unavailable",
        )
    )


def metadata_quality_needs_repair(document: Document) -> bool:
    return bool(metadata_quality_repair_reasons(document))


def _bad_metadata_party(value: str | None) -> bool:
    token = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return token in BAD_METADATA_PARTY_TOKENS


def _suspicious_year_amount(value: str | None) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2},00", str(value or "").strip()))


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
    from app.workers.tasks import ocr_document_task, publish_document_task
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        publish_document_task(db, document_id, ocr_document_task, args=[str(document_id)], task_id=task_id, queue="ocr", stage="ocr")
    finally:
        db.close()


def _enqueue_metadata(document_id, *, force: bool = False, task_id: str | None = None) -> None:
    from app.workers.tasks import extract_metadata_task, publish_document_task
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        publish_document_task(db, document_id, extract_metadata_task, args=[str(document_id)], kwargs={"force": force}, task_id=task_id, queue="metadata", stage="metadata")
    finally:
        db.close()


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


def _looks_orphaned_from_publish_or_expired_lease(document: Document) -> bool:
    if (document.error_message or "").startswith("Task publish failed"):
        return True
    if document.processing_task_id and not has_active_processing_lease(document):
        return True
    return False
