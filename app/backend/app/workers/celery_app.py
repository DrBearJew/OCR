from __future__ import annotations

from celery import Celery

from app.config import get_settings


settings = get_settings()
celery_app = Celery(
    "dokocr",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    task_default_queue="metadata",
    task_routes={
        "app.workers.tasks.ocr_document_task": {"queue": "ocr"},
        "app.workers.tasks.process_document_task": {"queue": "ocr"},
        "app.workers.tasks.extract_metadata_task": {"queue": "metadata"},
        "app.workers.tasks.process_record_task": {"queue": "maintenance"},
        "app.workers.tasks.reconcile_stuck_documents_task": {"queue": "maintenance"},
        "app.workers.tasks.scan_ingestion_sources_task": {"queue": "maintenance"},
    },
    task_annotations={
        "app.workers.tasks.ocr_document_task": {
            "soft_time_limit": settings.ocr_task_soft_time_limit,
            "time_limit": settings.ocr_task_time_limit,
        },
        "app.workers.tasks.process_document_task": {
            "soft_time_limit": settings.ocr_task_soft_time_limit,
            "time_limit": settings.ocr_task_time_limit,
        },
    },
    beat_schedule={
        "reconcile-stuck-documents": {
            "task": "app.workers.tasks.reconcile_stuck_documents_task",
            "schedule": 300.0,
        },
        "scan-ingestion-sources": {
            "task": "app.workers.tasks.scan_ingestion_sources_task",
            "schedule": float(settings.ingestion_poll_interval_seconds),
        },
    },
)
