from __future__ import annotations

import base64
from datetime import date, datetime
import json
import uuid

from sqlalchemy import String, and_, case, cast, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.models import CustomFieldDefinition, Document, DocumentCustomFieldValue, DocumentState, OCRMode, ReviewState, document_tags
from app.schemas import SearchResult


def search_documents(
    db: Session,
    query: str,
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
) -> list[SearchResult]:
    return search_documents_page(
        db,
        query,
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
    )["items"]


def search_documents_page(
    db: Session,
    query: str,
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
) -> dict:
    query = (query or "").strip()
    normalized_limit = max(1, min(limit, 200))
    if not query:
        return {"items": [], "limit": normalized_limit, "next_cursor": None, "total_estimate": 0}

    metadata_rank_expr = _ranking_expression(query)
    if db.bind and db.bind.dialect.name == "postgresql":
        ts_query = func.websearch_to_tsquery("simple", query)
        text_rank_expr = func.ts_rank(text("documents.ocr_search"), ts_query)
        snippet_expr = func.ts_headline(
            "simple",
            func.coalesce(Document.ocr_text, ""),
            ts_query,
            "StartSel=<mark>, StopSel=</mark>, MaxWords=24, MinWords=8",
        )
        stmt = (
            select(Document, snippet_expr.label("snippet"), metadata_rank_expr.label("metadata_rank"), text_rank_expr.label("text_rank"))
            .where(or_(text("documents.ocr_search @@ websearch_to_tsquery('simple', :q)"), _metadata_match_expression(query)))
            .where(Document.deleted_at.is_(None))
            .params(q=query)
        )
    else:
        like = f"%{query.lower()}%"
        text_rank_expr = literal(0.0)
        stmt = (
            select(Document, literal("").label("snippet"), metadata_rank_expr.label("metadata_rank"), text_rank_expr.label("text_rank"))
            .where(
                Document.deleted_at.is_(None),
                or_(
                    func.lower(func.coalesce(Document.ocr_text, "")).like(like),
                    func.lower(func.coalesce(Document.extracted_title, "")).like(like),
                    func.lower(Document.original_filename).like(like),
                    func.lower(func.coalesce(Document.llm_summary, "")).like(like),
                    func.lower(cast(Document.llm_keywords, String)).like(like),
                    func.lower(cast(Document.llm_entities, String)).like(like),
                    func.lower(func.coalesce(Document.llm_document_purpose, "")).like(like),
                    func.lower(func.coalesce(Document.llm_suggested_folder, "")).like(like),
                ),
            )
        )

    stmt = _apply_filters(stmt, collection_name, status, date_from, date_to, filename, title, custom_field, custom_value, correspondent_id, document_type_id, tag_id, storage_path_id, folder_id, ocr_mode, review_state)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    stmt = _apply_search_cursor(stmt, cursor, metadata_rank_expr, text_rank_expr)
    rows = db.execute(
        stmt.order_by(metadata_rank_expr.desc(), text_rank_expr.desc(), Document.created_at.desc(), Document.id.desc()).limit(normalized_limit + 1)
    ).all()
    page_rows = rows[:normalized_limit]
    items = [_to_result(document, row_snippet or "", query, float(metadata_rank or 0)) for document, row_snippet, metadata_rank, _text_rank in page_rows]
    next_cursor = None
    if len(rows) > normalized_limit and page_rows:
        document, _snippet, metadata_rank, text_rank = page_rows[-1]
        next_cursor = _encode_search_cursor(document, float(metadata_rank or 0), float(text_rank or 0))
    return {"items": items, "limit": normalized_limit, "next_cursor": next_cursor, "total_estimate": int(total)}


