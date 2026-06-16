from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.collections import create_collection, update_collection
from app.api.documents import patch_document
from app.api.folders import delete_folder, folder_contents, update_folder
from app.api.records import patch_record
from app.config import Settings
from app.models import Batch, Collection, CustomFieldDefinition, CustomFieldType, Document, DocumentState, DocumentType, Folder, OCRMode, Record, ReviewState, StageState, StoragePathRule, Tag
from app.schemas import CollectionCreate, CollectionUpdate, DocumentPatch, FolderWrite, RecordPatch
from app.services.collections import create_record_for_upload, ensure_collection, upsert_custom_field_value
from app.services.folders import create_folder
from app.services.paperless_metadata import apply_paperless_metadata
from app.services.processing import is_stale
from app.services.reconciliation import reconcile_stuck_documents
from app.services.search import search_documents
from app.services.storage import LocalStorage


def make_doc(db: Session, tmp_path: Path, text: str = "needle", collection_name: str = "Dokumente") -> Document:
    collection = ensure_collection(db, collection_name)
    record = create_record_for_upload(db, collection, "Record")
    batch = Batch(collection_name=collection_name, document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / f"{collection_name}.txt"
    path.write_text(text, encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name=collection_name,
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="h" * 64,
        ocr_text=text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_reconcile_does_not_requeue_fresh_docs_but_requeues_stale(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id: queued.append(("ocr", str(doc_id))))
    monkeypatch.setattr("app.services.reconciliation._enqueue_metadata", lambda doc_id, force=False: queued.append(("metadata", str(doc_id))))

    fresh = make_doc(db_session, tmp_path, sha_text := "fresh")
    fresh.processing_state = DocumentState.queued_for_ocr
    fresh.final_state = DocumentState.queued_for_ocr
    fresh.updated_at = datetime.now(timezone.utc)
    stale = make_doc(db_session, tmp_path, "stale")
    stale.processing_state = DocumentState.ocr_done
    stale.ocr_state = StageState.done
    stale.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()

    result = reconcile_stuck_documents(db_session)

    assert result["queued"] == 1
    assert ("metadata", str(stale.id)) in queued
    assert all(str(fresh.id) not in item for _, item in queued)


def test_is_stale_uses_updated_at_for_missing_heartbeat(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path)
    doc.processing_state = DocumentState.queued_for_ocr
    doc.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    doc.last_processing_heartbeat_at = None
    assert is_stale(doc) is True
    doc.processing_state = DocumentState.complete
    assert is_stale(doc) is False


def test_collection_create_conflict_and_partial_patch(db_session: Session) -> None:
    create_collection(CollectionCreate(name="Invoices", slug="invoices"), db_session)
    try:
        create_collection(CollectionCreate(name="Invoices", slug="invoices2"), db_session)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("duplicate collection create was accepted")

    collection = db_session.query(Collection).filter_by(slug="invoices").one()
    updated = update_collection(collection.id, CollectionUpdate(color="#00ff00"), db_session)
    assert updated.color == "#00ff00"
    assert updated.name == "Invoices"


def test_record_and_document_patch_validate_folders_and_server_fields(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, collection_name="Eingangsrechnung")
    other_collection = ensure_collection(db_session, "Belege")
    folder = create_folder(db_session, "Other", collection_id=other_collection.id)
    db_session.commit()

    try:
        patch_record(doc.record_id, RecordPatch(folder_id=folder.id), db_session)  # type: ignore[arg-type]
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("cross-collection record folder was accepted")

    patch = DocumentPatch.model_validate({"metadata_sources_json": {"amount": {"source": "manual"}}})
    patch_document(doc.id, patch, db_session, "admin")
    db_session.refresh(doc)
    assert "amount" not in doc.metadata_sources_json
    patch = DocumentPatch.model_validate({"extracted_title": "Manual"})
    patch_document(doc.id, patch, db_session, "admin")
    db_session.refresh(doc)
    assert doc.extracted_title == "Manual"
    assert doc.metadata_sources_json.get("title", {}).get("source") == "manual"
    assert "metadata_sources_json" not in patch.model_fields_set


def test_folder_descendant_move_and_nonempty_delete_rejected(db_session: Session, tmp_path: Path) -> None:
    parent = create_folder(db_session, "Parent")
    child = create_folder(db_session, "Child", parent_id=parent.id)
    doc = make_doc(db_session, tmp_path)
    doc.folder_id = child.id
    db_session.commit()

    try:
        update_folder(parent.id, FolderWrite(parent_id=child.id, name="Parent"), db_session)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("folder cycle was accepted")

    try:
        delete_folder(parent.id, db_session)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("non-empty folder was deleted")


def test_folder_contents_are_paginated_and_filterable(db_session: Session, tmp_path: Path) -> None:
    parent = create_folder(db_session, "Archive")
    child = create_folder(db_session, "Invoices", parent_id=parent.id)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    docs: list[Document] = []
    for index in range(3):
        doc = make_doc(db_session, tmp_path, f"FolderNeedle {index}")
        doc.folder_id = child.id
        doc.extracted_title = f"FolderNeedle {index}"
        doc.updated_at = base_time + timedelta(minutes=index)
        docs.append(doc)
    unfiled = make_doc(db_session, tmp_path, "LooseNeedle")
    unfiled.extracted_title = "LooseNeedle"
    unfiled.updated_at = base_time + timedelta(minutes=5)
    db_session.commit()

    first = folder_contents(kind="documents", scope="subtree", folder_id=parent.id, q="FolderNeedle", limit=2, db=db_session)
    assert first.total_estimate == 3
    assert len(first.items) == 2
    assert first.next_cursor
    assert all(item.folder_id == child.id for item in first.items)

    second = folder_contents(kind="documents", scope="subtree", folder_id=parent.id, q="FolderNeedle", limit=2, cursor=first.next_cursor, db=db_session)
    assert len(second.items) == 1
    assert second.next_cursor is None

    unfiled_page = folder_contents(kind="documents", scope="unfiled", q="LooseNeedle", db=db_session)
    assert unfiled_page.total_estimate == 1
    assert unfiled_page.items[0].id == unfiled.id

    record_page = folder_contents(kind="records", scope="unfiled", q="Record", db=db_session)
    assert record_page.total_estimate >= 1
    assert all(item.kind == "record" for item in record_page.items)


def test_delete_folder_can_soft_delete_contained_documents(db_session: Session, tmp_path: Path) -> None:
    parent = create_folder(db_session, "DeleteMe")
    child = create_folder(db_session, "Nested", parent_id=parent.id)
    document = make_doc(db_session, tmp_path, "delete folder contents")
    document.folder_id = child.id
    db_session.commit()

    try:
        delete_folder(parent.id, db=db_session)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:  # pragma: no cover
        raise AssertionError("non-empty folder delete should require delete_contents")

    deleted = delete_folder(parent.id, delete_contents=True, db=db_session)
    assert deleted.deleted_at is not None
    db_session.refresh(document)
    db_session.refresh(child)
    assert document.deleted_at is not None
    assert child.deleted_at is not None



def test_search_filters_coerce_enums_and_distinct_combined_filters(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "AlphaNeedle", "Dokumente")
    collection = doc.record.collection
    field = CustomFieldDefinition(collection_id=collection.id, name="Project", slug="project", field_type=CustomFieldType.string, searchable=True)
    tag = Tag(collection_id=collection.id, name="Tax", slug="tax")
    db_session.add_all([field, tag])
    db_session.flush()
    upsert_custom_field_value(db_session, doc, field, "Alpha")
    doc.tags.append(tag)
    doc.processing_state = DocumentState.complete
    doc.ocr_state = StageState.done
    doc.review_state = ReviewState.reviewed
    doc.ocr_mode = OCRMode.redo
    db_session.commit()

    rows = search_documents(db_session, "AlphaNeedle", custom_field="project", custom_value="Alpha", tag_id=str(tag.id), status="complete", review_state="reviewed", ocr_mode="redo")
    assert [row.document_id for row in rows] == [doc.id]
    try:
        search_documents(db_session, "AlphaNeedle", status="bogus")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("invalid enum filter was accepted")


def test_paperless_mapping_preserves_manual_doc_type_and_storage(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path)
    collection = doc.record.collection
    manual_type = DocumentType(collection_id=collection.id, name="Manual Type", slug="manual-type")
    manual_storage = StoragePathRule(collection_id=collection.id, name="Manual Storage", slug="manual-storage")
    db_session.add_all([manual_type, manual_storage])
    db_session.flush()
    doc.document_type_id = manual_type.id
    doc.storage_path_id = manual_storage.id
    doc.metadata_sources_json = {"document_type_id": {"source": "manual"}, "storage_path_id": {"source": "manual"}}
    db_session.commit()

    apply_paperless_metadata(db_session, doc)
    assert doc.document_type_id == manual_type.id
    assert doc.storage_path_id == manual_storage.id


def test_storage_resolve_rejects_traversal_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    good = root / "ok.txt"
    good.write_text("ok", encoding="utf-8")
    storage = LocalStorage(Settings(storage_root=root))
    assert storage.resolve(str(good)) == good.resolve()

    try:
        storage.resolve(str(root / ".." / "outside.txt"))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("path traversal was accepted")

    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    symlink = root / "link.txt"
    try:
        symlink.symlink_to(outside)
    except OSError:
        return
    try:
        storage.resolve(str(symlink))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("symlink escape was accepted")
