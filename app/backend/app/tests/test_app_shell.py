from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.app_shell import activity, dashboard, failed_and_review, processing, router
from app.api.documents import bulk_documents, patch_document
from app.auth import require_admin
from app.db import get_db
from app.models import Batch, Document, DocumentEvent, DocumentState, ReviewState, SavedView, StageState
from app.schemas import DocumentBulkAction, DocumentPatch
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.events import record_event
from app.services.status import derive_parent_status


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


@pytest.fixture()
def shell_client(db_session: Session):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_admin] = lambda: "admin"
    with TestClient(app) as client:
        yield client


def test_collection_page_counts_review_independently_of_processing_state(db_session: Session, tmp_path: Path, shell_client) -> None:
    needs_review = make_shell_document(db_session, tmp_path)
    needs_review.review_state = ReviewState.needs_review
    reviewed = make_shell_document(db_session, tmp_path)
    reviewed.review_state = ReviewState.reviewed
    deleted = make_shell_document(db_session, tmp_path)
    deleted.review_state = ReviewState.needs_review
    deleted.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    response = shell_client.get("/api/collection-pages/dokumente")
    assert response.status_code == 200
    assert response.json()["status_counts"] == {"complete": 2}
    assert response.json()["needs_review_count"] == 1


def test_activity_legacy_and_page_default_limits(db_session: Session, tmp_path: Path, shell_client) -> None:
    doc = make_shell_document(db_session, tmp_path)
    db_session.add_all([
        DocumentEvent(document_id=doc.id, event_type="limit_test", message=str(index))
        for index in range(205)
    ])
    db_session.commit()

    legacy = shell_client.get("/api/activity", params={"event_type": "limit_test"})
    assert legacy.status_code == 200
    assert len(legacy.json()) == 200
    page = shell_client.get("/api/activity/page", params={"event_type": "limit_test"})
    assert page.status_code == 200
    assert len(page.json()["items"]) == page.json()["limit"] == 100
    assert page.json()["total_estimate"] == 205


