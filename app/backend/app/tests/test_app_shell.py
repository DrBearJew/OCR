from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.api.app_shell import activity, dashboard, failed_and_review, processing
from app.api.documents import bulk_documents
from app.models import Batch, Document, DocumentState, ReviewState, SavedView, StageState
from app.schemas import DocumentBulkAction
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.events import record_event


def make_shell_document(db: Session, tmp_path: Path, *, state: DocumentState = DocumentState.complete) -> Document:
    collection = ensure_collection(db, "Dokumente")
    record = create_record_for_upload(db, collection, "Shell")
    batch = Batch(collection_name="Dokumente", document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / "shell.txt"
    path.write_text("shell needle", encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Dokumente",
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=12,
        sha256="6" * 64,
        processing_state=state,
        final_state=state,
        ocr_state=StageState.done,
        metadata_state=StageState.done,
        ocr_text="shell needle",
        extracted_title="Shell_Doc",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_dashboard_processing_failed_and_activity_shell_endpoints(db_session: Session, tmp_path: Path) -> None:
    complete = make_shell_document(db_session, tmp_path)
    failed = make_shell_document(db_session, tmp_path, state=DocumentState.failed)
    failed.review_state = ReviewState.needs_review
    failed.review_reason = "missing amount"
    record_event(db_session, complete, "manual_edit", "Edited title", actor="admin", source="manual")
    db_session.commit()

    dash = dashboard(db_session)
    assert dash["status_counts"]["complete"] >= 1
    assert any(row["collection"] == "Dokumente" for row in dash["collection_counts"])

    failed_payload = failed_and_review(db_session)
    assert any(row["id"] == str(failed.id) for row in failed_payload["failed_documents"])
    assert any(row["id"] == str(failed.id) for row in failed_payload["needs_review_documents"])

    queue_payload = processing(db_session)
    assert "summary" in queue_payload

    events = activity(actor="admin", db=db_session)
    assert any(row["event_type"] == "manual_edit" and row["document_id"] == str(complete.id) for row in events)


def test_bulk_review_action_and_saved_view_model(db_session: Session, tmp_path: Path) -> None:
    doc = make_shell_document(db_session, tmp_path)
    result = bulk_documents(
        DocumentBulkAction(
            document_ids=[doc.id],
            action="set_review_state",
            review_state=ReviewState.reviewed,
        ),
        db_session,
        _admin="admin",
    )
    db_session.refresh(doc)
    assert result["updated"] == 1
    assert doc.review_state == ReviewState.reviewed
    assert doc.reviewed_by == "admin"
    assert any(event.event_type == "review_state_updated" for event in doc.events)

    view = SavedView(name="Needs review", slug="needs-review", section="documents", filters_json={"review_state": "needs_review"})
    db_session.add(view)
    db_session.commit()
    assert db_session.query(SavedView).filter_by(section="documents").one().filters_json["review_state"] == "needs_review"
