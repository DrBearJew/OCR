from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, CustomFieldDefinition, CustomFieldType, Document, FieldValueSource, StageState
from app.services.collections import (
    create_record_for_upload,
    ensure_collection,
    update_record_status,
    upsert_custom_field_value,
)
from app.services.processing import run_metadata_for_document
from app.services.search import search_documents


def test_multi_file_record_keeps_per_document_metadata_isolated(db_session: Session, tmp_path: Path) -> None:
    collection = ensure_collection(db_session, "Eingangsrechnung")
    record = create_record_for_upload(db_session, collection, "Two invoices")
    batch = Batch(collection_name="Eingangsrechnung", document_count=2)
    db_session.add(batch)
    db_session.flush()
    samples = [
        ("demo.txt", "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"),
        ("muster.txt", "Muster GmbH\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nGrand Total 222,51"),
    ]
    docs: list[Document] = []
    for filename, text in samples:
        path = tmp_path / filename
        path.write_text(text, encoding="utf-8")
        doc = Document(
            batch_id=batch.id,
            record_id=record.id,
            collection_name="Eingangsrechnung",
            original_filename=filename,
            storage_path=str(path),
            mime_type="text/plain",
            file_size=len(text),
            sha256=filename.ljust(64, "0")[:64],
            ocr_text=text,
            ocr_state=StageState.done,
            metadata_state=StageState.done,
            processing_state="ocr_done",
            final_state="ocr_done",
        )
        db_session.add(doc)
        docs.append(doc)
    db_session.commit()

    for doc in docs:
        run_metadata_for_document(db_session, doc.id)
    update_record_status(db_session, record.id)
    db_session.refresh(record)

    assert record.document_count == 2
    assert record.status == BatchStatus.complete
    assert {db_session.get(Document, doc.id).extracted_title for doc in docs} == {
        "Demo_PR400000005_12/10/2020_205,25",
        "Muster_M1675_29/10/2020_222,51",
    }


def test_custom_field_value_lock_survives_reprocessing_candidate(db_session: Session, tmp_path: Path) -> None:
    collection = ensure_collection(db_session, "Belege")
    record = create_record_for_upload(db_session, collection, "Receipt")
    field = CustomFieldDefinition(
        collection_id=collection.id,
        name="Cost Center",
        slug="cost_center",
        field_type=CustomFieldType.string,
        searchable=True,
    )
    batch = Batch(collection_name="Belege", document_count=1)
    db_session.add_all([field, batch])
    db_session.flush()
    path = tmp_path / "receipt.txt"
    path.write_text("ACME\nDatum 04.04.2026", encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Belege",
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=10,
        sha256="9" * 64,
    )
    db_session.add(doc)
    db_session.commit()

    saved = upsert_custom_field_value(db_session, doc, field, "MANUAL-1", source=FieldValueSource.manual)
    saved.locked = True
    db_session.commit()
    upsert_custom_field_value(db_session, doc, field, "AUTO-2", source=FieldValueSource.deterministic, force=False)
    db_session.refresh(saved)
    assert saved.normalized_value == "MANUAL-1"

    upsert_custom_field_value(db_session, doc, field, "AUTO-2", source=FieldValueSource.deterministic, force=True)
    db_session.commit()
    db_session.refresh(saved)
    assert saved.normalized_value == "AUTO-2"


def test_search_can_filter_searchable_custom_fields(db_session: Session, tmp_path: Path) -> None:
    collection = ensure_collection(db_session, "Dokumente")
    record = create_record_for_upload(db_session, collection, "Custom searchable")
    field = CustomFieldDefinition(
        collection_id=collection.id,
        name="Project",
        slug="project",
        field_type=CustomFieldType.string,
        searchable=True,
    )
    batch = Batch(collection_name="Dokumente", document_count=1)
    db_session.add_all([field, batch])
    db_session.flush()
    path = tmp_path / "doc.txt"
    path.write_text("needle body", encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Dokumente",
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=11,
        sha256="8" * 64,
        ocr_text="needle body",
    )
    db_session.add(doc)
    db_session.flush()
    upsert_custom_field_value(db_session, doc, field, "Project Phoenix", source=FieldValueSource.manual)
    db_session.commit()

    results = search_documents(db_session, "needle", custom_field="project", custom_value="Phoenix")
    assert [row.document_id for row in results] == [doc.id]
