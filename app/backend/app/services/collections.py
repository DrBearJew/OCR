from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BatchStatus,
    Collection,
    CustomFieldDefinition,
    CustomFieldType,
    Document,
    DocumentCustomFieldValue,
    DocumentState,
    FieldValueSource,
    Record,
    ReviewState,
)
from app.services.events import record_event
from app.services.status import derive_parent_status


DEFAULT_COLLECTIONS = ("Belege", "Eingangsrechnung", "Ausgangsrechnung", "Dokumente")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "collection"


def ensure_collection(db: Session, name: str) -> Collection:
    slug = slugify(name)
    collection = db.scalars(select(Collection).where(Collection.slug == slug)).first()
    if collection:
        return collection
    collection = Collection(
        name=name,
        slug=slug,
        title_generation_rule={"collection": name},
        extraction_rules={"collection": name},
        validation_rules={},
        display_config={"visible_core_fields": ["title", "sender", "recipient", "invoice_number", "date", "amount"]},
        search_defaults={"searchable": ["ocr_text", "title", "filename"]},
        ocr_config_json={"ocr_mode": "redo", "language": "deu+eng"},
    )
    db.add(collection)
    db.flush()
    return collection


def seed_default_collections(db: Session) -> None:
    for name in DEFAULT_COLLECTIONS:
        ensure_collection(db, name)
    db.commit()


def create_record_for_upload(db: Session, collection: Collection, title: str | None = None) -> Record:
    record = Record(collection_id=collection.id, title=title or "Untitled", status=BatchStatus.pending)
    db.add(record)
    db.flush()
    return record


def update_record_status(db: Session, record_id: uuid.UUID | None) -> BatchStatus | None:
    if record_id is None:
        return None
    record = db.get(Record, record_id)
    if record is None:
        return None
    documents = db.scalars(select(Document).where(Document.record_id == record_id).where(Document.deleted_at.is_(None))).all()
    status = derive_parent_status(documents)
    record.status = status
    record.document_count = len(documents)
    first_title = next((doc.manual_title_override or doc.extracted_title for doc in documents if doc.manual_title_override or doc.extracted_title), None)
    if first_title and (record.title == "Untitled" or not record.title):
        record.title = first_title
    record.summary_metadata = _summary_metadata(documents)
    return status


def upsert_custom_field_value(
    db: Session,
    document: Document,
    field_definition: CustomFieldDefinition,
    raw_value: Any,
    *,
    source: FieldValueSource = FieldValueSource.deterministic,
    confidence: int | None = None,
    force: bool = False,
) -> DocumentCustomFieldValue:
    value = db.scalars(
        select(DocumentCustomFieldValue)
        .where(DocumentCustomFieldValue.document_id == document.id)
        .where(DocumentCustomFieldValue.custom_field_definition_id == field_definition.id)
    ).first()
    normalized = normalize_custom_field_value(field_definition, raw_value)
    if value is None:
        value = DocumentCustomFieldValue(
            document_id=document.id,
            custom_field_definition_id=field_definition.id,
        )
        db.add(value)
    elif value.locked and not force:
        record_event(
            db,
            document,
            "custom_field_locked_skip",
            "Custom field locked; candidate value was not overwritten",
            metadata={"field": field_definition.slug, "candidate": normalized},
        )
        return value
    old = {"raw_value": value.raw_value, "normalized_value": value.normalized_value}
    value.raw_value = "" if raw_value is None else str(raw_value)
    value.normalized_value = normalized
    value.source = source
    value.confidence = confidence
    record_event(
        db,
        document,
        "custom_field_value_saved",
        "Custom field value saved",
        old_value=old,
        new_value={"field": field_definition.slug, "normalized_value": normalized, "source": source.value},
    )
    return value


def normalize_custom_field_value(field: CustomFieldDefinition, raw_value: Any) -> str | None:
    if raw_value is None or raw_value == "":
        return field.default_value
    value = str(raw_value).strip()
    if field.field_type == CustomFieldType.boolean:
        return "true" if value.lower() in {"1", "true", "yes", "ja", "y"} else "false"
    if field.field_type == CustomFieldType.number:
        return value.replace(",", ".")
    if field.field_type == CustomFieldType.select:
        options = [str(item) for item in (field.enum_options or [])]
        if options and value not in options:
            raise ValueError(f"{value} is not a valid option for {field.slug}")
    return value

def _summary_metadata(documents: list[Document]) -> dict:
    return {
        "titles": [doc.manual_title_override or doc.extracted_title for doc in documents if doc.manual_title_override or doc.extracted_title][:5],
        "collections": sorted({doc.collection_name for doc in documents}),
        "failed": sum(1 for doc in documents if doc.processing_state == DocumentState.failed),
        "complete": sum(1 for doc in documents if doc.processing_state == DocumentState.complete),
    }
