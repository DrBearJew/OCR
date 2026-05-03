from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Collection, Correspondent, Document, DocumentType, StoragePathRule
from app.services.collections import slugify
from app.services.events import record_event


def apply_paperless_metadata(db: Session, document: Document) -> None:
    collection = document.record.collection if document.record else None
    if collection is None:
        return
    party = document.extracted_sender or document.extracted_recipient
    if party and party != "Dok":
        correspondent = _ensure_correspondent(db, collection, party)
        document.correspondent_id = correspondent.id
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    sources = document.metadata_sources_json if isinstance(document.metadata_sources_json, dict) else {}
    locked = document.metadata_locked
    if not (locked or _manual_source(sources, "document_type_id")):
        document_type_name = str(metadata.get("document_type") or document.collection_name)
        document_type = _ensure_document_type(db, collection, document_type_name)
        document.document_type_id = document_type.id
    if not (locked or _manual_source(sources, "storage_path_id")):
        storage_rule = _ensure_storage_path(db, collection, "Default", "{collection}/{year}")
        document.storage_path_id = storage_rule.id
    record_event(
        db,
        document,
        "paperless_metadata_mapped",
        "Mapped correspondent, document type, and storage path metadata",
        metadata={
            "correspondent_id": str(document.correspondent_id) if document.correspondent_id else None,
            "document_type_id": str(document.document_type_id) if document.document_type_id else None,
            "storage_path_id": str(document.storage_path_id) if document.storage_path_id else None,
        },
    )


def _ensure_correspondent(db: Session, collection: Collection, name: str) -> Correspondent:
    slug = slugify(name)
    row = db.scalars(
        select(Correspondent)
        .where(Correspondent.collection_id == collection.id)
        .where(Correspondent.slug == slug)
    ).first()
    if row:
        return row
    row = Correspondent(collection_id=collection.id, name=name, slug=slug, match_rules={"auto": True})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(Correspondent)
            .where(Correspondent.collection_id == collection.id)
            .where(Correspondent.slug == slug)
        ).one()


def _manual_source(sources: dict, field: str) -> bool:
    value = sources.get(field)
    return isinstance(value, dict) and value.get("source") == "manual"


def _ensure_document_type(db: Session, collection: Collection, name: str) -> DocumentType:
    slug = slugify(name)
    row = db.scalars(
        select(DocumentType)
        .where(DocumentType.collection_id == collection.id)
        .where(DocumentType.slug == slug)
    ).first()
    if row:
        return row
    row = DocumentType(collection_id=collection.id, name=name, slug=slug, match_rules={"collection": name})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(DocumentType)
            .where(DocumentType.collection_id == collection.id)
            .where(DocumentType.slug == slug)
        ).one()


def _ensure_storage_path(db: Session, collection: Collection, name: str, template: str) -> StoragePathRule:
    slug = slugify(name)
    row = db.scalars(
        select(StoragePathRule)
        .where(StoragePathRule.collection_id == collection.id)
        .where(StoragePathRule.slug == slug)
    ).first()
    if row:
        return row
    row = StoragePathRule(collection_id=collection.id, name=name, slug=slug, path_template=template)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(StoragePathRule)
            .where(StoragePathRule.collection_id == collection.id)
            .where(StoragePathRule.slug == slug)
        ).one()