def _apply_filters(
    stmt,
    collection_name: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    filename: str | None,
    title: str | None,
    custom_field: str | None,
    custom_value: str | None,
    correspondent_id: str | None,
    document_type_id: str | None,
    tag_id: str | None,
    storage_path_id: str | None,
    folder_id: str | None,
    ocr_mode: str | None,
    review_state: str | None,
):
    if collection_name:
        stmt = stmt.where(Document.collection_name == collection_name)
    if status:
        stmt = stmt.where(Document.processing_state == DocumentState(status))
    if date_from:
        stmt = stmt.where(func.date(Document.created_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(Document.created_at) <= date_to)
    if filename:
        stmt = stmt.where(func.lower(Document.original_filename).like(f"%{filename.lower()}%"))
    if title:
        stmt = stmt.where(func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")).like(f"%{title.lower()}%"))
    if custom_field and custom_value:
        stmt = (
            stmt.join(DocumentCustomFieldValue, DocumentCustomFieldValue.document_id == Document.id)
            .join(CustomFieldDefinition, CustomFieldDefinition.id == DocumentCustomFieldValue.custom_field_definition_id)
            .where(CustomFieldDefinition.slug == custom_field)
            .where(CustomFieldDefinition.searchable.is_(True))
            .where(func.lower(func.coalesce(DocumentCustomFieldValue.normalized_value, "")).like(f"%{custom_value.lower()}%"))
        )
    if correspondent_id:
        stmt = stmt.where(Document.correspondent_id == _uuid(correspondent_id))
    if document_type_id:
        stmt = stmt.where(Document.document_type_id == _uuid(document_type_id))
    if storage_path_id:
        stmt = stmt.where(Document.storage_path_id == _uuid(storage_path_id))
    if folder_id:
        stmt = stmt.where(Document.folder_id == _uuid(folder_id))
    if ocr_mode:
        stmt = stmt.where(Document.ocr_mode == OCRMode(ocr_mode))
    if review_state:
        stmt = stmt.where(Document.review_state == ReviewState(review_state))
    if tag_id:
        stmt = stmt.join(document_tags, document_tags.c.document_id == Document.id).where(document_tags.c.tag_id == _uuid(tag_id))
    if (custom_field and custom_value) or tag_id:
        stmt = stmt.distinct()
    return stmt


def _apply_search_cursor(stmt, cursor: str | None, metadata_rank_expr, text_rank_expr):
    decoded = _decode_search_cursor(cursor)
    if decoded is None:
        return stmt
    metadata_rank, text_rank, created_at, row_id = decoded
    return stmt.where(or_(
        metadata_rank_expr < metadata_rank,
        and_(metadata_rank_expr == metadata_rank, text_rank_expr < text_rank),
        and_(metadata_rank_expr == metadata_rank, text_rank_expr == text_rank, Document.created_at < created_at),
        and_(metadata_rank_expr == metadata_rank, text_rank_expr == text_rank, Document.created_at == created_at, Document.id < row_id),
    ))


def _encode_search_cursor(document: Document, metadata_rank: float, text_rank: float) -> str:
    payload = {"metadata_rank": metadata_rank, "text_rank": text_rank, "created_at": document.created_at.isoformat(), "id": str(document.id)}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


def _decode_search_cursor(cursor: str | None) -> tuple[float, float, datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return (
            float(payload["metadata_rank"]),
            float(payload.get("text_rank", 0.0)),
            datetime.fromisoformat(str(payload["created_at"])),
            uuid.UUID(str(payload["id"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc


def _uuid(value: str):
    return uuid.UUID(value) if isinstance(value, str) else value


def _ranking_expression(query: str):
    q = query.lower()
    return case(
        (func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")) == q, 100),
        (func.lower(Document.original_filename) == q, 90),
        (func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")).like(f"%{q}%"), 60),
        (func.lower(Document.original_filename).like(f"%{q}%"), 50),
        (func.lower(cast(Document.metadata_json, String)).like(f"%{q}%"), 30),
        (func.lower(func.coalesce(Document.llm_summary, "")).like(f"%{q}%"), 25),
        (func.lower(cast(Document.llm_keywords, String)).like(f"%{q}%"), 25),
        (func.lower(cast(Document.llm_entities, String)).like(f"%{q}%"), 20),
        else_=0,
    )


def _metadata_match_expression(query: str):
    q = f"%{query.lower()}%"
    return or_(
        func.lower(func.coalesce(Document.manual_title_override, Document.extracted_title, "")).like(q),
        func.lower(Document.original_filename).like(q),
        func.lower(cast(Document.metadata_json, String)).like(q),
        func.lower(func.coalesce(Document.llm_summary, "")).like(q),
        func.lower(cast(Document.llm_keywords, String)).like(q),
        func.lower(cast(Document.llm_entities, String)).like(q),
        func.lower(func.coalesce(Document.llm_document_purpose, "")).like(q),
        func.lower(func.coalesce(Document.llm_suggested_folder, "")).like(q),
    )


def _metadata_rank(document: Document, query: str) -> float:
    q = query.lower()
    display = (document.manual_title_override or document.extracted_title or "").lower()
    filename = document.original_filename.lower()
    metadata = str(document.metadata_json or {}).lower()
    llm = " ".join(
        [
            str(document.llm_summary or ""),
            str(document.llm_keywords or ""),
            str(document.llm_entities or ""),
            str(document.llm_document_purpose or ""),
            str(document.llm_suggested_folder or ""),
        ]
    ).lower()
    if display == q:
        return 100.0
    if filename == q:
        return 90.0
    if q in display:
        return 60.0
    if q in filename:
        return 50.0
    if q in metadata:
        return 30.0
    if q in llm:
        return 25.0
    return 0.0


def _plain_snippet(text_value: str, query: str) -> str:
    text_value = " ".join((text_value or "").split())
    if not text_value:
        return ""
    idx = text_value.lower().find(query.lower())
    if idx < 0:
        return text_value[:180]
    start = max(0, idx - 70)
    end = min(len(text_value), idx + len(query) + 90)
    return text_value[start:end]


def _to_result(document: Document, snippet: str, query: str, rank: float = 0.0) -> SearchResult:
    return SearchResult(
        document_id=document.id,
        batch_id=document.batch_id,
        record_id=document.record_id,
        record_title=document.record.title if document.record else None,
        folder_id=document.folder_id,
        folder_path=document.folder.path if document.folder else None,
        collection_name=document.collection_name,
        extracted_title=document.manual_title_override or document.extracted_title,
        original_filename=document.original_filename,
        status=document.processing_state,
        correspondent_id=document.correspondent_id,
        document_type_id=document.document_type_id,
        storage_path_id=document.storage_path_id,
        ocr_mode=document.ocr_mode,
        review_state=document.review_state,
        snippet=snippet or _plain_snippet(document.ocr_text or "", query),
        created_at=document.created_at,
        rank=rank,
    )
