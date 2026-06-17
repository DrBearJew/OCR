from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, ReviewState
from app.services.events import record_event
from app.services.llm_qwen import QwenProviderError, build_qwen_provider, parse_json_suggestion


CORE_CANDIDATE_FIELDS = (
    "correspondent",
    "sender",
    "recipient",
    "document_type",
    "created_date",
    "invoice_number",
    "amount",
    "currency",
    "payment_method",
    "suggested_title_base",
)

QWEN_PROMPT_OMIT_METADATA_KEYS = {
    "qwen_refinement",
    "qwen_candidates",
    "merged_sources",
    "review_warnings",
    "missing_required_fields",
    "metadata_resolution",
}


def find_similar_documents(
    db: Session,
    document: Document,
    deterministic_metadata: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Small DB-backed context retrieval for Qwen; no vector stack required."""
    deterministic_metadata = deterministic_metadata or {}
    terms = [
        document.extracted_sender,
        document.extracted_recipient,
        document.extracted_invoice_number,
        document.extracted_title,
        deterministic_metadata.get("sender"),
        deterministic_metadata.get("recipient"),
        deterministic_metadata.get("invoice_number"),
        deterministic_metadata.get("title"),
        deterministic_metadata.get("amount"),
        deterministic_metadata.get("date"),
    ]
    ocr_terms = _ocr_context_terms(document.ocr_text or "")
    seen_terms: set[str] = set()
    title_terms: list[str] = []
    for term in [*terms, *ocr_terms]:
        if not isinstance(term, str) or not term.strip():
            continue
        normalized = term.strip().lower()
        if normalized in seen_terms:
            continue
        seen_terms.add(normalized)
        title_terms.append(normalized)
    stmt = (
        select(Document)
        .where(Document.id != document.id)
        .where(Document.deleted_at.is_(None))
        .where(Document.collection_name == document.collection_name)
        .order_by(Document.created_at.desc())
    )
    if title_terms:
        clauses = []
        for term in title_terms[:8]:
            like = f"%{term}%"
            clauses.extend(
                [
                    func.lower(func.coalesce(Document.extracted_title, "")).like(like),
                    func.lower(func.coalesce(Document.manual_title_override, "")).like(like),
                    func.lower(func.coalesce(Document.extracted_sender, "")).like(like),
                    func.lower(func.coalesce(Document.extracted_recipient, "")).like(like),
                    func.lower(func.coalesce(Document.ocr_text, "")).like(like),
                ]
            )
        stmt = stmt.where(or_(*clauses))
    rows = db.scalars(stmt.limit(limit)).all()
    return [_similar_doc_payload(row) for row in rows]


def build_qwen_metadata_payload(
    db: Session,
    document: Document,
    deterministic_metadata: dict[str, Any],
    processing_options: dict[str, Any],
) -> dict[str, Any]:
    collection = document.record.collection if document.record else None
    custom_fields = []
    if collection:
        custom_fields = [
            {
                "name": field.name,
                "slug": field.slug,
                "type": field.field_type.value,
                "required": field.required,
                "searchable": field.searchable,
                "default": field.default_value,
                "enum_options": field.enum_options or [],
                "validation": field.validation_rules or {},
                "extraction_binding": field.extraction_binding or {},
            }
            for field in sorted(collection.custom_fields, key=lambda item: item.display_order)
        ]
    return {
        "collection_name": document.collection_name,
        "title": _qwen_prompt_title(document),
        "ocr_text": document.ocr_text or "",
        "collection_schema": {
            "name": collection.name if collection else document.collection_name,
            "slug": collection.slug if collection else "",
            "validation_rules": collection.validation_rules if collection else {},
            "display_config": collection.display_config if collection else {},
        },
        "title_rule": collection.title_generation_rule if collection else {"collection": document.collection_name},
        "custom_fields": custom_fields,
        "deterministic_metadata": _sanitize_qwen_prompt_metadata(deterministic_metadata),
        "manual_locked_fields": {
            "current_sources": document.metadata_sources_json or {},
            "locks": document.field_locks_json or {},
            "metadata_locked": document.metadata_locked,
            "manual_title_override": document.manual_title_override,
        },
        "similar_documents": find_similar_documents(db, document, deterministic_metadata),
        "processing_options": processing_options,
    }


def qwen_generate_metadata_candidates(
    db: Session,
    document: Document,
    deterministic_metadata: dict[str, Any],
    processing_options: dict[str, Any],
    *,
    provider: Any | None = None,
) -> dict[str, Any]:
    provider = provider if provider is not None else build_qwen_provider()
    payload = build_qwen_metadata_payload(db, document, deterministic_metadata, processing_options)
    try:
        generate = getattr(provider, "generate_metadata_candidates", None)
        if generate is None:
            # Compatibility with older tests/providers that only expose custom-field refinement.
            generate = getattr(provider, "refine_metadata", None)
        if generate is None:
            # Compatibility with the previous second-brain-only provider shape.
            generate = getattr(provider, "enrich_metadata", None)
        if generate is None:
            raise QwenProviderError("Qwen provider does not implement metadata candidates")
        refinement = generate(payload)
    except QwenProviderError as exc:
        record_event(db, document, "qwen_unavailable", "Qwen metadata brain unavailable", metadata={"reason": str(exc)})
        return {
            "ok": False,
            "error": str(exc),
            "candidate": {},
            "payload": payload,
            "similar_documents": payload["similar_documents"],
        }

    if not refinement.raw_text.strip():
        return {
            "ok": False,
            "candidate": {},
            "raw_text": refinement.raw_text,
            "raw_response": refinement.raw_response,
            "prompt": {"name": refinement.prompt.name, "version": refinement.prompt.version},
            "model": {"role": "qwen_metadata_brain", "endpoint": refinement.endpoint, "model": refinement.model},
            "payload": payload,
            "similar_documents": payload["similar_documents"],
            "empty_response": True,
            "error": "Qwen returned empty metadata candidate response",
        }

    parsed = parse_json_suggestion(refinement.raw_text)
    candidate = validate_metadata_candidates(parsed)
    debug = {
        "ok": candidate is not None,
        "candidate": candidate or {},
        "raw_text": refinement.raw_text,
        "raw_response": refinement.raw_response,
        "prompt": {"name": refinement.prompt.name, "version": refinement.prompt.version},
        "model": {"role": "qwen_metadata_brain", "endpoint": refinement.endpoint, "model": refinement.model},
        "payload": payload,
        "similar_documents": payload["similar_documents"],
    }
    if candidate is None:
        debug["error"] = "Qwen returned invalid metadata candidate JSON"
    return debug


def run_qwen_secondbrain_enrichment(
    db: Session,
    document: Document,
    *,
    provider: Any | None = None,
    enabled: bool | None = None,
) -> bool:
    """Compatibility wrapper that now stores search/RAG metadata from the metadata brain."""
    settings = get_settings()
    if enabled is None:
        enabled = settings.llm_metadata_refinement_enabled
    if not enabled:
        record_event(db, document, "qwen_enrichment_skipped", "Qwen search metadata disabled")
        return False

    deterministic_metadata = {
        "sender": document.extracted_sender,
        "recipient": document.extracted_recipient,
        "invoice_number": document.extracted_invoice_number,
        "date": document.extracted_date,
        "amount": document.extracted_amount,
        "payment_method": document.extracted_payment_method,
        "metadata": document.metadata_json or {},
    }
    result = qwen_generate_metadata_candidates(
        db,
        document,
        deterministic_metadata,
        {"qwen_enrichment_enabled": True},
        provider=provider,
    )
    if not result.get("ok"):
        document.llm_raw_response = {
            **(document.llm_raw_response or {}),
            "invalid": bool(result.get("raw_text")),
            "raw_text": result.get("raw_text"),
            "raw_response": result.get("raw_response"),
            "metadata_brain_error": result.get("error"),
            "similar_documents": result.get("similar_documents", []),
        }
        record_event(db, document, "qwen_enrichment_unavailable", "Qwen search metadata unavailable", metadata={"reason": result.get("error")})
        return False

    apply_qwen_search_metadata(document, result["candidate"], result)
    record_event(
        db,
        document,
        "qwen_enrichment_done",
        "Qwen metadata brain search hints saved",
        metadata={"suggested_folder": document.llm_suggested_folder, "confidence": document.llm_confidence},
    )
    return True


def validate_metadata_candidates(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or "text" in value:
        if isinstance(value, list):
            return _candidate_from_custom_field_list(value)
        return None

    candidate: dict[str, Any] = {}
    for field in CORE_CANDIDATE_FIELDS:
        candidate[field] = _field_candidate(value.get(field), value.get("confidence"), field)

    legacy_metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    for field, keys in {
        "sender": ("sender", "correspondent", "vendor", "issuer"),
        "recipient": ("recipient", "customer"),
        "invoice_number": ("invoice_number", "invoiceNo", "invoice_no"),
        "created_date": ("date", "invoice_date", "created_date"),
        "amount": ("amount", "total", "gross_amount"),
        "payment_method": ("payment_method", "zahlart"),
    }.items():
        if candidate[field]["value"]:
            continue
        for key in keys:
            if key in legacy_metadata:
                candidate[field] = _field_candidate(legacy_metadata[key], value.get("confidence"), field)
                break

    candidate["custom_fields"] = _custom_field_candidates(value.get("custom_fields"))
    if not candidate["custom_fields"] and isinstance(value.get("fields"), list):
        candidate["custom_fields"] = _custom_field_candidates(value.get("fields"))
    candidate["suggested_tags"] = _string_list(value.get("suggested_tags"))
    candidate["suggested_folder"] = _string(value.get("suggested_folder"))
    candidate["search_keywords"] = _string_list(value.get("search_keywords") or value.get("keywords"))
    candidate["summary"] = _string(value.get("summary"))
    candidate["entities"] = _entities(value.get("entities"))
    candidate["document_purpose"] = _string(value.get("document_purpose"))
    candidate["related_search_queries"] = _string_list(value.get("related_search_queries") or value.get("related_query"))
    candidate["uncertain_fields"] = _string_list(value.get("uncertain_fields"))
    candidate["confidence"] = _confidence(value.get("confidence"))
    return candidate


def candidate_to_metadata_suggestion(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = {}
    confidence = {}
    evidence = {}
    mapping = {
        "sender": "sender",
        "correspondent": "sender",
        "recipient": "recipient",
        "invoice_number": "invoice_number",
        "created_date": "date",
        "amount": "amount",
        "payment_method": "payment_method",
        "suggested_title_base": "title_base",
    }
    for source_key, target_key in mapping.items():
        item = candidate.get(source_key)
        if not isinstance(item, dict) or not item.get("value"):
            continue
        if target_key == "sender" and metadata.get("sender") and source_key == "correspondent":
            continue
        metadata[target_key] = str(item["value"]).strip()
        confidence[target_key] = item.get("confidence")
        evidence[target_key] = item.get("evidence")
    currency = candidate.get("currency")
    if isinstance(currency, dict) and currency.get("value"):
        metadata["currency"] = str(currency["value"]).strip()
        confidence["currency"] = currency.get("confidence")
    document_type = candidate.get("document_type")
    if isinstance(document_type, dict) and document_type.get("value"):
        metadata["document_type"] = str(document_type["value"]).strip()
        confidence["document_type"] = document_type.get("confidence")
        evidence["document_type"] = document_type.get("evidence")
    return {"metadata": metadata, "confidence": confidence, "evidence": evidence}


def apply_qwen_search_metadata(document: Document, candidate: dict[str, Any], debug: dict[str, Any]) -> None:
    document.llm_summary = candidate.get("summary") or document.llm_summary
    document.llm_keywords = candidate.get("search_keywords") or document.llm_keywords or []
    document.llm_entities = candidate.get("entities") or document.llm_entities or {}
    document.llm_document_purpose = candidate.get("document_purpose") or document.llm_document_purpose
    document.llm_suggested_tags = candidate.get("suggested_tags") or document.llm_suggested_tags or []
    document.llm_suggested_folder = candidate.get("suggested_folder") or document.llm_suggested_folder
    document.llm_related_query = candidate.get("related_search_queries") or document.llm_related_query or []
    document.llm_confidence = candidate.get("confidence") or document.llm_confidence
    document.llm_raw_response = {
        **(document.llm_raw_response or {}),
        "metadata_brain": {
            "parsed": candidate,
            "raw_response": debug.get("raw_response"),
            "similar_documents": debug.get("similar_documents", []),
            "uncertain_fields": candidate.get("uncertain_fields", []),
        },
    }


def qwen_extract_correspondent(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("correspondent") or candidate.get("sender") or {}


def qwen_extract_created_date(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("created_date") or {}


def qwen_extract_document_type(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("document_type") or {}


def qwen_extract_custom_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    return candidate.get("custom_fields") or {}


def qwen_generate_search_metadata(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": candidate.get("summary") or "",
        "keywords": candidate.get("search_keywords") or [],
        "entities": candidate.get("entities") or {},
        "document_purpose": candidate.get("document_purpose") or "",
        "related_search_queries": candidate.get("related_search_queries") or [],
    }


def qwen_suggest_folder_and_tags(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "suggested_folder": candidate.get("suggested_folder") or "",
        "suggested_tags": candidate.get("suggested_tags") or [],
    }


def qwen_interpret_search_query(candidate: dict[str, Any]) -> dict[str, Any]:
    return {"related_search_queries": candidate.get("related_search_queries") or []}


def _candidate_from_custom_field_list(value: list[Any]) -> dict[str, Any] | None:
    custom_fields: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        slug = item.get("field") or item.get("field_slug") or item.get("name")
        if slug:
            custom_fields[str(slug)] = _field_candidate(item.get("value"), item.get("confidence"), str(slug))
    if not custom_fields:
        return None
    empty = {field: _field_candidate(None, None, field) for field in CORE_CANDIDATE_FIELDS}
    return {
        **empty,
        "custom_fields": custom_fields,
        "suggested_tags": [],
        "suggested_folder": "",
        "search_keywords": [],
        "summary": "",
        "entities": _entities({}),
        "document_purpose": "",
        "related_search_queries": [],
        "uncertain_fields": [],
        "confidence": None,
    }


def _field_candidate(value: Any, confidence_source: Any = None, field_name: str | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        raw_confidence = value.get("confidence", confidence_source)
        return {
            "value": _string(value.get("value")),
            "confidence": _confidence(raw_confidence),
            "evidence": _string(value.get("evidence")),
        }
    confidence = confidence_source.get(field_name) if isinstance(confidence_source, dict) and field_name else confidence_source
    return {"value": _string(value), "confidence": _confidence(confidence), "evidence": ""}


def _custom_field_candidates(value: Any) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        for slug, raw in value.items():
            fields[str(slug)] = _field_candidate(raw, None, str(slug))
    elif isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            slug = item.get("field_slug") or item.get("field") or item.get("slug") or item.get("name")
            if slug:
                fields[str(slug)] = _field_candidate(item, item.get("confidence"), str(slug))
    return {slug: candidate for slug, candidate in fields.items() if candidate.get("value")}


def _qwen_prompt_title(document: Document) -> str:
    """Return non-stale title context for Qwen.

    Generated titles are derived outputs and may contain stale fallback segments.
    Only manual overrides are authoritative title input; otherwise use the original
    filename as weak context while deterministic_metadata carries fresh parser candidates.
    """
    if document.manual_title_override:
        return document.manual_title_override
    return document.original_filename or ""


def _similar_doc_payload(document: Document) -> dict[str, Any]:
    folder_path = document.folder.path if document.folder else None
    return {
        "id": str(document.id),
        "title": document.manual_title_override or document.extracted_title,
        "filename": document.original_filename,
        "collection": document.collection_name,
        "sender": document.extracted_sender,
        "recipient": document.extracted_recipient,
        "invoice_number": document.extracted_invoice_number,
        "date": document.extracted_date,
        "amount": document.extracted_amount,
        "folder": folder_path,
        "keywords": document.llm_keywords or [],
    }


def _ocr_context_terms(text: str) -> list[str]:
    words: list[str] = []
    for raw in text.replace("\n", " ").split():
        word = "".join(char for char in raw if char.isalnum() or char in {"-", "_"}).strip("-_")
        if len(word) < 5:
            continue
        lower = word.lower()
        if lower in {"rechnung", "datum", "betrag", "gesamt", "rechnungsnummer"}:
            continue
        words.append(word)
        if len(words) >= 6:
            break
    return words


def _entities(value: Any) -> dict[str, list[str]]:
    entities = value if isinstance(value, dict) else {}
    return {key: _string_list(entities.get(key)) for key in ["people", "organizations", "locations", "dates", "amounts"]}


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()[:4000]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:160] for item in value if str(item).strip()][:40]


def _confidence(value: Any) -> int | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if numeric <= 1:
            numeric *= 100
        return max(0, min(100, int(round(numeric))))
    except (TypeError, ValueError):
        return None


def _sanitize_qwen_prompt_metadata(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in (value or {}).items():
        if key in QWEN_PROMPT_OMIT_METADATA_KEYS:
            continue
        if key == "metadata" and isinstance(item, dict):
            cleaned[key] = {
                metadata_key: metadata_value
                for metadata_key, metadata_value in item.items()
                if metadata_key not in QWEN_PROMPT_OMIT_METADATA_KEYS
            }
        else:
            cleaned[key] = item
    return cleaned


def uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