def test_activity_pages_order_tied_timestamps_and_preserve_filters(db_session: Session, tmp_path: Path, shell_client) -> None:
    doc = make_shell_document(db_session, tmp_path)
    deleted = make_shell_document(db_session, tmp_path)
    base_time = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    deleted.deleted_at = base_time
    deleted.record_id = doc.record_id
    expected = []
    for index in [3, 1, 6, 2, 5, 0, 4]:
        created_at = base_time + timedelta(minutes=index // 3)
        row_id = uuid.UUID(int=index + 1)
        db_session.add(DocumentEvent(
            id=row_id, document_id=doc.id, event_type="cursor_test", actor="admin",
            source="manual", message=str(index), created_at=created_at,
        ))
        expected.append((created_at, str(row_id)))
    for overrides in [
        {"document_id": deleted.id}, {"event_type": "other"},
        {"actor": "system"}, {"source": "automatic"},
        {"created_at": base_time - timedelta(days=1)},
        {"created_at": base_time + timedelta(days=1)},
    ]:
        db_session.add(DocumentEvent(**{
            "document_id": doc.id, "event_type": "cursor_test", "actor": "admin",
            "source": "manual", "message": "excluded", "created_at": base_time, **overrides,
        }))
    db_session.commit()
    params = {
        "record_id": str(doc.record_id), "event_type": "cursor_test", "actor": "admin",
        "source": "manual", "date_from": "2026-02-01", "date_to": "2026-02-01", "limit": 2,
    }
    seen = []
    for page_index in range(4):
        response = shell_client.get("/api/activity/page", params=params)
        assert response.status_code == 200
        page = response.json()
        assert page["total_estimate"] == 7
        assert len(page["items"]) == (1 if page_index == 3 else 2)
        seen.extend(item["id"] for item in page["items"])
        if page_index == 3:
            assert page["next_cursor"] is None
        else:
            assert page["next_cursor"]
            params["cursor"] = page["next_cursor"]
    assert seen == [row_id for _, row_id in sorted(expected, reverse=True)]
    legacy = shell_client.get("/api/activity", params={key: value for key, value in params.items() if key != "cursor"})
    assert [item["id"] for item in legacy.json()] == seen[:2]


@pytest.mark.parametrize("cursor", ["", "a", "!!!!", "not-base64", "é", "/w=="])
def test_activity_page_rejects_malformed_base64(shell_client, cursor: str) -> None:
    response = shell_client.get("/api/activity/page", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid cursor"


@pytest.mark.parametrize("payload", [
    None, True, 42, "text", [], {},
    {"created_at": "2026-02-01T12:00:00"},
    {"created_at": [], "id": str(uuid.UUID(int=1))},
    {"created_at": "not-a-date", "id": str(uuid.UUID(int=1))},
    {"created_at": "2026-02-30T12:00:00", "id": str(uuid.UUID(int=1))},
    {"created_at": "2026-02-01T12:00:00", "id": []},
    {"created_at": "2026-02-01T12:00:00", "id": "not-a-uuid"},
    {"created_at": "2026-02-01T12:00:00", "id": 11111111111111111111111111111111},
])
def test_activity_page_rejects_malformed_cursor_payload(shell_client, payload) -> None:
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    response = shell_client.get("/api/activity/page", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid cursor"


def test_activity_page_rejects_invalid_characters_in_valid_cursor(shell_client) -> None:
    payload = {"created_at": "2026-02-01T12:00:00", "id": str(uuid.UUID(int=1))}
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    response = shell_client.get("/api/activity/page", params={"cursor": cursor + "!"})
    assert response.status_code == 422


def test_bulk_review_action_and_saved_view_model(db_session: Session, tmp_path: Path) -> None:
    doc = make_shell_document(db_session, tmp_path, state=DocumentState.needs_review)
    doc.review_state = ReviewState.needs_review
    doc.review_reason = "Needs human confirmation"
    db_session.commit()
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
    assert doc.review_reason is None
    assert doc.processing_state == DocumentState.complete
    assert doc.final_state == DocumentState.complete
    assert doc.reviewed_by == "admin"
    assert any(event.event_type == "review_state_updated" for event in doc.events)

    view = SavedView(name="Needs review", slug="needs-review", section="documents", filters_json={"review_state": "needs_review"})
    db_session.add(view)
    db_session.commit()
    assert db_session.query(SavedView).filter_by(section="documents").one().filters_json["review_state"] == "needs_review"


def test_filter_scope_bulk_actions_match_current_document_filters(db_session: Session, tmp_path: Path) -> None:
    matching: list[Document] = []
    for index in range(3):
        doc = make_shell_document(db_session, tmp_path, state=DocumentState.needs_review)
        doc.extracted_title = f"FilterBulk {index}"
        doc.review_state = ReviewState.needs_review
        doc.review_reason = "Needs review"
        matching.append(doc)
    other = make_shell_document(db_session, tmp_path, state=DocumentState.needs_review)
    other.extracted_title = "Other Bulk"
    other.review_state = ReviewState.needs_review
    db_session.commit()

    capped = DocumentBulkAction(
        selection_mode="filters",
        filters={"title": "FilterBulk", "state": "needs_review"},
        max_matches=2,
        action="set_review_state",
        review_state=ReviewState.reviewed,
    )
    try:
        bulk_documents(capped, db_session, _admin="admin")
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("filter-scope bulk action ignored max_matches")

    empty = DocumentBulkAction(
        selection_mode="filters",
        filters={},
        action="set_review_state",
        review_state=ReviewState.reviewed,
    )
    try:
        bulk_documents(empty, db_session, _admin="admin")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("filter-scope bulk action accepted empty filters")

    result = bulk_documents(
        DocumentBulkAction(
            selection_mode="filters",
            filters={"title": "FilterBulk", "state": "needs_review"},
            action="set_review_state",
            review_state=ReviewState.reviewed,
        ),
        db_session,
        _admin="admin",
    )
    assert result["updated"] == 3
    assert result["details"]["matched_total"] == 3
    assert result["details"]["selection_mode"] == "filters"

    for doc in matching:
        db_session.refresh(doc)
        assert doc.review_state == ReviewState.reviewed
        assert doc.processing_state == DocumentState.complete
    db_session.refresh(other)
    assert other.review_state == ReviewState.needs_review


def test_patch_reviewed_promotes_needs_review_document_to_complete(db_session: Session, tmp_path: Path) -> None:
    doc = make_shell_document(db_session, tmp_path, state=DocumentState.needs_review)
    doc.review_state = ReviewState.needs_review
    doc.review_reason = "Needs human confirmation"
    db_session.commit()

    result = patch_document(
        doc.id,
        DocumentPatch(review_state=ReviewState.reviewed, review_reason=None),
        db_session,
        _admin="admin",
    )
    db_session.refresh(doc)

    assert result.review_state == ReviewState.reviewed
    assert doc.review_state == ReviewState.reviewed
    assert doc.review_reason is None
    assert doc.processing_state == DocumentState.complete
    assert doc.final_state == DocumentState.complete
    assert doc.reviewed_by == "admin"


def test_reviewed_document_overrides_review_only_record_warnings(db_session: Session, tmp_path: Path) -> None:
    doc = make_shell_document(db_session, tmp_path, state=DocumentState.complete)
    doc.review_state = ReviewState.reviewed
    doc.metadata_json = {"title_schema_valid": False}
    db_session.commit()

    assert derive_parent_status([doc]).value == "complete"
