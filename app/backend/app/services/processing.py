from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Batch, BatchStatus, Document, DocumentPage, DocumentState, FieldValueSource, HookStage, OCRMode, ReviewState, StageState
from app.services.events import append_processing_log, record_event
from app.services.collections import update_record_status, upsert_custom_field_value
from app.services.document_assets import render_pdf_pages
from app.services.extraction import ExtractionInput, apply_shared_title_to_result, extract_metadata, sanitize_shared_title_base
from app.services.hooks import execute_hooks
from app.services.folders import auto_folder_path_for_document, ensure_folder_path
from app.services.llm_enrichment import (
    apply_qwen_search_metadata,
    candidate_to_metadata_suggestion,
    qwen_generate_metadata_candidates,
)
from app.services.llm_qwen import build_qwen_provider
from app.services.model_setup import settings_with_model_setup
from app.services.ocr_glm import OCRProvider, OCRProviderError, build_ocr_provider
from app.services.ocr_pipeline import resolve_ocr_config, store_effective_ocr_trace
from app.services.paperless_metadata import apply_paperless_metadata
from app.services.shared_titles import title_is_locked
from app.services.status import derive_parent_status

logger = logging.getLogger(__name__)


CORE_FIELD_ATTRS = {
    "title": "extracted_title",
    "sender": "extracted_sender",
    "recipient": "extracted_recipient",
    "invoice_number": "extracted_invoice_number",
    "date": "extracted_date",
    "amount": "extracted_amount",
    "payment_method": "extracted_payment_method",
}

DEFAULT_PROCESSING_OPTIONS = {
    "auto_ocr": True,
    "auto_process": False,
    "qwen_enabled": None,
    "qwen_enrichment_enabled": None,
    "auto_folder_enabled": False,
    "use_qwen_folder_suggestion": False,
    "overwrite_manual_values": False,
    "preserve_locked_fields": True,
    "skip_metadata": False,
    "extract_tables": False,
    "collection_rules_enabled": True,
}

