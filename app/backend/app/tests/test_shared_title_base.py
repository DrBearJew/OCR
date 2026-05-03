from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.api.batches import upload_batch
from app.models import Batch, Document, DocumentState, StageState
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.processing import run_metadata_for_document
from app.services.shared_titles import apply_shared_title_base


def _doc(
    db: Session,
    tmp_path: Path,
    text: str,
    collection_name: str,
    record_id,
    filename: str,
) -> Document:
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    batch = Batch(collection_name=collection_name, document_count=1)
    db.add(batch)
    db.flush()
    document = Document(
        batch_id=batch.id,
        record_id=record_id,
        collection_name=collection_name,
        original_filename=filename,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256=(filename.replace(".", "") + "0" * 64)[:64],
        ocr_text=text,
        ocr_state=StageState.done,
        processing_state=DocumentState.ocr_done,
        final_state=DocumentState.ocr_done,
    )
    db.add(document)
    db.flush()
    return document


def _record(db: Session, collection_name: str, shared_base: str | None = "Telekom", apply: bool = True):
    collection = ensure_collection(db, collection_name)
    record = create_record_for_upload(db, collection, title=f"{collection_name} record")
    record.shared_title_base = shared_base
    record.apply_shared_title_to_documents = apply
    db.flush()
    return record


def test_multifile_shared_title_keeps_document_specific_invoice_suffixes(db_session: Session, tmp_path: Path) -> None:
    record = _record(db_session, "Eingangsrechnung")
    first = _doc(
        db_session,
        tmp_path,
        "Demo GmbH\nRechnungsnummer 12345\nRechnungsdatum 12.10.2024\nEndsumme 90,74",
        "Eingangsrechnung",
        record.id,
        "one.txt",
    )
    second = _doc(
        db_session,
        tmp_path,
        "Muster GmbH\nRechnungsnummer 12346\nRechnungsdatum 13.10.2024\nEndsumme 120,10",
        "Eingangsrechnung",
        record.id,
        "two.txt",
    )
    db_session.commit()

    run_metadata_for_document(db_session, first.id, qwen_enabled=False)
    run_metadata_for_document(db_session, second.id, qwen_enabled=False)
    db_session.refresh(first)
    db_session.refresh(second)

    assert first.extracted_title == "Telekom_12345_12/10/2024_90,74"
    assert second.extracted_title == "Telekom_12346_13/10/2024_120,10"
    assert first.extracted_invoice_number == "12345"
    assert second.extracted_invoice_number == "12346"
    assert first.extracted_amount == "90,74"
    assert second.extracted_amount == "120,10"
    assert first.extracted_sender == "Demo"
    assert second.extracted_sender == "Muster"


def test_disabling_shared_title_uses_extracted_base(db_session: Session, tmp_path: Path) -> None:
    record = _record(db_session, "Eingangsrechnung", shared_base="Telekom", apply=False)
    document = _doc(
        db_session,
        tmp_path,
        "Demo GmbH\nRechnungsnummer 12345\nRechnungsdatum 12.10.2024\nEndsumme 90,74",
        "Eingangsrechnung",
        record.id,
        "disabled.txt",
    )
    db_session.commit()

    run_metadata_for_document(db_session, document.id, qwen_enabled=False)
    db_session.refresh(document)

    assert document.extracted_title == "Demo_12345_12/10/2024_90,74"


def test_shared_title_collection_specific_base_replacement(db_session: Session, tmp_path: Path) -> None:
    cases = [
        (
            "Belege",
            "CommerceBank\nDatum 10.10.2024\nGesamtbetrag 90,74\nKarte",
            "Telekom_B_10/24_90,74_Karte",
            {"extracted_sender": "CommerceBank"},
        ),
        (
            "Ausgangsrechnung",
            "\n".join([
                "Demo AG",
                "Industriestrasse 1",
                "10000 Berlin",
                "Musterkunde & Co. KG",
                "Kundenweg 4",
                "30000 Bonn",
                "Rechnung-Nr. 2400",
                "Rechnungsdatum 15.07.2019",
                "Invoice Total 2,539,46",
            ]),
            "Telekom_2400_15/07/2019_2539,46",
            {"extracted_recipient": "MusterkundeCo"},
        ),
    ]
    for collection_name, text, expected_title, expected_fields in cases:
        record = _record(db_session, collection_name)
        document = _doc(db_session, tmp_path, text, collection_name, record.id, f"{collection_name}.txt")
        db_session.commit()
        run_metadata_for_document(db_session, document.id, qwen_enabled=False)
        db_session.refresh(document)
        assert document.extracted_title == expected_title
        for attr, expected in expected_fields.items():
            assert getattr(document, attr) == expected


def test_apply_shared_title_updates_only_unlocked_documents(db_session: Session, tmp_path: Path) -> None:
    record = _record(db_session, "Eingangsrechnung", shared_base="Telekom")
    unlocked = _doc(db_session, tmp_path, "", "Eingangsrechnung", record.id, "unlocked.txt")
    locked = _doc(db_session, tmp_path, "", "Eingangsrechnung", record.id, "locked.txt")
    unlocked.extracted_title = "Demo_12345_12/10/2024_90,74"
    locked.extracted_title = "Manual_12346_13/10/2024_120,10"
    locked.manual_title_override = "Manual_12346_13/10/2024_120,10"
    db_session.commit()

    record.shared_title_base = "Vodafone"
    updated = apply_shared_title_base(record, [unlocked, locked], only_unlocked=True)
    db_session.commit()
    db_session.refresh(unlocked)
    db_session.refresh(locked)

    assert updated == 1
    assert unlocked.extracted_title == "Vodafone_12345_12/10/2024_90,74"
    assert locked.extracted_title == "Manual_12346_13/10/2024_120,10"


def _make_upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def test_upload_persists_shared_title_record_options(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: None)
    result = asyncio.run(
        upload_batch(
            collection_name="Eingangsrechnung",
            label=None,
            document_metadata_json=json.dumps([{}, {}]),
            processing_options_json=json.dumps({"auto_ocr": False, "qwen_enabled": False}),
            record_metadata_json=json.dumps({"shared_title_base": "Telekom", "apply_shared_title_to_documents": True}),
            files=[
                _make_upload("one.jpg", b"one", "image/jpeg"),
                _make_upload("two.jpg", b"two", "image/jpeg"),
            ],
            db=db_session,
        )
    )
    documents = db_session.scalars(select(Document).where(Document.batch_id == result.id)).all()
    assert len(documents) == 2
    assert documents[0].record is not None
    assert documents[0].record.shared_title_base == "Telekom"
    assert documents[0].record.apply_shared_title_to_documents is True
