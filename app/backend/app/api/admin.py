from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.models import (
    Correspondent,
    Document,
    DocumentState,
    DocumentType,
    IngestionJob,
    IngestionSource,
)
from app.models import ProcessingHook, StoragePathRule, Tag
from app.schemas import (
    ModelEndpointTestPayload,
    ModelEndpointTestResult,
    ModelSetupRead,
    ModelSetupWrite,
    AdminActionResult,
    IngestionJobRead,
    IngestionSourceRead,
    IngestionSourceWrite,
    JobInfo,
    PaperlessMetadataPatch,
    PaperlessMetadataRead,
    PaperlessMetadataWrite,
    ProcessingHookRead,
    ProcessingHookWrite,
)
from app.services.collections import slugify
from app.services.hooks import execute_hook
from app.services.ingestion import retry_ingestion_job, scan_enabled_sources, scan_source
from app.services.integrations import collect_integrations
from app.services.model_setup import get_model_setup, save_model_setup, check_model_endpoint
from app.services.reconciliation import reconcile_stuck_documents, reextract_collection, retry_failed_documents
from app.services.storage_integrity import scan_storage_integrity


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _job(document: Document) -> JobInfo:
    return JobInfo(
        document_id=document.id,
        batch_id=document.batch_id,
        state=document.processing_state,
        ocr_state=document.ocr_state,
        metadata_state=document.metadata_state,
        filename=document.original_filename,
        title=document.manual_title_override or document.extracted_title,
        updated_at=document.updated_at,
        error_message=document.error_message,
    )


@router.get("/jobs", response_model=list[JobInfo])
def recent_jobs(db: Session = Depends(get_db)) -> list[JobInfo]:
    stmt = select(Document).order_by(Document.updated_at.desc()).limit(50)
    return [_job(document) for document in db.scalars(stmt).all()]


@router.get("/failed", response_model=list[JobInfo])
def failed_documents(db: Session = Depends(get_db)) -> list[JobInfo]:
    stmt = (
        select(Document)
        .where(Document.processing_state == DocumentState.failed)
        .order_by(Document.updated_at.desc())
        .limit(100)
    )
    return [_job(document) for document in db.scalars(stmt).all()]


@router.get("/integrations")
def integrations(db: Session = Depends(get_db)) -> dict:
    return collect_integrations(db)


@router.get("/model-setup", response_model=ModelSetupRead)
def read_model_setup(db: Session = Depends(get_db)) -> ModelSetupRead:
    return ModelSetupRead(**get_model_setup(db))


@router.patch("/model-setup", response_model=ModelSetupRead)
def update_model_setup(payload: ModelSetupWrite, db: Session = Depends(get_db)) -> ModelSetupRead:
    return ModelSetupRead(**save_model_setup(db, payload.model_dump()))


@router.post("/model-setup/test", response_model=ModelEndpointTestResult)
def test_model_setup_endpoint(payload: ModelEndpointTestPayload) -> ModelEndpointTestResult:
    return ModelEndpointTestResult(**check_model_endpoint(payload.model_dump()))


@router.post("/reconcile", response_model=AdminActionResult)
def reconcile(db: Session = Depends(get_db)) -> AdminActionResult:
    return AdminActionResult(**reconcile_stuck_documents(db))


@router.post("/retry-failed", response_model=AdminActionResult)
def retry_failed(db: Session = Depends(get_db)) -> AdminActionResult:
    return AdminActionResult(**retry_failed_documents(db))


@router.post("/reextract-collection", response_model=AdminActionResult)
def reextract_collection_endpoint(
    collection_name: str,
    force: bool = False,
    db: Session = Depends(get_db),
) -> AdminActionResult:
    return AdminActionResult(**reextract_collection(db, collection_name, force=force))


@router.get("/storage-integrity")
def storage_integrity(db: Session = Depends(get_db)) -> dict:
    return scan_storage_integrity(db)


@router.post("/reindex", response_model=AdminActionResult)
def reindex_documents(
    collection_name: str | None = None,
    db: Session = Depends(get_db),
) -> AdminActionResult:
    from app.services.events import record_event

    stmt = select(Document).where(Document.deleted_at.is_(None))
    if collection_name:
        stmt = stmt.where(Document.collection_name == collection_name)
    updated = 0
    for document in db.scalars(stmt).all():
        document.metadata_json = {**(document.metadata_json or {}), "search_indexed": True}
        record_event(db, document, "search_indexed", "Search index marker refreshed by admin reindex", actor="admin", source="manual")
        updated += 1
    db.commit()
    return AdminActionResult(ok=True, updated=updated, details={"collection_name": collection_name})


@router.get("/ingestion-sources", response_model=list[IngestionSourceRead])
def ingestion_sources(db: Session = Depends(get_db)) -> list[IngestionSourceRead]:
    rows = db.scalars(select(IngestionSource).order_by(IngestionSource.created_at.desc())).all()
    return [IngestionSourceRead.model_validate(row) for row in rows]