ACTIVE_PROCESSING_STATES = {
    DocumentState.queued_for_ocr,
    DocumentState.ocr_processing,
    DocumentState.metadata_processing,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def has_active_processing_lease(document: Document, *, stage: str | None = None, now: datetime | None = None) -> bool:
    now = now or _now()
    lease_until = _aware(document.processing_lease_until)
    if lease_until is None or lease_until <= now:
        return False
    if stage and document.current_stage not in {stage, "process"}:
        return False
    return bool(document.processing_task_id)


def reserve_processing_task(
    document: Document,
    *,
    task_id: str,
    stage: str,
    force: bool = False,
    lease_seconds: int | None = None,
) -> bool:
    if not force and has_active_processing_lease(document, stage=stage):
        return False
    settings = get_settings()
    now = _now()
    document.processing_task_id = task_id
    document.current_stage = stage
    document.processing_started_at = now
    document.last_processing_heartbeat_at = now
    document.processing_lease_until = now + timedelta(seconds=lease_seconds or settings.task_lease_seconds)
    return True


def clear_processing_lease(document: Document) -> None:
    document.processing_task_id = None
    document.current_stage = None
    document.processing_started_at = None
    document.processing_lease_until = None


def task_matches_or_expired(document: Document, task_id: str | None) -> bool:
    if not document.processing_task_id:
        return True
    if task_id and document.processing_task_id == task_id:
        return True
    return not has_active_processing_lease(document)


def update_batch_status(db: Session, batch_id: uuid.UUID) -> BatchStatus:
    documents = db.scalars(select(Document).where(Document.batch_id == batch_id).where(Document.deleted_at.is_(None))).all()
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise ValueError(f"Batch not found: {batch_id}")

    status = derive_parent_status(documents)
    batch.status = status
    batch.document_count = len(documents)
    for record_id in {doc.record_id for doc in documents if doc.record_id is not None}:
        update_record_status(db, record_id)
    return status


def mark_document_failed(db: Session, document: Document, message: str) -> None:
    logger.error("Document processing failed document_id=%s error=%s", document.id, message)
    record_event(db, document, "failed", message, metadata={"attempt": document.processing_attempt})
    document.processing_state = DocumentState.failed
    document.final_state = DocumentState.failed
    if document.ocr_state == StageState.processing:
        document.ocr_state = StageState.failed
    if document.metadata_state == StageState.processing:
        document.metadata_state = StageState.failed
    document.error_message = message
    document.retry_after_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    clear_processing_lease(document)
    update_batch_status(db, document.batch_id)
    update_record_status(db, document.record_id)


def processing_options(document: Document, settings: Any | None = None, **overrides: Any) -> dict[str, Any]:
    options = {**DEFAULT_PROCESSING_OPTIONS, **(document.processing_options_json or {})}
    options.update({key: value for key, value in overrides.items() if value is not None})
    if options["qwen_enabled"] is None:
        options["qwen_enabled"] = (settings or get_settings()).llm_metadata_refinement_enabled
    if options.get("qwen_enrichment_enabled") is None:
        options["qwen_enrichment_enabled"] = bool(options.get("qwen_enabled"))
    return options


def qwen_metadata_enabled(options: dict[str, Any]) -> bool:
    """One switch for the single Qwen metadata-brain call.

    Older payloads may still send qwen_enrichment_enabled. Treat it as enabling
    the same structured metadata candidate call, not a second sidecar call.
    """
    return bool(options.get("qwen_enabled") or options.get("qwen_enrichment_enabled"))


def should_qwen_overwrite_field(
    field_name: str,
    current_value: str | None,
    current_source: str | None,
    locked: bool,
    overwrite_manual_values: bool,
) -> bool:
    del field_name
    if locked:
        return False
    if _is_empty_value(current_value):
        return True
    if overwrite_manual_values:
        return True
    if current_source == "manual":
        return False
    return False


def merge_extracted_metadata_with_manual_values(
    document: Document,
    deterministic: dict[str, str | None],
    qwen_suggestion: dict[str, Any] | None = None,
    *,
    overwrite_manual_values: bool = False,
    force: bool = False,
) -> tuple[dict[str, str | None], dict[str, dict[str, Any]]]:
    existing_sources = document.metadata_sources_json or {}
    locks = document.field_locks_json or {}
    merged: dict[str, str | None] = {}
    sources: dict[str, dict[str, Any]] = {}

    for field_name, attr in CORE_FIELD_ATTRS.items():
        current = getattr(document, attr, None)
        source_info = existing_sources.get(field_name) if isinstance(existing_sources.get(field_name), dict) else {}
        current_source = source_info.get("source")
        locked = bool(locks.get(field_name)) or (document.metadata_locked and not force)
        candidate = deterministic.get(field_name)

        if locked or (current_source == "manual" and current and not force and not overwrite_manual_values):
            merged[field_name] = current
            sources[field_name] = {"source": current_source or "manual", "confidence": source_info.get("confidence")}
        elif not _is_empty_value(candidate):
            merged[field_name] = candidate
            sources[field_name] = {"source": "deterministic", "confidence": 90}
        elif force:
            merged[field_name] = None
            sources[field_name] = {"source": "deterministic", "confidence": None}
        else:
            merged[field_name] = current
            sources[field_name] = {"source": current_source or "deterministic", "confidence": source_info.get("confidence")}

    normalized_qwen = _normalize_qwen_suggestion(qwen_suggestion or {})
    for field_name, candidate in normalized_qwen.items():
        if field_name not in CORE_FIELD_ATTRS or _is_empty_value(candidate):
            continue
        source_info = sources.get(field_name, {})
        locked = bool((document.field_locks_json or {}).get(field_name)) or (document.metadata_locked and not force)
        if should_qwen_overwrite_field(field_name, merged.get(field_name), source_info.get("source"), locked, overwrite_manual_values):
            merged[field_name] = str(candidate)
            sources[field_name] = {
                "source": "qwen",
                "confidence": _qwen_confidence(qwen_suggestion or {}, field_name),
                "evidence": _qwen_evidence(qwen_suggestion or {}, field_name),
            }

    return merged, sources


def determine_next_processing_state(document: Document, missing_required_fields: list[str] | None = None) -> DocumentState:
    if document.ocr_state == StageState.failed or document.metadata_state == StageState.failed:
        return DocumentState.failed
    if document.ocr_state not in {StageState.done, StageState.skipped}:
        return document.processing_state
    if document.metadata_state not in {StageState.done, StageState.skipped}:
        return document.processing_state
    if missing_required_fields or document.review_state == ReviewState.needs_review:
        return DocumentState.needs_review
    if document.metadata_state == StageState.done and not (document.manual_title_override or document.extracted_title):
        return DocumentState.metadata_done
    return DocumentState.complete


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.upper() in {"NA", "N/A", "00/00", "00/00/0000"}


def _normalize_qwen_suggestion(suggestion: dict[str, Any]) -> dict[str, str | None]:
    if not isinstance(suggestion, dict):
        return {}
    source = suggestion.get("metadata") if isinstance(suggestion.get("metadata"), dict) else suggestion
    aliases = {
        "title": ("title", "extracted_title"),
        "sender": ("sender", "correspondent", "vendor", "issuer"),
        "recipient": ("recipient", "customer"),
        "invoice_number": ("invoice_number", "invoiceNo", "invoice_no", "rechnungsnummer"),
        "date": ("date", "invoice_date", "rechnungsdatum"),
        "amount": ("amount", "total", "gross_amount", "invoice_total"),
        "payment_method": ("payment_method", "zahlart"),
    }
    normalized: dict[str, str | None] = {}
    for target, keys in aliases.items():
        for key in keys:
            if key in source:
                value = source[key]
                normalized[target] = None if value is None else str(value).strip()
                if target == "date" and normalized[target]:
                    normalized[target] = _normalize_qwen_date(normalized[target])
                break
    return normalized


def _qwen_confidence(suggestion: dict[str, Any], field_name: str) -> int | None:
    confidence = suggestion.get("confidence") if isinstance(suggestion, dict) else None
    if isinstance(confidence, dict):
        value = confidence.get(field_name)
    else:
        value = confidence
    try:
        if value is None:
            return None
        numeric = float(value)
        return int(numeric * 100) if numeric <= 1 else int(numeric)
    except (TypeError, ValueError):
        return None


NEUTRAL_QWEN_CORE_CANDIDATE_FIELDS = {
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
}

NEUTRAL_QWEN_METADATA_KEYS = {
    "title",
    "title_base",
    "extracted_title",
    "sender",
    "correspondent",
    "vendor",
    "issuer",
    "recipient",
    "customer",
    "document_type",
    "invoice_number",
    "invoiceNo",
    "invoice_no",
    "rechnungsnummer",
    "created_date",
    "date",
    "invoice_date",
    "rechnungsdatum",
    "amount",
    "total",
    "gross_amount",
    "invoice_total",
    "currency",
    "payment_method",
    "zahlart",
}


def suppress_qwen_candidate_core_fields_for_neutral(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Keep Qwen search/tag/custom-field hints, but do not let it classify neutral files as invoices."""
    if not isinstance(candidate, dict):
        return {}
    cleaned = {**candidate}
    for field_name in NEUTRAL_QWEN_CORE_CANDIDATE_FIELDS:
        item = cleaned.get(field_name)
        if isinstance(item, dict):
            cleaned[field_name] = {**item, "value": None, "confidence": None, "evidence": None}
        else:
            cleaned[field_name] = {"value": None, "confidence": None, "evidence": None}
    return cleaned


def suppress_qwen_core_fields_for_neutral(qwen_suggestion: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(qwen_suggestion, dict):
        return qwen_suggestion
    cleaned = {**qwen_suggestion}
    metadata = cleaned.get("metadata") if isinstance(cleaned.get("metadata"), dict) else None
    if metadata is not None:
        cleaned["metadata"] = {key: value for key, value in metadata.items() if key not in NEUTRAL_QWEN_METADATA_KEYS}
    else:
        for key in NEUTRAL_QWEN_METADATA_KEYS:
            cleaned.pop(key, None)
    for group in ("confidence", "evidence"):
        values = cleaned.get(group)
        if isinstance(values, dict):
            cleaned[group] = {key: value for key, value in values.items() if key not in NEUTRAL_QWEN_METADATA_KEYS}
    return cleaned


def _qwen_evidence(suggestion: dict[str, Any], field_name: str) -> str | None:
    evidence = suggestion.get("evidence") if isinstance(suggestion, dict) else None
    if isinstance(evidence, dict):
        value = evidence.get(field_name)
    else:
        value = None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_qwen_date(value: str) -> str:
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text.split("-")
        if year.isdigit() and month.isdigit() and day.isdigit():
            return f"{day}/{month}/{year}"
    return text


def _apply_qwen_candidate_side_effects(
    db: Session,
    document: Document,
    candidate: dict[str, Any],
    qwen_suggestion: dict[str, Any],
    *,
    debug: dict[str, Any] | None = None,
    overwrite_manual_values: bool,
    force: bool,
) -> None:
    apply_qwen_search_metadata(document, candidate, debug or {"raw_response": {}, "similar_documents": []})
    metadata = dict(document.metadata_json or {})
    metadata["qwen_candidates"] = candidate
    metadata["custom_field_evidence"] = {
        slug: {"confidence": item.get("confidence"), "evidence": item.get("evidence")}
        for slug, item in (candidate.get("custom_fields") or {}).items()
        if isinstance(item, dict)
    }
    document_type = (qwen_suggestion.get("metadata") or {}).get("document_type") if isinstance(qwen_suggestion, dict) else None
    if document_type and _is_empty_value(metadata.get("document_type")):
        metadata["document_type"] = document_type
    document.metadata_json = metadata
    _save_qwen_custom_fields(db, document, candidate, force=force, overwrite_manual_values=overwrite_manual_values)


def _save_qwen_custom_fields(
    db: Session,
    document: Document,
    candidate: dict[str, Any],
    *,
    force: bool,
    overwrite_manual_values: bool,
) -> None:
    collection = document.record.collection if document.record else None
    if collection is None:
        return
    custom_candidates = candidate.get("custom_fields") if isinstance(candidate.get("custom_fields"), dict) else {}
    if not custom_candidates:
        return
    existing_by_field = {value.custom_field_definition_id: value for value in document.custom_field_values}
    fields_by_slug = {field.slug.lower(): field for field in collection.custom_fields}
    fields_by_name = {field.name.lower(): field for field in collection.custom_fields}
    for raw_slug, item in custom_candidates.items():
        if not isinstance(item, dict) or _is_empty_value(item.get("value")):
            continue
        field = fields_by_slug.get(str(raw_slug).lower()) or fields_by_name.get(str(raw_slug).lower())
        if field is None:
            continue
        existing = existing_by_field.get(field.id)
        if existing and existing.locked and not force:
            continue
        if existing and existing.source == FieldValueSource.manual and not (force or overwrite_manual_values):
            continue
        upsert_custom_field_value(
            db,
            document,
            field,
            item.get("value"),
            source=FieldValueSource.qwen,
            confidence=item.get("confidence"),
            force=force or overwrite_manual_values,
        )


def _maybe_apply_qwen_title_base(document: Document, qwen_suggestion: dict[str, Any] | None) -> None:
    if not isinstance(qwen_suggestion, dict) or title_is_locked(document):
        return
    title_base = ((qwen_suggestion.get("metadata") or {}).get("title_base") or "").strip()
    if not title_base:
        return
    current = document.extracted_title or ""
    first_segment = current.split("_", 1)[0] if current else ""
    if current and first_segment not in {"", "Dok", "NA", "Unknown"}:
        return
    clean = sanitize_shared_title_base(title_base)
    if not clean:
        return
    if document.collection_name == "Belege" and "_B_" in current:
        document.extracted_title = clean + current[current.index("_B_") :]
    elif "_" in current:
        document.extracted_title = clean + "_" + current.split("_", 1)[1]


def missing_required_core_fields(document: Document, merged: dict[str, str | None]) -> list[str]:
    collection = document.record.collection if document.record and document.record.collection else None
    rules = collection.validation_rules if collection else {}
    required = rules.get("required_core_fields", []) if isinstance(rules, dict) else []
    missing: list[str] = []
    for field_name in required:
        if field_name in CORE_FIELD_ATTRS and _is_empty_value(merged.get(field_name)):
            missing.append(str(field_name))
    if collection:
        for field in collection.custom_fields:
            if not field.required:
                continue
            value = next((item for item in document.custom_field_values if item.custom_field_definition_id == field.id), None)
            if value is None or _is_empty_value(value.normalized_value):
                missing.append(field.slug)
    return missing


def review_warnings(
    document: Document,
    merged: dict[str, str | None],
    sources: dict[str, dict[str, Any]],
    qwen_suggestion: dict[str, Any] | None,
    deterministic: dict[str, str | None],
) -> list[str]:
    warnings: list[str] = []
    for field_name, source in sources.items():
        confidence = source.get("confidence")
        try:
            if confidence is not None and int(confidence) < 70:
                warnings.append(f"Low confidence for {field_name}")
        except (TypeError, ValueError):
            pass
    title = merged.get("title") or document.extracted_title or ""
    if title.startswith("Dok_") or "_NA" in title or title in {"Dok", "NA"}:
        warnings.append("Fallback title or missing title segment used")
    amount = merged.get("amount") or ""
    digits = "".join(ch for ch in amount if ch.isdigit())
    if amount == "42424242,00" or len(digits) > 9:
        warnings.append("Suspicious amount detected")
    date = merged.get("date") or ""
    if date in {"00/00", "00/00/0000"}:
        warnings.append("Suspicious or fallback date detected")
    normalized_qwen = _normalize_qwen_suggestion(qwen_suggestion or {})
    for field in ["sender", "recipient", "invoice_number", "date", "amount"]:
        qwen_value = normalized_qwen.get(field)
        deterministic_value = deterministic.get(field)
        if qwen_value and deterministic_value and str(qwen_value).strip() != str(deterministic_value).strip():
            warnings.append(f"Qwen disagrees with deterministic {field}")
    if document.ocr_state == StageState.failed or (document.raw_ocr_json or {}).get("partial_failure"):
        warnings.append("OCR failed partially")
    return sorted(set(warnings))


def queue_ocr(db: Session, document: Document, *, force: bool = False) -> bool:
    if not force and (
        has_active_processing_lease(document, stage="ocr")
        or document.processing_state in {DocumentState.queued_for_ocr, DocumentState.ocr_processing}
    ):
        record_event(
            db,
            document,
            "ocr_queue_skipped_active",
            "OCR was not queued because the document already has queued or active OCR work",
            metadata={
                "task_id": document.processing_task_id,
                "stage": document.current_stage,
                "lease_until": document.processing_lease_until.isoformat() if document.processing_lease_until else None,
                "state": document.processing_state.value,
            },
        )
        return False
    if document.processing_state == DocumentState.duplicate and not force:
        record_event(db, document, "retry_skipped_duplicate", "Duplicate document was not queued without force")
        update_batch_status(db, document.batch_id)
        return False
    document.processing_state = DocumentState.queued_for_ocr
    document.final_state = DocumentState.queued_for_ocr
    document.ocr_state = StageState.pending
    document.metadata_state = StageState.pending
    document.error_message = None
    document.retry_after_at = None
    document.completed_at = None
    if force:
        clear_processing_lease(document)
    record_event(db, document, "queued_for_ocr", "Document queued for OCR", metadata={"force": force})
    record_event(db, document, "ocr_queued", "Document queued for OCR", metadata={"force": force})
    update_batch_status(db, document.batch_id)
    update_record_status(db, document.record_id)
    return True


def queue_full_process(db: Session, document: Document, *, force: bool = False) -> bool:
    if not force and (
        has_active_processing_lease(document)
        or document.processing_state in {DocumentState.queued_for_ocr, DocumentState.ocr_processing, DocumentState.metadata_processing}
    ):
        record_event(
            db,
            document,
            "process_queue_skipped_active",
            "Full processing was not queued because the document already has queued or active work",
            metadata={
                "task_id": document.processing_task_id,
                "stage": document.current_stage,
                "lease_until": document.processing_lease_until.isoformat() if document.processing_lease_until else None,
                "state": document.processing_state.value,
            },
        )
        return False
    if document.deleted_at is not None:
        record_event(db, document, "process_skipped_deleted", "Deleted document was not queued for processing")
        return False
    if document.processing_state == DocumentState.duplicate and not force:
        record_event(db, document, "process_skipped_duplicate", "Duplicate document was not queued without force")
        update_batch_status(db, document.batch_id)
        return False
    if force or document.ocr_state not in {StageState.done, StageState.skipped}:
        queued = queue_ocr(db, document, force=force)
    else:
        document.processing_state = DocumentState.ocr_done
        document.final_state = DocumentState.ocr_done
        if document.metadata_state not in {StageState.done, StageState.skipped}:
            document.metadata_state = StageState.pending
        record_event(db, document, "process_queued", "Full document processing queued from existing OCR", metadata={"force": force})
        update_batch_status(db, document.batch_id)
        update_record_status(db, document.record_id)
        queued = True
    return queued


def mark_duplicate_document(db: Session, document: Document, original: Document) -> None:
    document.duplicate_of_document_id = original.id
    document.processing_state = DocumentState.duplicate
    document.final_state = DocumentState.duplicate
    document.ocr_state = StageState.done
    document.metadata_state = StageState.done
    document.ocr_text = original.ocr_text
    document.extracted_title = original.extracted_title
    document.extracted_sender = original.extracted_sender
    document.extracted_recipient = original.extracted_recipient
    document.extracted_invoice_number = original.extracted_invoice_number
    document.extracted_date = original.extracted_date
    document.extracted_amount = original.extracted_amount
    document.extracted_payment_method = original.extracted_payment_method
    document.metadata_json = {
        **(original.metadata_json or {}),
        "duplicate_of_document_id": str(original.id),
        "duplicate_policy": "linked_without_reprocessing",
    }
    document.raw_ocr_json = original.raw_ocr_json or {}
    document.prompt_trace_json = original.prompt_trace_json or {}
    document.model_trace_json = {
        **(original.model_trace_json or {}),
        "duplicate_of_document_id": str(original.id),
    }
    document.completed_at = datetime.now(timezone.utc)
    for page in original.pages:
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                ocr_text=page.ocr_text,
                raw_ocr_json={
                    **(page.raw_ocr_json or {}),
                    "duplicate_of_document_id": str(original.id),
                },
                rendered_image_path=page.rendered_image_path,
            )
        )
    record_event(
        db,
        document,
        "duplicate_detected",
        "Duplicate upload linked to existing document and not reprocessed",
        metadata={"duplicate_of_document_id": str(original.id), "sha256": document.sha256},
    )
    update_batch_status(db, document.batch_id)
    update_record_status(db, document.record_id)


def is_stale(document: Document) -> bool:
    if document.processing_state not in {
        DocumentState.uploaded,
        DocumentState.queued_for_ocr,
        DocumentState.ocr_processing,
        DocumentState.ocr_done,
        DocumentState.metadata_processing,
    }:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=get_settings().stuck_document_minutes)
    heartbeat = document.last_processing_heartbeat_at
    candidate = heartbeat or document.updated_at or document.created_at
    if candidate is None:
        return False
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    return candidate < cutoff


def _write_page_fragments(db: Session, document: Document, result_text: str, raw_response: dict) -> None:
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    raw_pages = raw_response.get("pages") if isinstance(raw_response, dict) else None
    if isinstance(raw_pages, list) and raw_pages:
        for index, raw_page in enumerate(raw_pages, start=1):
            if isinstance(raw_page, dict):
                text = str(raw_page.get("text") or raw_page.get("ocr_text") or "")
                raw = raw_page
            else:
                text = str(raw_page)
                raw = {"raw": raw_page}
            db.add(
                DocumentPage(
                    document_id=document.id,
                    page_number=index,
                    ocr_text=text,
                    raw_ocr_json=raw,
                    rendered_image_path=raw.get("rendered_image_path") if isinstance(raw, dict) else None,
                )
            )
        document.page_count = len(raw_pages)
        return

    fragments = [item.strip() for item in result_text.split("\f") if item.strip()]
    if not fragments and result_text:
        fragments = [result_text]
    for index, text in enumerate(fragments, start=1):
        db.add(DocumentPage(document_id=document.id, page_number=index, ocr_text=text, raw_ocr_json={}))
    if fragments:
        document.page_count = len(fragments)


def run_ocr_for_document(
    db: Session,
    document_id: uuid.UUID,
    provider: OCRProvider | None = None,
    *,
    enqueue_metadata: bool = True,
    force: bool = False,
    ocr_mode: str | None = None,
    task_id: str | None = None,
) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    if document.processing_state == DocumentState.duplicate and not force:
        record_event(db, document, "ocr_skipped_duplicate", "Duplicate document OCR skipped")
        db.commit()
        return document
    if not force and not task_matches_or_expired(document, task_id):
        record_event(
            db,
            document,
            "ocr_skipped_foreign_active_task",
            "OCR task skipped because another active task lease owns this document",
            metadata={"task_id": task_id, "active_task_id": document.processing_task_id, "stage": document.current_stage},
        )
        db.commit()
        return document
    if not force and document.processing_state not in {DocumentState.queued_for_ocr, DocumentState.ocr_processing}:
        record_event(
            db,
            document,
            "ocr_skipped_state_guard",
            "OCR task skipped because document is not queued for OCR",
            metadata={"state": document.processing_state.value},
        )
        db.commit()
        return document
    if not force and document.processing_state == DocumentState.ocr_processing and not is_stale(document):
        record_event(db, document, "ocr_skipped_active", "OCR task skipped because another worker is active")
        db.commit()
        return document
    if ocr_mode:
        document.ocr_mode = OCRMode(ocr_mode)
    runtime_settings = settings_with_model_setup(db)
    config = resolve_ocr_config(document, settings=runtime_settings)
    if force:
        config.ocr_mode = OCRMode.force
        document.ocr_mode = OCRMode.force
    store_effective_ocr_trace(document, config)
    if config.ocr_mode == OCRMode.skip:
        reason = "OCR skipped because text already exists" if document.ocr_text else "OCR explicitly skipped without existing text"
        record_event(db, document, "ocr_skipped", reason, metadata=config.as_dict())
        document.ocr_state = StageState.skipped
        document.processing_state = DocumentState.ocr_done
        document.final_state = DocumentState.ocr_done
        _write_page_fragments(db, document, document.ocr_text or "", document.raw_ocr_json or {})
        metadata_task_id = str(uuid.uuid4()) if enqueue_metadata else None
        if enqueue_metadata:
            reserve_processing_task(document, task_id=metadata_task_id or "", stage="metadata", force=True)
        update_batch_status(db, document.batch_id)
        db.commit()
        if enqueue_metadata:
            from app.workers.tasks import extract_metadata_task, publish_document_task

            publish_document_task(db, document.id, extract_metadata_task, args=[str(document.id)], task_id=metadata_task_id, queue="metadata", stage="metadata")
        return document
    provider = provider or build_ocr_provider(runtime_settings, provider_name=config.ocr_engine)
    try:
        document.processing_state = DocumentState.ocr_processing
        document.final_state = DocumentState.ocr_processing
        document.ocr_state = StageState.processing
        document.error_message = None
        document.retry_after_at = None
        document.processing_attempt = (document.processing_attempt or 0) + 1
        document.last_processing_heartbeat_at = datetime.now(timezone.utc)
        document.current_stage = "ocr"
        record_event(db, document, "ocr_started", "OCR started", metadata={"attempt": document.processing_attempt, "ocr_config": config.as_dict()})
        update_batch_status(db, document.batch_id)
        db.commit()

        logger.info("OCR started document_id=%s path=%s", document.id, document.storage_path)
        try:
            if _is_pdf_document(document):
                result = _extract_pdf_pages(provider, document, config)
            else:
                result = provider.extract_text(document.storage_path)
        except OCRProviderError as exc:
            empty_paddle_vl = config.ocr_engine == "paddle_vl" and "empty text" in str(exc).lower()
            can_fallback = empty_paddle_vl and not _is_pdf_document(document)
            if not can_fallback:
                raise
            record_event(
                db,
                document,
                "ocr_fallback_ppocrv6",
                "PaddleOCR-VL returned empty text; falling back to local PP-OCRv6",
                metadata={"error": str(exc), "from_engine": config.ocr_engine, "fallback_engine": "ppocrv6"},
            )
            db.commit()
            logger.warning("PaddleOCR-VL returned empty text for document_id=%s; falling back to PP-OCRv6", document.id)
            fallback_provider = build_ocr_provider(runtime_settings, provider_name="ppocrv6")
            result = fallback_provider.extract_text(document.storage_path)
            result.raw_response = {
                **(result.raw_response or {}),
                "fallback_from": config.ocr_engine,
                "fallback_reason": str(exc),
            }
        document.ocr_text = result.text
        document.raw_ocr_json = result.raw_response
        _write_page_fragments(db, document, result.text, result.raw_response)
        document.prompt_trace_json = {
            **(document.prompt_trace_json or {}),
            "ocr": {
                "name": result.prompt_name,
                "version": result.prompt_version,
            },
            "ocr_config": config.as_dict(),
        }
        document.model_trace_json = {
            **(document.model_trace_json or {}),
            "ocr": {
                "role": result.model_role,
                "endpoint": result.model_endpoint,
                "model": result.model_name,
            },
            "ocr_pipeline": {
                "engine": result.model_role or get_settings().ocr_provider,
                "mode": config.ocr_mode.value,
                "output_type_note": "VLM OCR/parser produces text or markdown; output_type is trace-only in v1",
            },
        }
        record_event(
            db,
            document,
            "ocr_done",
            "OCR completed",
            metadata={"chars": len(result.text), "prompt": result.prompt_name, "model": result.model_name},
        )
        document.ocr_state = StageState.done
        document.processing_state = DocumentState.ocr_done
        document.final_state = DocumentState.ocr_done
        document.last_processing_heartbeat_at = datetime.now(timezone.utc)
        metadata_task_id = str(uuid.uuid4()) if enqueue_metadata else None
        if enqueue_metadata:
            reserve_processing_task(document, task_id=metadata_task_id or "", stage="metadata", force=True)
        update_batch_status(db, document.batch_id)
        db.commit()
        logger.info("OCR completed document_id=%s chars=%s", document.id, len(result.text))

        if enqueue_metadata:
            from app.workers.tasks import extract_metadata_task, publish_document_task

            publish_document_task(db, document.id, extract_metadata_task, args=[str(document.id)], task_id=metadata_task_id, queue="metadata", stage="metadata")
        return document
    except Exception as exc:  # noqa: BLE001
        mark_document_failed(db, document, str(exc))
        db.commit()
        raise


def _is_pdf_document(document: Document) -> bool:
    return (document.mime_type or "").lower() == "application/pdf" or document.storage_path.lower().endswith(".pdf")


def _extract_pdf_pages(provider: OCRProvider, document: Document, config: Any):
    from app.services.ocr_glm import OCRResult

    rendered_paths = render_pdf_pages(
        document.storage_path,
        document.id,
        page_limit=config.page_limit,
        image_dpi=config.image_dpi,
    )
    if not rendered_paths:
        return provider.extract_text(document.storage_path)

    page_payloads: list[dict[str, Any]] = []
    texts: list[str] = []
    first_result = None
    for index, page_path in enumerate(rendered_paths, start=1):
        page_result = provider.extract_text(page_path)
        if first_result is None:
            first_result = page_result
        texts.append(page_result.text)
        page_payloads.append(
            {
                "page_number": index,
                "text": page_result.text,
                "raw_response": page_result.raw_response,
                "rendered_image_path": page_path,
            }
        )
    assert first_result is not None
    return OCRResult(
        text="\f".join(texts),
        raw_response={"pages": page_payloads, "source": "pdf_page_rendering"},
        prompt_name=first_result.prompt_name,
        prompt_version=first_result.prompt_version,
        model_role=first_result.model_role,
        model_endpoint=first_result.model_endpoint,
        model_name=first_result.model_name,
        model_response_text="\n\n".join(texts),
    )


def run_metadata_for_document(
    db: Session,
    document_id: uuid.UUID,
    *,
    force: bool = False,
    qwen_provider: Any | None = None,
    qwen_enabled: bool | None = None,
    overwrite_manual_values: bool | None = None,
    skip_metadata: bool | None = None,
    task_id: str | None = None,
) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    if document.processing_state == DocumentState.duplicate and not force:
        record_event(db, document, "metadata_skipped_duplicate", "Duplicate document metadata skipped")
        db.commit()
        return document
    if not force and not task_matches_or_expired(document, task_id):
        record_event(
            db,
            document,
            "metadata_skipped_foreign_active_task",
            "Metadata task skipped because another active task lease owns this document",
            metadata={"task_id": task_id, "active_task_id": document.processing_task_id, "stage": document.current_stage},
        )
        db.commit()
        return document
    if document.ocr_state not in {StageState.done, StageState.skipped}:
        record_event(
            db,
            document,
            "metadata_skipped_missing_ocr",
            "Metadata extraction skipped because OCR is not done",
            metadata={"ocr_state": document.ocr_state.value},
        )
        db.commit()
        return document
    if not force and document.processing_state == DocumentState.complete:
        record_event(
            db,
            document,
            "metadata_skipped_complete",
            "Metadata task skipped because document is already complete",
        )
        db.commit()
        return document
    if not force and document.processing_state not in {DocumentState.ocr_done, DocumentState.metadata_processing}:
        record_event(
            db,
            document,
            "metadata_skipped_state_guard",
            "Metadata extraction skipped because document is not ready",
            metadata={"state": document.processing_state.value},
        )
        db.commit()
        return document
    if not force and document.processing_state == DocumentState.metadata_processing and not is_stale(document):
        record_event(db, document, "metadata_skipped_active", "Metadata task skipped because another worker is active")
        db.commit()
        return document
    runtime_settings = settings_with_model_setup(db)
    options = processing_options(
        document,
        settings=runtime_settings,
        qwen_enabled=qwen_enabled,
        overwrite_manual_values=overwrite_manual_values,
        skip_metadata=skip_metadata,
    )
    document.processing_options_json = options
    if options.get("skip_metadata"):
        document.metadata_state = StageState.skipped
        document.processing_state = determine_next_processing_state(document)
        document.final_state = document.processing_state
        clear_processing_lease(document)
        if document.processing_state == DocumentState.complete:
            document.completed_at = datetime.now(timezone.utc)
        record_event(db, document, "metadata_skipped", "Metadata extraction explicitly skipped", metadata={"processing_options": options})
        update_batch_status(db, document.batch_id)
        db.commit()
        return document
    try:
        old_metadata = {
            "title": document.extracted_title,
            "manual_title_override": document.manual_title_override,
            "metadata": document.metadata_json,
        }
        document.processing_state = DocumentState.metadata_processing
        document.final_state = DocumentState.metadata_processing
        document.metadata_state = StageState.processing
        document.error_message = None
        document.retry_after_at = None
        document.processing_attempt = (document.processing_attempt or 0) + 1
        document.last_processing_heartbeat_at = datetime.now(timezone.utc)
        document.current_stage = "metadata"
        record_event(db, document, "metadata_started", "Metadata extraction started", metadata={"attempt": document.processing_attempt})
        update_batch_status(db, document.batch_id)
        db.commit()

        payload = ExtractionInput(
            collection_name=document.collection_name,
            ocr_text=document.ocr_text or "",
            original_filename=document.original_filename,
            created_at=document.created_at,
            existing_title=document.extracted_title,
        )
        result = extract_metadata(payload)
        if (
            document.record
            and document.record.apply_shared_title_to_documents
            and document.record.shared_title_base
            and not title_is_locked(document, force=force)
        ):
            result = apply_shared_title_to_result(document.collection_name, result, document.record.shared_title_base)
            if result.metadata.get("shared_title_applied"):
                record_event(
                    db,
                    document,
                    "shared_title_base_applied",
                    "Record shared title base applied to generated document title",
                    metadata={"shared_title_base": sanitize_shared_title_base(document.record.shared_title_base)},
                )
        logger.info("Metadata extraction completed document_id=%s title=%s", document.id, result.title)
        record_event(db, document, "metadata_deterministic_done", "Deterministic extraction completed", metadata={"title": result.title})

        deterministic = {
            "title": result.title,
            "sender": result.sender,
            "recipient": result.recipient,
            "invoice_number": result.invoice_number,
            "date": result.date,
            "amount": result.amount,
            "payment_method": result.payment_method,
        }

        qwen_debug: dict[str, Any] | None = None
        qwen_suggestion: dict[str, Any] | None = None
        qwen_enabled_for_run = qwen_metadata_enabled(options)
        if qwen_enabled_for_run:
            qwen_provider = qwen_provider if qwen_provider is not None else build_qwen_provider(runtime_settings)
            record_event(db, document, "qwen_started", "Qwen metadata brain started")
            qwen_debug = qwen_generate_metadata_candidates(
                db,
                document,
                deterministic,
                options,
                provider=qwen_provider,
            )
            if qwen_debug.get("ok"):
                qwen_candidate = qwen_debug.get("candidate") or {}
                if result.metadata.get("neutral_file"):
                    qwen_candidate = suppress_qwen_candidate_core_fields_for_neutral(qwen_candidate)
                    qwen_debug = {
                        **qwen_debug,
                        "candidate": qwen_candidate,
                        "neutral_core_fields_suppressed": True,
                    }
                qwen_suggestion = candidate_to_metadata_suggestion(qwen_candidate)
                if result.metadata.get("neutral_file"):
                    qwen_suggestion = suppress_qwen_core_fields_for_neutral(qwen_suggestion)
                _apply_qwen_candidate_side_effects(
                    db,
                    document,
                    qwen_candidate,
                    qwen_suggestion,
                    debug=qwen_debug,
                    overwrite_manual_values=bool(options.get("overwrite_manual_values")),
                    force=force,
                )
                document.qwen_response_text = qwen_debug.get("raw_text")
                document.prompt_trace_json = {
                    **(document.prompt_trace_json or {}),
                    "metadata_refinement": qwen_debug["prompt"],
                    "metadata_brain": qwen_debug["prompt"],
                }
                document.model_trace_json = {
                    **(document.model_trace_json or {}),
                    "metadata_refinement": qwen_debug["model"],
                    "metadata_brain": qwen_debug["model"],
                }
                record_event(
                    db,
                    document,
                    "qwen_metadata_brain_done",
                    "Qwen metadata candidates generated",
                    metadata={"model": qwen_debug["model"].get("model"), "prompt": qwen_debug["prompt"].get("name")},
                )
                record_event(
                    db,
                    document,
                    "qwen_done",
                    "Qwen metadata, search, tag, and folder candidates generated",
                    metadata={"model": qwen_debug["model"].get("model"), "prompt": qwen_debug["prompt"].get("name")},
                )
            else:
                document.qwen_response_text = qwen_debug.get("raw_text")
                document.llm_raw_response = {
                    **(document.llm_raw_response or {}),
                    "metadata_brain": {
                        "invalid": bool(qwen_debug.get("raw_text")),
                        "raw_text": qwen_debug.get("raw_text"),
                        "raw_response": qwen_debug.get("raw_response"),
                        "error": qwen_debug.get("error"),
                        "similar_documents": qwen_debug.get("similar_documents", []),
                    },
                }
                if qwen_debug.get("raw_text"):
                    document.review_state = ReviewState.needs_review
                    document.review_reason = document.review_reason or "Qwen metadata brain returned invalid JSON"
                record_event(
                    db,
                    document,
                    "qwen_unavailable",
                    "Qwen metadata brain unavailable or invalid",
                    metadata={"reason": qwen_debug.get("error")},
                )
        else:
            qwen_debug = {"disabled": True}
            record_event(db, document, "qwen_metadata_brain_skipped", "Qwen metadata brain disabled by processing options")

        merged, sources = merge_extracted_metadata_with_manual_values(
            document,
            deterministic,
            qwen_suggestion,
            overwrite_manual_values=bool(options.get("overwrite_manual_values")),
            force=force,
        )
        if result.metadata.get("shared_title_applied"):
            sources["title_base"] = {
                "source": "shared_record",
                "confidence": 100,
                "record_id": str(document.record_id) if document.record_id else None,
            }
        for field_name, attr in CORE_FIELD_ATTRS.items():
            setattr(document, attr, merged.get(field_name))
        _maybe_apply_qwen_title_base(document, qwen_suggestion)

        document.metadata_sources_json = sources
        apply_paperless_metadata(db, document)
        previous_metadata = dict(document.metadata_json or {})
        previous_metadata.pop("review_warnings", None)
        previous_metadata.pop("missing_required_fields", None)
        document.metadata_json = {
            **previous_metadata,
            **result.metadata,
            "deterministic_title": result.title,
            "qwen_refinement": qwen_debug,
            "qwen_candidates": (qwen_debug or {}).get("candidate", {}),
            "merged_sources": sources,
            "search_indexed": True,
        }
        record_event(db, document, "search_indexed", "Full OCR and metadata are searchable in the app database")
        record_event(
            db,
            document,
            "title_generated",
            "Final title and metadata generated",
            old_value=old_metadata,
            new_value={
                "title": document.extracted_title,
                "sender": document.extracted_sender,
                "recipient": document.extracted_recipient,
                "invoice_number": document.extracted_invoice_number,
                "date": document.extracted_date,
                "amount": document.extracted_amount,
                "sources": sources,
            },
            metadata={"locked": document.metadata_locked and not force, "qwen_enabled": qwen_enabled_for_run},
        )

        document.metadata_state = StageState.done
        missing_required = missing_required_core_fields(document, merged)
        warnings = review_warnings(document, merged, sources, qwen_suggestion, deterministic)
        if (
            not missing_required
            and not warnings
            and document.review_state == ReviewState.needs_review
            and not str(document.review_reason or "").startswith("Qwen metadata brain")
        ):
            document.review_state = ReviewState.unreviewed
            document.review_reason = None
        document.processing_state = determine_next_processing_state(document, missing_required)
        if warnings and document.processing_state == DocumentState.complete:
            document.processing_state = DocumentState.needs_review
        document.final_state = document.processing_state
        if missing_required:
            document.review_state = ReviewState.needs_review
            document.review_reason = f"Missing required fields: {', '.join(missing_required)}"
            document.metadata_json = {
                **(document.metadata_json or {}),
                "missing_required_fields": missing_required,
            }
        elif warnings:
            document.review_state = ReviewState.needs_review
            document.review_reason = "; ".join(warnings)
            document.metadata_json = {
                **(document.metadata_json or {}),
                "review_warnings": warnings,
            }
        document.last_processing_heartbeat_at = datetime.now(timezone.utc)
        clear_processing_lease(document)
        if document.processing_state == DocumentState.complete:
            document.completed_at = datetime.now(timezone.utc)
            record_event(db, document, "complete", "Document complete after OCR, metadata, title, and DB update")
        else:
            record_event(db, document, "needs_review", "Document metadata saved but requires review", metadata={"missing_required_fields": missing_required})
        execute_hooks(db, HookStage.post_consume, document=document, context={"stage": "metadata_complete"})
        update_batch_status(db, document.batch_id)
        db.commit()
        return document
    except Exception as exc:  # noqa: BLE001
        mark_document_failed(db, document, str(exc))
        db.commit()
        raise


def run_full_process_for_document(
    db: Session,
    document_id: uuid.UUID,
    *,
    ocr_provider: OCRProvider | None = None,
    qwen_provider: Any | None = None,
    force: bool = False,
    task_id: str | None = None,
) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document not found: {document_id}")
    if document.deleted_at is not None:
        record_event(db, document, "process_skipped_deleted", "Deleted document processing skipped")
        db.commit()
        return document
    if document.processing_state == DocumentState.duplicate and not force:
        record_event(db, document, "process_skipped_duplicate", "Duplicate document processing skipped")
        update_batch_status(db, document.batch_id)
        db.commit()
        return document
    if not force and not task_matches_or_expired(document, task_id):
        record_event(
            db,
            document,
            "process_skipped_foreign_active_task",
            "Full processing skipped because another active task lease owns this document",
            metadata={"task_id": task_id, "active_task_id": document.processing_task_id, "stage": document.current_stage},
        )
        db.commit()
        return document

    runtime_settings = settings_with_model_setup(db)
    options = processing_options(document, settings=runtime_settings)
    document.current_stage = "process"
    document.last_processing_heartbeat_at = datetime.now(timezone.utc)
    record_event(db, document, "process_started", "Full document processing started", metadata={"force": force, "processing_options": options})
    db.commit()

    if force or document.ocr_state not in {StageState.done, StageState.skipped}:
        document = db.get(Document, document_id)
        assert document is not None
        if document.processing_state not in {DocumentState.queued_for_ocr, DocumentState.ocr_processing}:
            queue_ocr(db, document, force=force)
            db.commit()
        document = run_ocr_for_document(db, document_id, provider=ocr_provider, enqueue_metadata=False, force=force, task_id=task_id)
    else:
        record_event(db, document, "process_ocr_reused", "Existing OCR reused for full processing")
        db.commit()

    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document disappeared during processing: {document_id}")
    options = processing_options(document, settings=runtime_settings)
    if force or document.metadata_state not in {StageState.done, StageState.skipped}:
        if document.ocr_state not in {StageState.done, StageState.skipped}:
            record_event(db, document, "process_waiting_for_ocr", "Full processing stopped because OCR is not complete")
            db.commit()
            return document
        document.processing_state = DocumentState.ocr_done
        document.final_state = DocumentState.ocr_done
        document.metadata_state = StageState.pending
        db.commit()
        document = run_metadata_for_document(
            db,
            document_id,
            force=force,
            qwen_provider=qwen_provider,
            qwen_enabled=(qwen_provider is not None or qwen_metadata_enabled(options)),
            overwrite_manual_values=bool(options.get("overwrite_manual_values")),
            skip_metadata=bool(options.get("skip_metadata")),
            task_id=task_id,
        )
    else:
        record_event(db, document, "process_metadata_reused", "Existing metadata reused for full processing")
        db.commit()

    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document disappeared after metadata: {document_id}")
    options = processing_options(document)
    if qwen_metadata_enabled(options):
        record_event(
            db,
            document,
            "qwen_metadata_brain_single_pass",
            "Qwen metadata, search, tag, and folder candidates were handled in the metadata stage",
        )
    else:
        record_event(db, document, "qwen_metadata_brain_skipped", "Qwen metadata brain disabled by processing options")

    _assign_folder_after_processing(db, document, options)
    missing_required = missing_required_core_fields(
        document,
        {
            "title": document.extracted_title,
            "sender": document.extracted_sender,
            "recipient": document.extracted_recipient,
            "invoice_number": document.extracted_invoice_number,
            "date": document.extracted_date,
            "amount": document.extracted_amount,
            "payment_method": document.extracted_payment_method,
        },
    )
    document.processing_state = determine_next_processing_state(document, missing_required)
    document.final_state = document.processing_state
    if document.processing_state == DocumentState.complete:
        document.completed_at = datetime.now(timezone.utc)
    clear_processing_lease(document)
    update_batch_status(db, document.batch_id)
    update_record_status(db, document.record_id)
    record_event(
        db,
        document,
        "process_finished",
        "Full document processing finished",
        metadata={"state": document.processing_state.value, "folder_id": str(document.folder_id) if document.folder_id else None},
    )
    db.commit()
    return document


def _assign_folder_after_processing(db: Session, document: Document, options: dict[str, Any]) -> None:
    if not options.get("auto_folder_enabled", False) or document.folder_id is not None:
        return
    folder_path = None
    if options.get("use_qwen_folder_suggestion") and document.llm_suggested_folder:
        folder_path = document.llm_suggested_folder
    if not folder_path:
        folder_path = auto_folder_path_for_document(document)
    folder = ensure_folder_path(db, folder_path, collection_id=document.record.collection_id if document.record else None)
    document.folder_id = folder.id
    if document.record and document.record.folder_id is None:
        document.record.folder_id = folder.id
    record_event(
        db,
        document,
        "folder_assigned",
        "Document assigned to folder",
        metadata={"folder_id": str(folder.id), "folder_path": folder.path, "source": "qwen" if folder_path == document.llm_suggested_folder else "rules"},
    )
