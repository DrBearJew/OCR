from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.api.admin import create_paperless_metadata, delete_paperless_metadata, update_paperless_metadata
from app.models import Batch, Correspondent, Document, DocumentType, StoragePathRule, Tag
from app.schemas import PaperlessMetadataPatch, PaperlessMetadataWrite
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.paperless_metadata import apply_paperless_metadata


def make_doc(db: Session, tmp_path: Path, text: str = "") -> Document:
    collection = ensure_collection(db, "Eingangsrechnung")
    record = create_record_for_upload(db, collection, "Profile test")
    batch = Batch(collection_name=collection.name, document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / "profile.txt"
    text = text or "O2 Telefonica invoice with mobile service and Steuer 2025"
    path.write_text(text, encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name=collection.name,
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="p" * 64,
        ocr_text=text,
        extracted_sender="TelefonicaGermany",
        extracted_title="TelefonicaGermany_1318249263/08_28/07/2025_26,49",
        llm_suggested_tags=["Mobilfunk", "Steuer"],
        llm_suggested_folder="Invoices/Mobile",
        metadata_json={
            "document_type": "Invoice",
            "qwen_candidates": {
                "document_type": {"value": "Invoice"},
                "suggested_tags": ["Mobilfunk"],
                "suggested_folder": "Invoices/Mobile",
            },
        },
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_paperless_profiles_assign_correspondent_type_tags_and_storage(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path)
    collection = doc.record.collection
    correspondent = Correspondent(
        collection_id=collection.id,
        name="O2",
        slug="o2",
        match_rules={"matching_algorithm": "any", "match": ["Telefonica", "O2"]},
    )
    document_type = DocumentType(
        collection_id=collection.id,
        name="Mobile Invoice",
        slug="mobile-invoice",
        match_rules={"matching_algorithm": "all", "match": ["invoice", "mobile"]},
    )
    tag = Tag(
        collection_id=collection.id,
        name="Mobilfunk",
        slug="mobilfunk",
        match_rules={"matching_algorithm": "automatic", "aliases": ["Mobilfunk"]},
    )
    storage = StoragePathRule(
        collection_id=collection.id,
        name="Mobile Folder",
        slug="mobile-folder",
        path_template="Invoices/Mobile",
        match_rules={"matching_algorithm": "automatic", "aliases": ["Invoices/Mobile"]},
    )
    db_session.add_all([correspondent, document_type, tag, storage])
    db_session.commit()

    apply_paperless_metadata(db_session, doc)
    db_session.commit()
    db_session.refresh(doc)

    assert doc.correspondent_id == correspondent.id
    assert doc.document_type_id == document_type.id
    assert doc.storage_path_id == storage.id
    assert [item.slug for item in doc.tags] == ["mobilfunk"]
    assignments = doc.metadata_json["paperless_assignments"]
    assert assignments["correspondent"]["source"] == "paperless_profile"
    assert assignments["document_type"]["reason"] == "all_rule"
    assert assignments["tags"][0]["name"] == "Mobilfunk"
    assert assignments["storage_path"]["name"] == "Mobile Folder"


def test_paperless_profile_assignment_preserves_manual_ids(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path)
    collection = doc.record.collection
    manual_type = DocumentType(collection_id=collection.id, name="Manual", slug="manual")
    matched_type = DocumentType(collection_id=collection.id, name="Matched", slug="matched", match_rules={"match": "invoice"})
    manual_storage = StoragePathRule(collection_id=collection.id, name="Manual", slug="manual")
    matched_storage = StoragePathRule(collection_id=collection.id, name="Matched", slug="matched", match_rules={"match": "invoice"})
    db_session.add_all([manual_type, matched_type, manual_storage, matched_storage])
    db_session.flush()
    doc.document_type_id = manual_type.id
    doc.storage_path_id = manual_storage.id
    doc.metadata_sources_json = {"document_type_id": {"source": "manual"}, "storage_path_id": {"source": "manual"}}
    db_session.commit()

    apply_paperless_metadata(db_session, doc)

    assert doc.document_type_id == manual_type.id
    assert doc.storage_path_id == manual_storage.id


def test_admin_metadata_profiles_can_be_updated_and_deleted(db_session: Session) -> None:
    collection = ensure_collection(db_session, "Eingangsrechnung")
    created = create_paperless_metadata(
        "tags",
        PaperlessMetadataWrite(
            collection_id=collection.id,
            name="Tax",
            color="#123456",
            match_rules={"match": "steuer"},
        ),
        db_session,
    )

    updated = update_paperless_metadata(
        "tags",
        created.id,
        PaperlessMetadataPatch(name="Steuer", match_rules={"matching_algorithm": "literal", "match": "Steuer"}),
        db_session,
    )
    assert updated.name == "Steuer"
    assert updated.slug == "steuer"
    assert updated.match_rules["matching_algorithm"] == "literal"

    deleted = delete_paperless_metadata("tags", created.id, db_session)
    assert deleted.id == created.id
    assert db_session.get(Tag, created.id) is None