@router.post("/ingestion-sources", response_model=IngestionSourceRead)
def create_ingestion_source(payload: IngestionSourceWrite, db: Session = Depends(get_db)) -> IngestionSourceRead:
    row = IngestionSource(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return IngestionSourceRead.model_validate(row)


@router.patch("/ingestion-sources/{source_id}", response_model=IngestionSourceRead)
def update_ingestion_source(source_id: uuid.UUID, payload: IngestionSourceWrite, db: Session = Depends(get_db)) -> IngestionSourceRead:
    row = db.get(IngestionSource, source_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Ingestion source not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return IngestionSourceRead.model_validate(row)


@router.post("/ingestion-sources/{source_id}/scan")
def scan_ingestion_source(source_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    source = db.get(IngestionSource, source_id)
    if source is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Ingestion source not found")
    return scan_source(db, source)


@router.post("/ingestion-sources/scan-all")
def scan_all_ingestion_sources(db: Session = Depends(get_db)) -> dict:
    return scan_enabled_sources(db)


@router.get("/ingestion-jobs", response_model=list[IngestionJobRead])
def ingestion_jobs(db: Session = Depends(get_db)) -> list[IngestionJobRead]:
    rows = db.scalars(select(IngestionJob).order_by(IngestionJob.updated_at.desc()).limit(200)).all()
    return [IngestionJobRead.model_validate(row) for row in rows]


@router.post("/ingestion-jobs/{job_id}/retry", response_model=IngestionJobRead)
def retry_ingestion(job_id: uuid.UUID, db: Session = Depends(get_db)) -> IngestionJobRead:
    job = db.get(IngestionJob, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return IngestionJobRead.model_validate(retry_ingestion_job(db, job))


@router.get("/hooks", response_model=list[ProcessingHookRead])
def processing_hooks(db: Session = Depends(get_db)) -> list[ProcessingHookRead]:
    rows = db.scalars(select(ProcessingHook).order_by(ProcessingHook.stage.asc(), ProcessingHook.created_at.asc())).all()
    return [ProcessingHookRead.model_validate(row) for row in rows]


@router.post("/hooks", response_model=ProcessingHookRead)
def create_processing_hook(payload: ProcessingHookWrite, db: Session = Depends(get_db)) -> ProcessingHookRead:
    row = ProcessingHook(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ProcessingHookRead.model_validate(row)


@router.post("/hooks/{hook_id}/test")
def test_processing_hook(hook_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    hook = db.get(ProcessingHook, hook_id)
    if hook is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Hook not found")
    return execute_hook(hook, context={"test": True})


@router.get("/metadata/{kind}", response_model=list[PaperlessMetadataRead])
def list_paperless_metadata(kind: str, db: Session = Depends(get_db)) -> list[PaperlessMetadataRead]:
    model = _metadata_model(kind)
    rows = db.scalars(select(model).order_by(model.name.asc())).all()
    return [PaperlessMetadataRead.model_validate(row) for row in rows]


@router.post("/metadata/{kind}", response_model=PaperlessMetadataRead)
def create_paperless_metadata(kind: str, payload: PaperlessMetadataWrite, db: Session = Depends(get_db)) -> PaperlessMetadataRead:
    model = _metadata_model(kind)
    values = payload.model_dump(exclude_unset=True)
    values["slug"] = values.get("slug") or slugify(payload.name)
    if model is not Tag:
        values.pop("color", None)
    if model is not StoragePathRule:
        values.pop("path_template", None)
    else:
        values["path_template"] = values.get("path_template") or "{collection}/{year}"
    row = model(**values)
    db.add(row)
    db.commit()
    db.refresh(row)
    return PaperlessMetadataRead.model_validate(row)


@router.patch("/metadata/{kind}/{metadata_id}", response_model=PaperlessMetadataRead)
def update_paperless_metadata(kind: str, metadata_id: uuid.UUID, payload: PaperlessMetadataPatch, db: Session = Depends(get_db)) -> PaperlessMetadataRead:
    model = _metadata_model(kind)
    row = db.get(model, metadata_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Metadata profile not found")
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        row.name = values["name"]
        if "slug" not in values or values.get("slug") is None:
            row.slug = slugify(row.name)
    if "slug" in values and values["slug"] is not None:
        row.slug = values["slug"]
    if model is Tag and "color" in values:
        row.color = values.get("color")
    if model is StoragePathRule and "path_template" in values and values.get("path_template") is not None:
        row.path_template = values["path_template"]
    if "collection_id" in values:
        row.collection_id = values.get("collection_id")
    if "match_rules" in values and values.get("match_rules") is not None:
        row.match_rules = values["match_rules"]
    db.commit()
    db.refresh(row)
    return PaperlessMetadataRead.model_validate(row)


@router.delete("/metadata/{kind}/{metadata_id}", response_model=PaperlessMetadataRead)
def delete_paperless_metadata(kind: str, metadata_id: uuid.UUID, db: Session = Depends(get_db)) -> PaperlessMetadataRead:
    model = _metadata_model(kind)
    row = db.get(model, metadata_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Metadata profile not found")
    result = PaperlessMetadataRead.model_validate(row)
    db.delete(row)
    db.commit()
    return result


@router.get("/{kind}", response_model=list[PaperlessMetadataRead])
def list_paperless_metadata_legacy(kind: str, db: Session = Depends(get_db)) -> list[PaperlessMetadataRead]:
    return list_paperless_metadata(kind, db)


@router.post("/{kind}", response_model=PaperlessMetadataRead)
def create_paperless_metadata_legacy(kind: str, payload: PaperlessMetadataWrite, db: Session = Depends(get_db)) -> PaperlessMetadataRead:
    return create_paperless_metadata(kind, payload, db)


def _metadata_model(kind: str):
    mapping = {
        "correspondents": Correspondent,
        "document-types": DocumentType,
        "tags": Tag,
        "storage-paths": StoragePathRule,
    }
    if kind not in mapping:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Unknown metadata kind")
    return mapping[kind]
