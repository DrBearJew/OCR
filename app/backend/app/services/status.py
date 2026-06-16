from __future__ import annotations

from collections.abc import Iterable

from app.models import BatchStatus, Document, DocumentState, ReviewState


ACTIVE_STATES = {
    DocumentState.queued_for_ocr,
    DocumentState.ocr_processing,
    DocumentState.ocr_done,
    DocumentState.metadata_processing,
    DocumentState.metadata_done,
}

SUCCESS_TERMINAL_STATES = {
    DocumentState.complete,
    DocumentState.duplicate,
}


def document_needs_review(document: Document) -> bool:
    if document.review_state == ReviewState.reviewed:
        return False
    return (
        document.processing_state == DocumentState.needs_review
        or document.review_state == ReviewState.needs_review
        or bool((document.metadata_json or {}).get("title_schema_valid") is False)
    )


def derive_parent_status(documents: Iterable[Document]) -> BatchStatus:
    docs = list(documents)
    if not docs:
        return BatchStatus.pending

    states = [doc.processing_state for doc in docs]
    if all(state == DocumentState.failed for state in states):
        return BatchStatus.failed
    if any(state == DocumentState.failed for state in states):
        return BatchStatus.partially_failed
    if any(state in ACTIVE_STATES for state in states):
        return BatchStatus.processing
    if all(state == DocumentState.uploaded for state in states):
        return BatchStatus.pending
    if any(document_needs_review(doc) for doc in docs):
        return BatchStatus.needs_review
    if all(state in SUCCESS_TERMINAL_STATES for state in states):
        return BatchStatus.complete
    return BatchStatus.processing
