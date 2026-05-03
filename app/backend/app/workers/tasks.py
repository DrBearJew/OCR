from __future__ import annotations

import uuid

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document, DocumentState, StageState
from app.services.events import record_event
from app.services.processing import clear_processing_lease, queue_full_process, queue_ocr, reserve_processing_task
from app.services.processing import run_full_process_for_document, run_metadata_for_document, run_ocr_for_document
from app.services.reconciliation import reconcile_stuck_documents
from app.services.ingestion import scan_enabled_sources
from app.workers.celery_app import celery_app


MAX_PROCESSING_RETRIES = get_settings().ocr_max_retries


def _retry_delay(retries: int) -> int:
    return min(300, 10 * (2 ** retries))


def publish_task(task, *, args: list | tuple, kwargs: dict | None = None, task_id: str | None = None, queue: str | None = None):
    """Publish a Celery task while preserving older tests that monkeypatch .delay.

    Production needs apply_async so we can pin queues and task ids. A few existing
    tests patch task.delay to avoid a live Redis broker; when that happens, use
    the patched function instead of touching Redis.
    """
    delay = getattr(task, "delay")
    if getattr(delay, "__self__", None) is not task:
        return delay(*args, **(kwargs or {}))
    return task.apply_async(args=list(args), kwargs=kwargs or {}, task_id=task_id, queue=queue)


def publish_document_task(
    db,
    document_id: str | uuid.UUID,
    task,
    *,
    args: list | tuple,
    kwargs: dict | None = None,
    task_id: str | None = None,
    queue: str | None = None,
    stage: str,
):
    try:
        return publish_task(task, args=args, kwargs=kwargs, task_id=task_id, queue=queue)
    except Exception as exc:  # noqa: BLE001
        document = db.get(Document, uuid.UUID(str(document_id)))
        if document is not None:
            if task_id is None or document.processing_task_id == task_id:
                clear_processing_lease(document)
            document.error_message = f"Task publish failed for {stage}: {exc}"
            record_event(
                db,
                document,
                "task_publish_failed",
                "Task publish failed; processing lease was released for reconciliation",
                metadata={"stage": stage, "task_id": task_id, "queue": queue, "error": str(exc)},
            )
            db.commit()
        raise


@celery_app.task(name="app.workers.tasks.ocr_document_task", bind=True, max_retries=MAX_PROCESSING_RETRIES, queue="ocr")
def ocr_document_task(self, document_id: str) -> str:
    db = SessionLocal()
    try:
        run_ocr_for_document(db, uuid.UUID(document_id), enqueue_metadata=True, task_id=self.request.id)
        return document_id
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < MAX_PROCESSING_RETRIES:
            document = db.get(Document, uuid.UUID(document_id))
            if document is not None:
                document.processing_state = DocumentState.queued_for_ocr
                document.final_state = DocumentState.queued_for_ocr
                document.ocr_state = StageState.pending
                document.metadata_state = StageState.pending
                document.retry_after_at = None
                reserve_processing_task(document, task_id=self.request.id, stage="ocr", force=True)
                record_event(
                    db,
                    document,
                    "ocr_retry_scheduled",
                    "OCR task retry scheduled after transient worker/provider failure",
                    metadata={"retry": self.request.retries + 1, "error": str(exc)},
                )
                db.commit()
            raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.extract_metadata_task", bind=True, max_retries=MAX_PROCESSING_RETRIES, queue="metadata")
def extract_metadata_task(self, document_id: str, force: bool = False) -> str:
    db = SessionLocal()
    try:
        run_metadata_for_document(db, uuid.UUID(document_id), force=force, task_id=self.request.id)
        return document_id
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < MAX_PROCESSING_RETRIES:
            document = db.get(Document, uuid.UUID(document_id))
            if document is not None and document.ocr_state in {StageState.done, StageState.skipped}:
                document.processing_state = DocumentState.ocr_done
                document.final_state = DocumentState.ocr_done
                document.metadata_state = StageState.pending
                reserve_processing_task(document, task_id=self.request.id, stage="metadata", force=True)
                record_event(
                    db,
                    document,
                    "metadata_retry_scheduled",
                    "Metadata task retry scheduled after worker failure",
                    metadata={"retry": self.request.retries + 1, "error": str(exc), "force": force},
                )
                db.commit()
            raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_document_task", bind=True, max_retries=MAX_PROCESSING_RETRIES, queue="ocr")
def process_document_task(self, document_id: str, force: bool = False) -> str:
    db = SessionLocal()
    try:
        run_full_process_for_document(db, uuid.UUID(document_id), force=force, task_id=self.request.id)
        return document_id
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < MAX_PROCESSING_RETRIES:
            document = db.get(Document, uuid.UUID(document_id))
            if document is not None:
                queue_full_process(db, document, force=True)
                reserve_processing_task(document, task_id=self.request.id, stage="process", force=True)
                record_event(
                    db,
                    document,
                    "process_retry_scheduled",
                    "Full process task retry scheduled after worker failure",
                    metadata={"retry": self.request.retries + 1, "error": str(exc), "force": force},
                )
                db.commit()
            raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_record_task", bind=True, max_retries=MAX_PROCESSING_RETRIES, queue="maintenance")
def process_record_task(self, record_id: str, force: bool = False) -> dict:
    db = SessionLocal()
    try:
        documents = db.scalars(
            select(Document)
            .where(Document.record_id == uuid.UUID(record_id))
            .where(Document.deleted_at.is_(None))
            .order_by(Document.created_at.asc())
        ).all()
        queued = 0
        skipped = 0
        queueable: list[tuple[str, str]] = []
        for document in documents:
            if queue_full_process(db, document, force=force):
                task_id = str(uuid.uuid4())
                reserve_processing_task(document, task_id=task_id, stage="process", force=force)
                queued += 1
                queueable.append((str(document.id), task_id))
            else:
                skipped += 1
        db.commit()
        for document_id, task_id in queueable:
            publish_document_task(db, document_id, process_document_task, args=[document_id], kwargs={"force": force}, task_id=task_id, queue="ocr", stage="process")
        return {"record_id": record_id, "queued": queued, "skipped": skipped}
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.reconcile_stuck_documents_task", bind=True, max_retries=2, queue="maintenance")
def reconcile_stuck_documents_task(self) -> dict:
    db = SessionLocal()
    try:
        return reconcile_stuck_documents(db)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.scan_ingestion_sources_task", bind=True, max_retries=2, queue="maintenance")
def scan_ingestion_sources_task(self) -> dict:
    db = SessionLocal()
    try:
        return scan_enabled_sources(db)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=_retry_delay(self.request.retries))
    finally:
        db.close()
