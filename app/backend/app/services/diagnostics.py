from __future__ import annotations

from typing import Any

from app.models import Document, DocumentState, ReviewState, StageState
from app.services.extraction import ExtractionInput, extract_metadata
from app.services.processing import missing_required_core_fields


IMPORTANT_FIELDS = {
    "title": "extracted_title",
    "sender": "extracted_sender",
    "recipient": "extracted_recipient",
    "invoice_number": "extracted_invoice_number",
    "date": "extracted_date",
    "amount": "extracted_amount",
    "payment_method": "extracted_payment_method",
}


def document_completion_diagnostics(document: Document) -> dict[str, Any]:
    qwen_info = _qwen_status(document)
    task_active = document.processing_state in {DocumentState.queued_for_ocr, DocumentState.ocr_processing, DocumentState.metadata_processing} and bool(document.processing_task_id)
    merged = {field: getattr(document, attr, None) for field, attr in IMPORTANT_FIELDS.items()}
    missing_required = missing_required_core_fields(document, merged)
    indexed = bool((document.metadata_json or {}).get("search_indexed")) or _search_index_is_implicit(document)
    checks = {
        "file_stored": bool(document.storage_path),
        "ocr_done": document.ocr_state in {StageState.done, StageState.skipped},
        "metadata_done": document.metadata_state in {StageState.done, StageState.skipped},
        "title_saved": bool(document.manual_title_override or document.extracted_title),
        "search_indexed": indexed,
        "required_fields_satisfied": not missing_required,
        "qwen_status": qwen_info["status"],
    }
    blockers: list[str] = []
    if not checks["file_stored"]:
        blockers.append("Original file was not stored.")
    if not checks["ocr_done"]:
        blockers.append("OCR is not done or explicitly skipped.")
    if not checks["metadata_done"]:
        blockers.append("Metadata extraction is not done or explicitly skipped.")
    if not checks["title_saved"]:
        blockers.append("No final title has been saved.")
    if not checks["search_indexed"]:
        blockers.append("Search index marker is missing.")
    if missing_required:
        blockers.append(f"Missing required fields: {', '.join(missing_required)}.")
    if document.error_message:
        blockers.append(f"Last error: {document.error_message}")
    if document.processing_state == DocumentState.queued_for_ocr and not document.processing_task_id:
        blockers.append("Queued for OCR but no task lease is recorded; worker may have been down when queued.")
    if document.processing_state in {DocumentState.ocr_processing, DocumentState.metadata_processing} and document.processing_task_id:
        blockers.append(f"Active {document.current_stage or 'processing'} task: {document.processing_task_id}")
    if document.review_state == ReviewState.needs_review and document.review_reason:
        blockers.append(f"Needs review: {document.review_reason}")
    return {
        "document_id": str(document.id),
        "processing_state": document.processing_state.value,
        "complete": document.processing_state == DocumentState.complete and not blockers,
        "checks": checks,
        "qwen": qwen_info,
        "missing_required_fields": missing_required,
        "last_error": document.error_message,
        "task": {
            "active": task_active,
            "task_id": document.processing_task_id if task_active else None,
            "current_stage": document.current_stage if task_active else None,
            "started_at": document.processing_started_at if task_active else None,
            "lease_until": document.processing_lease_until if task_active else None,
            "last_heartbeat_at": document.last_processing_heartbeat_at if task_active else None,
            "retry_after_at": document.retry_after_at if task_active else None,
            "attempt": document.processing_attempt if task_active else None,
            "total_attempts": document.processing_attempt or 0,
            "last_heartbeat_recorded_at": document.last_processing_heartbeat_at,
        },
        "blockers": blockers,
        "field_provenance": field_provenance(document),
    }


def field_provenance(document: Document) -> dict[str, dict[str, Any]]:
    sources = document.metadata_sources_json or {}
    locks = document.field_locks_json or {}
    result: dict[str, dict[str, Any]] = {}
    for field, attr in IMPORTANT_FIELDS.items():
        source_info = sources.get(field) if isinstance(sources.get(field), dict) else {}
        result[field] = {
            "value": getattr(document, attr, None),
            "source": source_info.get("source") or "deterministic",
            "confidence": source_info.get("confidence"),
            "evidence": source_info.get("evidence"),
            "locked": bool(locks.get(field)) or bool(document.metadata_locked),
        }
    return result


def extraction_preview(document: Document) -> dict[str, Any]:
    result = extract_metadata(
        ExtractionInput(
            collection_name=document.collection_name,
            ocr_text=document.ocr_text or "",
            original_filename=document.original_filename,
            created_at=document.created_at,
            existing_title=document.extracted_title,
        )
    )
    proposed = {
        "title": result.title,
        "sender": result.sender,
        "recipient": result.recipient,
        "invoice_number": result.invoice_number,
        "date": result.date,
        "amount": result.amount,
        "payment_method": result.payment_method,
    }
    current = {field: getattr(document, attr, None) for field, attr in IMPORTANT_FIELDS.items()}
    diff = {
        field: {"old": current.get(field), "new": value}
        for field, value in proposed.items()
        if (current.get(field) or "") != (value or "")
    }
    return {
        "document_id": str(document.id),
        "collection_name": document.collection_name,
        "current": current,
        "proposed": proposed,
        "diff": diff,
        "metadata": result.metadata,
        "field_provenance": field_provenance(document),
    }


def _qwen_status(document: Document) -> dict[str, Any]:
    refinement = (document.metadata_json or {}).get("qwen_refinement")
    if isinstance(refinement, dict):
        if refinement.get("disabled"):
            return {"status": "skipped", "reason": "disabled"}
        if _qwen_empty_response(refinement):
            return {"status": "not_run", "reason": "Qwen returned no metadata candidate"}
        if refinement.get("error"):
            return {"status": "failed", "reason": refinement.get("error")}
        if refinement.get("ok"):
            return {"status": "done", "confidence": document.llm_confidence}
    if document.llm_raw_response:
        metadata_brain = document.llm_raw_response.get("metadata_brain")
        if isinstance(metadata_brain, dict) and _qwen_empty_response(metadata_brain):
            return {"status": "not_run", "reason": "Qwen returned no metadata candidate"}
        if isinstance(metadata_brain, dict) and metadata_brain.get("error"):
            return {"status": "failed", "reason": metadata_brain.get("error")}
    return {"status": "not_run"}


def _qwen_empty_response(value: dict[str, Any]) -> bool:
    if value.get("empty_response") is True:
        return True
    if value.get("raw_text"):
        return False
    if value.get("error") == "Qwen returned empty metadata candidate response":
        return True
    raw_response = value.get("raw_response")
    if not isinstance(raw_response, dict):
        return False
    choices = raw_response.get("choices") or []
    message = choices[0].get("message") if choices else {}
    return not str((message or {}).get("content") or "").strip()


def _search_index_is_implicit(document: Document) -> bool:
    return bool(document.ocr_text) and document.ocr_state in {StageState.done, StageState.skipped}
