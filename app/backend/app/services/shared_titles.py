from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models import Document, Record
from app.services.extraction import replace_title_base, sanitize_shared_title_base


def title_is_locked(document: Document, *, force: bool = False) -> bool:
    if force:
        return False
    if document.manual_title_override:
        return True
    if document.metadata_locked:
        return True
    locks = document.field_locks_json or {}
    if isinstance(locks, dict) and locks.get("title"):
        return True
    source = (document.metadata_sources_json or {}).get("title")
    return isinstance(source, dict) and source.get("source") == "manual" and bool(document.extracted_title)


def get_title_base_for_document(
    document: Document,
    record: Record | None = None,
    collection_rules: dict[str, Any] | None = None,
) -> str:
    del collection_rules
    active_record = record or document.record
    if document.manual_title_override:
        return _extract_base(document.collection_name, document.manual_title_override)
    if active_record and active_record.apply_shared_title_to_documents and active_record.shared_title_base:
        shared = sanitize_shared_title_base(active_record.shared_title_base)
        if shared:
            return shared
    if document.collection_name == "Ausgangsrechnung":
        return sanitize_shared_title_base(document.extracted_recipient) or "Dok"
    if document.collection_name == "Eingangsrechnung":
        return sanitize_shared_title_base(document.extracted_sender) or "Dok"
    if document.collection_name == "Belege":
        return sanitize_shared_title_base(document.extracted_sender) or "Dok"
    return _extract_base(document.collection_name, document.extracted_title) or "Dok"


def generate_document_title(
    document: Document,
    record: Record | None = None,
    collection_rules: dict[str, Any] | None = None,
) -> str:
    del collection_rules
    active_record = record or document.record
    current = document.extracted_title or document.original_filename
    if active_record and active_record.apply_shared_title_to_documents and active_record.shared_title_base:
        return replace_title_base(document.collection_name, current, active_record.shared_title_base)
    return current


def apply_shared_title_base(record: Record, documents: Iterable[Document], only_unlocked: bool = True) -> int:
    if not record.apply_shared_title_to_documents or not record.shared_title_base:
        return 0
    updated = 0
    for document in documents:
        if only_unlocked and title_is_locked(document):
            continue
        before = document.extracted_title
        next_title = generate_document_title(document, record)
        if next_title and next_title != before:
            document.extracted_title = next_title
            sources = dict(document.metadata_sources_json or {})
            sources["title_base"] = {
                "source": "shared_record",
                "confidence": 100,
                "record_id": str(record.id),
            }
            title_source = sources.get("title")
            title_source_info = title_source if isinstance(title_source, dict) else {}
            if title_source_info.get("source") != "manual":
                sources["title"] = {
                    "source": "deterministic",
                    "confidence": title_source_info.get("confidence", 90),
                    "shared_base_applied": True,
                }
            document.metadata_sources_json = sources
            document.metadata_json = {
                **(document.metadata_json or {}),
                "shared_title_base": sanitize_shared_title_base(record.shared_title_base),
                "shared_title_applied": True,
            }
            updated += 1
    return updated


def _extract_base(collection_name: str, title: str | None) -> str:
    if not title:
        return ""
    if collection_name == "Belege":
        return sanitize_shared_title_base(title.split("_B_", 1)[0])
    return sanitize_shared_title_base(title.split("_", 1)[0])
