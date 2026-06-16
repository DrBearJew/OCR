from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_admin
from app.db import get_db
from app.models import Collection, CustomFieldDefinition, Document, Record
from app.schemas import (
    CollectionCreate,
    CollectionRead,
    CollectionUpdate,
    CustomFieldDefinitionRead,
    CustomFieldDefinitionWrite,
)
from app.services.collections import DEFAULT_COLLECTIONS, ensure_collection, seed_default_collections, slugify


router = APIRouter(prefix="/api/collections", tags=["collections"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[CollectionRead])
def list_collections(db: Session = Depends(get_db)) -> list[CollectionRead]:
    seed_default_collections(db)
    rows = db.scalars(select(Collection).order_by(Collection.name.asc())).all()
    return [CollectionRead.model_validate(row) for row in rows]


@router.post("", response_model=CollectionRead, status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)) -> CollectionRead:
    slug = payload.slug or slugify(payload.name)
    existing = db.scalars(select(Collection).where((Collection.name == payload.name) | (Collection.slug == slug))).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Collection already exists")
    collection = Collection(name=payload.name, slug=slug)
    db.add(collection)
    collection.icon = payload.icon
    collection.color = payload.color
    collection.title_generation_rule = payload.title_generation_rule
    collection.extraction_rules = payload.extraction_rules
    collection.validation_rules = payload.validation_rules
    collection.display_config = payload.display_config
    collection.search_defaults = payload.search_defaults
    db.commit()
    db.refresh(collection)
    return CollectionRead.model_validate(collection)


@router.delete("/{collection_id}", response_model=CollectionRead)
def delete_collection(collection_id: uuid.UUID, db: Session = Depends(get_db)) -> CollectionRead:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if collection.name in DEFAULT_COLLECTIONS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Default schemas cannot be deleted")
    record_count = db.scalar(
        select(func.count())
        .select_from(Record)
        .where(Record.collection_id == collection.id)
        .where(Record.deleted_at.is_(None))
    ) or 0
    document_count = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.collection_name == collection.name)
        .where(Document.deleted_at.is_(None))
    ) or 0
    if record_count or document_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only unused schemas can be deleted; found {record_count} records and {document_count} documents",
        )
    deleted = CollectionRead.model_validate(collection)
    db.delete(collection)
    db.commit()
    return deleted


@router.patch("/{collection_id}", response_model=CollectionRead)
def update_collection(collection_id: uuid.UUID, payload: CollectionUpdate, db: Session = Depends(get_db)) -> CollectionRead:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("slug") == "":
        updates["slug"] = slugify(updates.get("name") or collection.name)
    if "name" in updates and "slug" not in updates:
        updates["slug"] = slugify(updates["name"])
    for key, value in updates.items():
        setattr(collection, key, value)
    db.commit()
    db.refresh(collection)
    return CollectionRead.model_validate(collection)


@router.get("/{collection_id}/fields", response_model=list[CustomFieldDefinitionRead])
def list_custom_fields(collection_id: uuid.UUID, db: Session = Depends(get_db)) -> list[CustomFieldDefinitionRead]:
    stmt = (
        select(CustomFieldDefinition)
        .where(CustomFieldDefinition.collection_id == collection_id)
        .order_by(CustomFieldDefinition.display_order.asc(), CustomFieldDefinition.name.asc())
    )
    return [CustomFieldDefinitionRead.model_validate(row) for row in db.scalars(stmt).all()]


@router.post("/{collection_id}/fields", response_model=CustomFieldDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_custom_field(collection_id: uuid.UUID, payload: CustomFieldDefinitionWrite, db: Session = Depends(get_db)) -> CustomFieldDefinitionRead:
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    field = CustomFieldDefinition(collection_id=collection.id, **payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return CustomFieldDefinitionRead.model_validate(field)


@router.patch("/{collection_id}/fields/{field_id}", response_model=CustomFieldDefinitionRead)
def update_custom_field(collection_id: uuid.UUID, field_id: uuid.UUID, payload: CustomFieldDefinitionWrite, db: Session = Depends(get_db)) -> CustomFieldDefinitionRead:
    field = db.get(CustomFieldDefinition, field_id)
    if field is None or field.collection_id != collection_id:
        raise HTTPException(status_code=404, detail="Field not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, key, value)
    db.commit()
    db.refresh(field)
    return CustomFieldDefinitionRead.model_validate(field)


@router.delete("/{collection_id}/fields/{field_id}")
def delete_custom_field(collection_id: uuid.UUID, field_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    field = db.get(CustomFieldDefinition, field_id)
    if field is None or field.collection_id != collection_id:
        raise HTTPException(status_code=404, detail="Field not found")
    db.delete(field)
    db.commit()
    return {"ok": True}
