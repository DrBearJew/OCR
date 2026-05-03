from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, DocumentEvent


def append_processing_log(
    document: Document,
    stage: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> None:
    current = list(document.processing_log_json or [])
    current.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "message": message,
            "extra": extra or {},
        }
    )
    document.processing_log_json = current


def record_event(
    db: Session,
    document: Document,
    event_type: str,
    message: str | None = None,
    *,
    actor: str = "system",
    source: str = "automatic",
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DocumentEvent:
    append_processing_log(document, event_type, message or event_type, metadata)
    event = DocumentEvent(
        document_id=document.id,
        event_type=event_type,
        actor=actor,
        source=source,
        message=message,
        old_value=old_value,
        new_value=new_value,
        event_metadata=metadata or {},
    )
    db.add(event)
    return event
