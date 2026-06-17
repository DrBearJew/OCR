from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.db import get_db
from app.schemas import SearchResult, SearchResultPage
from app.services.search import search_documents, search_documents_page


router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_admin)])


@router.get("/page", response_model=SearchResultPage)
def search_page(
    q: str,
    collection_name: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    filename: str | None = None,
    title: str | None = None,
    custom_field: str | None = None,
    custom_value: str | None = None,
    correspondent_id: str | None = None,
    document_type_id: str | None = None,
    tag_id: str | None = None,
    storage_path_id: str | None = None,
    folder_id: str | None = None,
    ocr_mode: str | None = None,
    review_state: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
    db: Session = Depends(get_db),
) -> SearchResultPage:
    try:
        return SearchResultPage.model_validate(search_documents_page(
            db,
            q,
            collection_name=collection_name,
            status=status,
            date_from=date_from,
            date_to=date_to,
            filename=filename,
            title=title,
            custom_field=custom_field,
            custom_value=custom_value,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_id=tag_id,
            storage_path_id=storage_path_id,
            folder_id=folder_id,
            ocr_mode=ocr_mode,
            review_state=review_state,
            limit=limit,
            cursor=cursor,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[SearchResult])
def search(
    q: str,
    collection_name: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    filename: str | None = None,
    title: str | None = None,
    custom_field: str | None = None,
    custom_value: str | None = None,
    correspondent_id: str | None = None,
    document_type_id: str | None = None,
    tag_id: str | None = None,
    storage_path_id: str | None = None,
    folder_id: str | None = None,
    ocr_mode: str | None = None,
    review_state: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
) -> list[SearchResult]:
    try:
        return search_documents(
            db,
            q,
            collection_name=collection_name,
            status=status,
            date_from=date_from,
            date_to=date_to,
            filename=filename,
            title=title,
            custom_field=custom_field,
            custom_value=custom_value,
            correspondent_id=correspondent_id,
            document_type_id=document_type_id,
            tag_id=tag_id,
            storage_path_id=storage_path_id,
            folder_id=folder_id,
            ocr_mode=ocr_mode,
            review_state=review_state,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
