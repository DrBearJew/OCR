from __future__ import annotations

import asyncio
from io import BytesIO
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from starlette.datastructures import Headers, UploadFile
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.batches import upload_batch
from app.api.documents import apply_document_extraction_preview, document_diagnostics, preview_document_extraction, preview_document_page, reextract_document, reindex_document, run_document_ocr
from app.api.admin import reindex_documents, storage_integrity
from app.api.app_shell import failed_and_review
from app.api.documents import list_documents
from app.cli import import_legacy
from app.models import Batch, Document, DocumentEvent, DocumentPage, DocumentState, ReviewState, StageState
from app.services.extraction import ExtractionInput, extract_metadata, normalize_amount
from app.services.ocr_glm import OCRProviderError, OCRResult
from app.services.processing import (
    clear_processing_lease,
    mark_duplicate_document,
    estimate_ocr_task_budget,
    queue_ocr,
    reserve_processing_task,
    run_metadata_for_document,
    run_ocr_for_document,
)
from app.services.reconciliation import reconcile_stuck_documents
from app.services.search import search_documents
from app.services.document_assets import inspect_page_count
from app.services.storage import LocalStorage


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ocr_samples"


class StaticProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self, file_path: str) -> OCRResult:
        return OCRResult(text=self.text, raw_response={"pages": [{"text": self.text}]})


class FailingProvider:
    def extract_text(self, file_path: str) -> OCRResult:
        raise OCRProviderError("should not run")


def make_doc(db: Session, tmp_path: Path, text: str, collection: str = "Eingangsrechnung", sha: str = "a" * 64) -> Document:
    path = tmp_path / f"{collection}_{sha[:6]}.txt"
    path.write_text(text, encoding="utf-8")
    batch = Batch(collection_name=collection, document_count=1)
    db.add(batch)
    db.flush()
    doc = Document(
        batch_id=batch.id,
        collection_name=collection,
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256=sha,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_known_old_system_golden_fixtures() -> None:
    cases = [
        ("267", "Belege", "ACME_B_04/26_NA_NA"),
        ("269", "Belege", "Dok_B_10/22_NA_NA"),
        ("272", "Belege", "CommerceBank_B_04/26_NA_NA"),
        ("273", "Belege", "Dok_B_04/25_NA_NA"),
        ("275", "Eingangsrechnung", "Demo_PR400000005_12/10/2020_205,25"),
        ("276", "Eingangsrechnung", "FensterBeruhmt_7453_08/11/2015_2975,00"),
        ("277", "Ausgangsrechnung", "HabermannSohne_M1675_29/10/2020_222,51"),
        ("291", "Ausgangsrechnung", "MusterkundeCo_2400_15/07/2019_2539,46"),
    ]
    for old_id, collection, expected in cases:
        text = (FIXTURE_DIR / f"{old_id}.txt").read_text(encoding="utf-8")
        result = extract_metadata(ExtractionInput(collection, text, f"{old_id}.pdf"))
        assert result.title == expected


def test_known_bad_titles_and_garbage_amounts_are_rejected() -> None:
    bad_tokens = [
        "ShipToBill",
        "NameVornameVed",
        "FehlendeGrundimmunisierungenNach",
        "Sauglingeund",
        "WORLDHEALTHORGANIZATION",
        "BGM",
        "FANGO",
        "Microsoft",
    ]
    for token in bad_tokens:
        result = extract_metadata(ExtractionInput("Belege", f"{token}\nDatum 04.04.2026", f"{token}.pdf"))
        assert result.title.startswith("Dok_B_04/26_")
        assert token not in result.title

    assert normalize_amount("42424242,00") == "42424242,00"
    text = "Demo GmbH\nRechnungsnummer X100\nRechnungsdatum 01.01.2024\nNetto 42424242,00\nGesamtbetrag 2,539,46"
    result = extract_metadata(ExtractionInput("Eingangsrechnung", text, "demo.pdf"))
    assert result.title.endswith("_2539,46")
    assert "42424242,00" not in result.title


def test_duplicate_task_delivery_is_idempotent(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, StaticProvider(text), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.ocr_done
    assert doc.page_count == 1

    run_ocr_for_document(db_session, doc.id, FailingProvider(), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.ocr_done
    assert doc.error_message is None

    run_metadata_for_document(db_session, doc.id)
    db_session.refresh(doc)
    attempt_after_complete = doc.processing_attempt
    run_metadata_for_document(db_session, doc.id)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.complete
    assert doc.processing_attempt == attempt_after_complete
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"


def test_reconcile_stale_documents_requeues_correct_stage(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id: queued.append(("ocr", str(doc_id))))
    monkeypatch.setattr("app.services.reconciliation._enqueue_metadata", lambda doc_id, force=False: queued.append(("metadata", str(doc_id))))
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    ocr_doc = make_doc(db_session, tmp_path, "stale", sha="b" * 64)
    ocr_doc.processing_state = DocumentState.ocr_processing
    ocr_doc.ocr_state = StageState.processing
    ocr_doc.last_processing_heartbeat_at = stale
    metadata_doc = make_doc(db_session, tmp_path, "done", sha="c" * 64)
    metadata_doc.processing_state = DocumentState.ocr_done
    metadata_doc.ocr_state = StageState.done
    metadata_doc.updated_at = stale
    db_session.commit()

    result = reconcile_stuck_documents(db_session)
    assert result["queued"] == 2
    assert ("ocr", str(ocr_doc.id)) in queued
    assert ("metadata", str(metadata_doc.id)) in queued


def test_reconcile_requeues_orphaned_queued_docs_without_waiting_for_stale(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id, task_id=None: queued.append(("ocr", str(doc_id))))
    monkeypatch.setattr("app.services.reconciliation._enqueue_metadata", lambda doc_id, force=False, task_id=None: queued.append(("metadata", str(doc_id))))

    ocr_doc = make_doc(db_session, tmp_path, "fresh queued", sha="9" * 64)
    ocr_doc.processing_state = DocumentState.queued_for_ocr
    ocr_doc.final_state = DocumentState.queued_for_ocr
    ocr_doc.ocr_state = StageState.pending
    ocr_doc.error_message = "Task publish failed for ocr: redis unavailable"
    clear_processing_lease(ocr_doc)

    metadata_doc = make_doc(db_session, tmp_path, "fresh metadata", sha="8" * 64)
    metadata_doc.processing_state = DocumentState.ocr_done
    metadata_doc.final_state = DocumentState.ocr_done
    metadata_doc.ocr_state = StageState.done
    metadata_doc.metadata_state = StageState.pending
    metadata_doc.error_message = "Task publish failed for metadata: redis unavailable"
    clear_processing_lease(metadata_doc)
    db_session.commit()

    result = reconcile_stuck_documents(db_session)

    assert result["queued"] == 2
    assert ("ocr", str(ocr_doc.id)) in queued
    assert ("metadata", str(metadata_doc.id)) in queued


def test_reconcile_skips_queued_doc_with_active_lease(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    queued: list[str] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id, task_id=None: queued.append(str(doc_id)))
    document = make_doc(db_session, tmp_path, "leased", sha="7" * 64)
    document.processing_state = DocumentState.queued_for_ocr
    document.final_state = DocumentState.queued_for_ocr
    document.ocr_state = StageState.pending
    reserve_processing_task(document, task_id="active-task", stage="ocr")
    db_session.commit()

    result = reconcile_stuck_documents(db_session)

    assert result["queued"] == 0
    assert queued == []


def test_duplicate_detection_links_without_reprocessing(db_session: Session, tmp_path: Path) -> None:
    original = make_doc(db_session, tmp_path, "original", sha="d" * 64)
    original.ocr_text = "Original OCR"
    original.extracted_title = "Original_Title"
    original.processing_state = DocumentState.complete
    original.ocr_state = StageState.done
    original.metadata_state = StageState.done
    duplicate = make_doc(db_session, tmp_path, "duplicate", sha="d" * 64)
    mark_duplicate_document(db_session, duplicate, original)
    db_session.commit()

    db_session.refresh(duplicate)
    assert duplicate.processing_state == DocumentState.duplicate
    assert duplicate.duplicate_of_document_id == original.id
    assert duplicate.extracted_title == "Original_Title"


def test_import_legacy_folder_with_json_metadata(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    files_dir = tmp_path / "legacy"
    files_dir.mkdir()
    source = files_dir / "legacy-demo.txt"
    source.write_text("Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25", encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps([
            {
                "filename": source.name,
                "legacy_document_id": "275",
                "collection": "Eingangsrechnung",
                "mime_type": "text/plain",
                "ocr_text": source.read_text(encoding="utf-8"),
            }
        ]),
        encoding="utf-8",
    )

    result = import_legacy(db_session, files_dir, str(metadata), "Eingangsrechnung", "paperless")
    assert result["imported"] == 1
    doc = db_session.scalars(select(Document).where(Document.legacy_document_id == "275")).one()
    assert doc.processing_state == DocumentState.complete
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"


def test_search_filters_and_metadata_ranking(db_session: Session, tmp_path: Path) -> None:
    first = make_doc(db_session, tmp_path, "Needle OCR", collection="Belege", sha="e" * 64)
    first.ocr_text = "Needle body"
    first.extracted_title = "Needle_Title"
    first.processing_state = DocumentState.complete
    first.ocr_state = StageState.done
    first.metadata_state = StageState.done
    second = make_doc(db_session, tmp_path, "Needle OCR", collection="Eingangsrechnung", sha="f" * 64)
    second.ocr_text = "Needle body"
    second.extracted_title = "Other"
    second.original_filename = "needle-file.txt"
    second.processing_state = DocumentState.complete
    second.ocr_state = StageState.done
    second.metadata_state = StageState.done
    db_session.commit()

    results = search_documents(db_session, "Needle", collection_name="Belege")
    assert [item.document_id for item in results] == [first.id]
    ranked = search_documents(db_session, "Needle")
    assert ranked[0].rank >= ranked[1].rank


def test_document_events_capture_processing_timeline(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    queue_ocr(db_session, doc)
    db_session.commit()
    run_ocr_for_document(db_session, doc.id, StaticProvider(text), enqueue_metadata=False)
    run_metadata_for_document(db_session, doc.id)
    events = db_session.scalars(select(DocumentEvent).where(DocumentEvent.document_id == doc.id)).all()
    event_types = {event.event_type for event in events}
    assert {"queued_for_ocr", "ocr_queued", "ocr_started", "ocr_done", "metadata_started", "metadata_deterministic_done", "title_generated", "search_indexed", "complete"} <= event_types


def test_pdf_preview_page_renders_on_demand(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setenv("STORAGE_PATH", str(storage_root))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    pdf_path = storage_root / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    batch = Batch(collection_name="Dokumente", document_count=1)
    db_session.add(batch)
    db_session.flush()
    document = Document(
        batch_id=batch.id,
        collection_name="Dokumente",
        original_filename="invoice.pdf",
        storage_path=str(pdf_path),
        mime_type="application/pdf",
        file_size=pdf_path.stat().st_size,
        sha256="p" * 64,
    )
    db_session.add(document)
    db_session.commit()

    def fake_render(path: str, document_id, *, page_limit: int, image_dpi: int) -> list[str]:
        assert path == str(pdf_path.resolve())
        assert page_limit == 1
        assert image_dpi == config_module.get_settings().ocr_image_dpi
        page_dir = storage_root / "pages" / str(document_id)
        page_dir.mkdir(parents=True)
        page_path = page_dir / "page_0001.jpg"
        page_path.write_bytes(b"jpeg")
        return [str(page_path)]

    monkeypatch.setattr("app.api.documents.render_pdf_pages", fake_render)
    response = preview_document_page(document.id, 1, db=db_session, _admin="admin")

    assert response.media_type == "image/jpeg"
    assert Path(response.path) == storage_root / "pages" / str(document.id) / "page_0001.jpg"
    page = db_session.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)).one()
    assert page.page_number == 1
    assert page.rendered_image_path == str(response.path)
    config_module.get_settings.cache_clear()


def test_document_diagnostics_extraction_preview_and_reindex(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    doc.ocr_text = text
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.ocr_done
    db_session.commit()

    diagnostics = document_diagnostics(doc.id, db=db_session, _admin="admin")
    assert diagnostics["checks"]["ocr_done"] is True
    assert diagnostics["checks"]["metadata_done"] is False
    assert any("Metadata extraction" in blocker for blocker in diagnostics["blockers"])

    preview = preview_document_extraction(doc.id, db=db_session, _admin="admin")
    assert preview["proposed"]["title"] == "Demo_PR400000005_12/10/2020_205,25"
    assert "title" in preview["diff"]

    applied = apply_document_extraction_preview(doc.id, db=db_session, _admin="admin")
    assert applied.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert applied.metadata_sources_json["title"]["source"] == "deterministic"

    reindexed = reindex_document(doc.id, db=db_session, _admin="admin")
    assert reindexed.metadata_json["search_indexed"] is True


def test_completed_document_diagnostics_hide_inactive_task_internals(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "Done")
    doc.processing_state = DocumentState.complete
    doc.ocr_state = StageState.done
    doc.metadata_state = StageState.done
    doc.extracted_title = "Done"
    doc.metadata_json = {"search_indexed": True}
    doc.processing_attempt = 4
    doc.last_processing_heartbeat_at = datetime.now(timezone.utc)
    db_session.commit()

    diagnostics = document_diagnostics(doc.id, db=db_session, _admin="admin")

    assert diagnostics["complete"] is True
    assert diagnostics["task"]["active"] is False
    assert diagnostics["task"]["task_id"] is None
    assert diagnostics["task"]["attempt"] is None
    assert diagnostics["task"]["last_heartbeat_at"] is None
    assert diagnostics["task"]["total_attempts"] == 4
    assert diagnostics["task"]["last_heartbeat_recorded_at"] is not None


def test_reconcile_repairs_old_stack_incomplete_shapes(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[tuple[str, str]] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id: queued.append(("ocr", str(doc_id))))
    monkeypatch.setattr("app.services.reconciliation._enqueue_metadata", lambda doc_id, force=False: queued.append(("metadata", str(doc_id))))
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    missing_metadata = make_doc(db_session, tmp_path, text, sha="r" * 64)
    missing_metadata.ocr_text = text
    missing_metadata.ocr_state = StageState.done
    missing_metadata.processing_state = DocumentState.ocr_done
    missing_title = make_doc(db_session, tmp_path, text, sha="s" * 64)
    missing_title.ocr_text = text
    missing_title.ocr_state = StageState.done
    missing_title.metadata_state = StageState.done
    missing_title.processing_state = DocumentState.metadata_done
    complete_not_indexed = make_doc(db_session, tmp_path, text, sha="t" * 64)
    complete_not_indexed.ocr_text = text
    complete_not_indexed.extracted_title = "Demo_PR400000005_12/10/2020_205,25"
    complete_not_indexed.ocr_state = StageState.done
    complete_not_indexed.metadata_state = StageState.done
    complete_not_indexed.processing_state = DocumentState.complete
    complete_not_indexed.metadata_json = {}
    db_session.commit()

    result = reconcile_stuck_documents(db_session)
    db_session.refresh(complete_not_indexed)

    assert ("metadata", str(missing_metadata.id)) in queued
    assert ("metadata", str(missing_title.id)) in queued
    assert complete_not_indexed.metadata_json["search_indexed"] is True
    assert result["updated"] >= 2


def test_reconcile_queues_suspicious_metadata_quality_repair(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[tuple[str, str, bool]] = []
    monkeypatch.setattr("app.services.reconciliation._enqueue_ocr", lambda doc_id, task_id=None: queued.append(("ocr", str(doc_id), False)))
    monkeypatch.setattr("app.services.reconciliation._enqueue_metadata", lambda doc_id, force=False, task_id=None: queued.append(("metadata", str(doc_id), force)))
    text = """Telefonica Germany GmbH & Co. OHG
Rechnungsnummer
1318249263/08
Rechnungsdatum
28.07.2025
Rechnungsbetrag
26,49 €"""
    document = make_doc(db_session, tmp_path, text, sha="m" * 64)
    document.ocr_text = text
    document.ocr_state = StageState.done
    document.metadata_state = StageState.done
    document.processing_state = DocumentState.needs_review
    document.final_state = DocumentState.needs_review
    document.review_state = ReviewState.needs_review
    document.review_reason = "Qwen metadata brain returned invalid JSON"
    document.extracted_title = "Leistungszeitraum_1318249263/08_28/07/2025_2025,00"
    document.extracted_sender = "Leistungszeitraum"
    document.extracted_invoice_number = "1318249263/08"
    document.extracted_date = "28/07/2025"
    document.extracted_amount = "2025,00"
    document.metadata_json = {"qwen_refinement": {"ok": False, "error": "Qwen returned invalid metadata candidate JSON"}, "search_indexed": True}
    db_session.commit()

    result = reconcile_stuck_documents(db_session)
    db_session.refresh(document)

    assert ("metadata", str(document.id), True) in queued
    assert result["details"]["queued_metadata_repair"] == 1
    assert document.processing_state == DocumentState.ocr_done
    assert document.metadata_state == StageState.pending


def test_admin_storage_integrity_and_reindex(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    doc = make_doc(db_session, tmp_path, "Missing file", sha="u" * 64)
    Path(doc.storage_path).unlink()
    db_session.commit()

    report = storage_integrity(db=db_session)
    assert report["missing_files"][0]["document_id"] == str(doc.id)

    result = reindex_documents(db=db_session)
    db_session.refresh(doc)
    assert result.updated == 1
    assert doc.metadata_json["search_indexed"] is True
    config_module.get_settings.cache_clear()


def test_upload_validation_and_mocked_pdf_page_limit(monkeypatch) -> None:
    storage = LocalStorage()
    storage.validate_upload(SimpleNamespace(filename="invoice.pdf", content_type="application/pdf"))

    try:
        storage.validate_upload(SimpleNamespace(filename="script.exe", content_type="application/octet-stream"))
    except ValueError as exc:
        assert "extension" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("invalid extension was accepted")

    class FakePdf:
        def __init__(self, path: str) -> None:
            self.path = path

        def __len__(self) -> int:
            return 101

        def close(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=FakePdf))
    try:
        inspect_page_count("too-large.pdf", "application/pdf")
    except ValueError as exc:
        assert "max" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("oversized PDF page count was accepted")


def make_upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def test_upload_accepts_empty_optional_metadata_and_creates_one_document(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: str(tmp_path / "thumb.jpg"))
    monkeypatch.setattr("app.workers.tasks.ocr_document_task.delay", lambda document_id: None)

    result = asyncio.run(
        upload_batch(
            collection_name=None,
            label=None,
            document_metadata_json=json.dumps([{}]),
            processing_options_json=json.dumps({"auto_ocr": False}),
            record_metadata_json=None,
            files=[make_upload("scan.png", b"not really a png", "image/png")],
            db=db_session,
        )
    )

    assert result.collection_name == "Dokumente"
    assert len(result.documents) == 1
    doc = db_session.get(Document, result.documents[0].id)
    assert doc is not None
    assert doc.processing_state == DocumentState.uploaded
    assert doc.processing_options_json["auto_ocr"] is False


def test_large_upload_succeeds_and_upload_limits_are_clean_json_errors(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("MAX_UPLOAD_FILE_SIZE_MB", "2")
    monkeypatch.setenv("MAX_UPLOAD_BATCH_SIZE_MB", "3")
    monkeypatch.setenv("MAX_UPLOAD_FILES_PER_BATCH", "2")
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: None)
    large = b"x" * (1530234)
    result = asyncio.run(
        upload_batch(
            collection_name="Dokumente",
            label=None,
            document_metadata_json=None,
            processing_options_json=json.dumps({"auto_ocr": False}),
            record_metadata_json=None,
            files=[make_upload("large.pdf", large, "application/pdf")],
            db=db_session,
        )
    )
    assert len(result.documents) == 1

    with pytest_raises_http(413, "Max file size"):
        asyncio.run(
            upload_batch(
                collection_name="Dokumente",
                label=None,
                document_metadata_json=None,
                processing_options_json=json.dumps({"auto_ocr": False}),
                record_metadata_json=None,
                files=[make_upload("too-large.pdf", b"x" * (2 * 1024 * 1024 + 1), "application/pdf")],
                db=db_session,
            )
        )

    with pytest_raises_http(413, "Max files"):
        asyncio.run(
            upload_batch(
                collection_name="Dokumente",
                label=None,
                document_metadata_json=None,
                processing_options_json=json.dumps({"auto_ocr": False}),
                record_metadata_json=None,
                files=[
                    make_upload("one.pdf", b"one", "application/pdf"),
                    make_upload("two.pdf", b"two", "application/pdf"),
                    make_upload("three.pdf", b"three", "application/pdf"),
                ],
                db=db_session,
            )
        )
    config_module.get_settings.cache_clear()


def test_batch_size_failure_cleans_partial_files(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("MAX_UPLOAD_FILE_SIZE_MB", "2")
    monkeypatch.setenv("MAX_UPLOAD_BATCH_SIZE_MB", "1")
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: None)
    with pytest_raises_http(413, "Upload too large"):
        asyncio.run(
            upload_batch(
                collection_name="Dokumente",
                label=None,
                document_metadata_json=None,
                processing_options_json=json.dumps({"auto_ocr": False}),
                record_metadata_json=None,
                files=[
                    make_upload("one.pdf", b"x" * (700 * 1024), "application/pdf"),
                    make_upload("two.pdf", b"y" * (700 * 1024), "application/pdf"),
                ],
                db=db_session,
            )
        )
    assert list((tmp_path / "storage").rglob("*.*")) == []
    assert db_session.scalar(select(Document).where(Document.original_filename.in_(["one.pdf", "two.pdf"]))) is None
    config_module.get_settings.cache_clear()


def test_multifile_upload_applies_manual_metadata_per_document(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: None)
    metadata = [
        {"title": "Manual One", "sender": "Sender One"},
        {"title": "Manual Two", "sender": "Sender Two"},
    ]
    result = asyncio.run(
        upload_batch(
            collection_name="Eingangsrechnung",
            label="Two files",
            document_metadata_json=json.dumps(metadata),
            processing_options_json=json.dumps({"auto_ocr": False, "qwen_enabled": False}),
            record_metadata_json=None,
            files=[
                make_upload("one.jpg", b"one", "image/jpeg"),
                make_upload("two.jpg", b"two", "image/jpeg"),
            ],
            db=db_session,
        )
    )

    docs = db_session.scalars(select(Document).where(Document.batch_id == result.id).order_by(Document.original_filename)).all()
    assert len(docs) == 2
    assert {doc.manual_title_override for doc in docs} == {"Manual One", "Manual Two"}
    assert {doc.extracted_sender for doc in docs} == {"Sender One", "Sender Two"}
    assert all(doc.metadata_sources_json["title"]["source"] == "manual" for doc in docs)


def test_pdf_upload_records_page_count_without_requiring_metadata(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setattr("app.api.batches.inspect_page_count", lambda path, mime: 3)
    monkeypatch.setattr("app.api.batches.generate_thumbnail", lambda path, mime, document_id: str(tmp_path / "pdf-thumb.jpg"))

    result = asyncio.run(
        upload_batch(
            collection_name=None,
            label=None,
            document_metadata_json=None,
            processing_options_json=json.dumps({"auto_ocr": False}),
            record_metadata_json=None,
            files=[make_upload("invoice.pdf", b"%PDF fake", "application/pdf")],
            db=db_session,
        )
    )
    doc = db_session.get(Document, result.documents[0].id)
    assert doc is not None
    assert doc.page_count == 3
    assert doc.thumbnail_path.endswith("pdf-thumb.jpg")


def test_pdf_ocr_with_paddlevl_renders_pages_and_calls_provider(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    doc = make_doc(db_session, tmp_path, "%PDF", collection="Eingangsrechnung", sha="p" * 64)
    doc.mime_type = "application/pdf"
    doc.ocr_config_json = {"ocr_engine": "paddle_vl", "page_limit": 3, "ocr_concurrency": 1}
    queue_ocr(db_session, doc)
    db_session.commit()

    page1 = tmp_path / "page1.jpg"
    page2 = tmp_path / "page2.jpg"
    page1.write_text("one", encoding="utf-8")
    page2.write_text("two", encoding="utf-8")
    monkeypatch.setattr("app.services.processing.render_pdf_pages", lambda *args, **kwargs: [str(page1), str(page2)])

    calls: list[str] = []

    class PaddleOnlyProvider:
        def extract_text(self, file_path: str) -> OCRResult:
            calls.append(file_path)
            return OCRResult(text=f"paddlevl:{Path(file_path).stem}", raw_response={"provider": "paddle_vl", "file": file_path}, model_role="paddleocr_vl")

    run_ocr_for_document(db_session, doc.id, PaddleOnlyProvider(), enqueue_metadata=False)
    db_session.refresh(doc)
    assert calls == [str(page1), str(page2)]
    assert doc.ocr_text == "paddlevl:page1paddlevl:page2"
    assert doc.raw_ocr_json["source"] == "pdf_page_rendering"
    assert doc.raw_ocr_json["provider"] == "paddle_vl"
    assert doc.raw_ocr_json["page_ocr_concurrency"] == 1
    assert doc.model_trace_json["ocr"]["role"] == "paddleocr_vl"
    assert doc.page_count == 2
    assert [page.rendered_image_path for page in doc.pages] == [str(page1), str(page2)]


def test_paddlevl_pdf_page_ocr_uses_bounded_parallel_page_requests(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    doc = make_doc(db_session, tmp_path, "%PDF", collection="Eingangsrechnung", sha="s" * 64)
    doc.mime_type = "application/pdf"
    doc.ocr_config_json = {"ocr_engine": "paddle_vl", "page_limit": 8, "ocr_concurrency": 4}
    queue_ocr(db_session, doc)
    db_session.commit()

    pages = []
    for index in range(1, 7):
        page = tmp_path / f"page{index}.jpg"
        page.write_text(str(index), encoding="utf-8")
        pages.append(str(page))
    monkeypatch.setattr("app.services.processing.render_pdf_pages", lambda *args, **kwargs: pages)

    class PageProvider:
        def extract_text(self, file_path: str) -> OCRResult:
            # Return reversed completion speed by not depending on call order; the
            # production combiner must still preserve page order.
            return OCRResult(text=Path(file_path).stem, raw_response={"provider": "paddle_vl", "file": file_path}, model_role="paddleocr_vl")

    run_ocr_for_document(db_session, doc.id, PageProvider(), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.ocr_text == "page1page2page3page4page5page6"
    assert doc.raw_ocr_json["source"] == "pdf_page_rendering"
    assert doc.raw_ocr_json["provider"] == "paddle_vl"
    assert doc.raw_ocr_json["page_ocr_concurrency"] == 4
    assert [page.page_number for page in doc.pages] == [1, 2, 3, 4, 5, 6]
    assert [page.rendered_image_path for page in doc.pages] == pages


def test_paddlevl_task_budget_scales_with_large_pdf_page_count(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "%PDF", collection="Eingangsrechnung", sha="t" * 64)
    doc.mime_type = "application/pdf"
    doc.page_count = 80
    doc.ocr_config_json = {"ocr_engine": "paddle_vl", "page_limit": 80, "ocr_concurrency": 4}
    budget = estimate_ocr_task_budget(doc)

    assert budget["page_count"] == 80
    assert budget["budget_unit"] == "chunk"
    assert budget["soft_time_limit"] > 600
    assert budget["time_limit"] >= budget["soft_time_limit"] + 120

    assert reserve_processing_task(doc, task_id="book-task", stage="ocr", force=True)
    assert doc.processing_started_at is not None
    assert doc.processing_lease_until is not None
    assert (doc.processing_lease_until - doc.processing_started_at).total_seconds() >= budget["lease_seconds"] - 1


def test_publish_document_task_applies_dynamic_ocr_limits(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    from app.workers.tasks import ocr_document_task, publish_document_task

    captured: dict = {}

    def fake_apply_async(*, args, kwargs=None, task_id=None, queue=None, **options):
        captured.update({"args": args, "kwargs": kwargs, "task_id": task_id, "queue": queue, **options})
        return "queued"

    monkeypatch.setattr(ocr_document_task, "apply_async", fake_apply_async)
    doc = make_doc(db_session, tmp_path, "%PDF", collection="Eingangsrechnung", sha="u" * 64)
    doc.mime_type = "application/pdf"
    doc.page_count = 40
    doc.ocr_config_json = {"ocr_engine": "paddle_vl", "page_limit": 40, "ocr_concurrency": 4}
    reserve_processing_task(doc, task_id="queued-book", stage="ocr", force=True)
    db_session.commit()

    publish_document_task(db_session, doc.id, ocr_document_task, args=[str(doc.id)], task_id="queued-book", queue="ocr", stage="ocr")

    assert captured["task_id"] == "queued-book"
    assert captured["queue"] == "ocr"
    assert captured["soft_time_limit"] > 600
    assert captured["soft_time_limit"] < 3600
    assert captured["time_limit"] >= captured["soft_time_limit"] + 120


def test_manual_ocr_endpoint_enqueues_without_running_sync(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[str] = []
    monkeypatch.setattr("app.api.documents.ocr_document_task.delay", lambda document_id: queued.append(document_id))
    doc = make_doc(db_session, tmp_path, "Demo GmbH", sha="q" * 64)

    result = run_document_ocr(doc.id, db=db_session, _admin="admin")

    assert result.processing_state == DocumentState.queued_for_ocr
    assert queued == [str(doc.id)]
    stored = db_session.get(Document, doc.id)
    assert stored is not None
    assert stored.ocr_text is None


def test_manual_reextract_endpoint_enqueues_without_running_sync(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[tuple[str, bool]] = []
    monkeypatch.setattr("app.api.documents.extract_metadata_task.delay", lambda document_id, force=False: queued.append((document_id, force)))
    doc = make_doc(db_session, tmp_path, "Demo GmbH", sha="r" * 64)
    doc.ocr_text = "Demo GmbH\nRechnungsnummer PR400000005"
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.complete
    doc.metadata_state = StageState.done
    db_session.commit()

    result = reextract_document(doc.id, force=True, qwen_enabled=False, db=db_session, _admin="admin")

    assert result.processing_state == DocumentState.ocr_done
    assert queued == [(str(doc.id), True)]
    stored = db_session.get(Document, doc.id)
    assert stored is not None
    assert stored.extracted_title is None


def test_list_and_failed_endpoints_do_not_return_full_ocr_but_detail_does(db_session: Session, tmp_path: Path) -> None:
    full_text = "Needle " + ("A" * 2000)
    doc = make_doc(db_session, tmp_path, full_text, sha="z" * 64)
    doc.ocr_text = full_text
    doc.ocr_state = StageState.done
    doc.metadata_state = StageState.done
    doc.processing_state = DocumentState.failed
    doc.final_state = DocumentState.failed
    db_session.commit()

    listed = list_documents(db=db_session, _admin="admin")
    row = next(item for item in listed if item["id"] == str(doc.id))
    assert row["ocr_text"] is None
    assert row["ocr_snippet"].startswith("Needle")
    assert len(row["ocr_snippet"]) <= 500

    failed = failed_and_review(db=db_session)
    failed_row = next(item for item in failed["failed_documents"] if item["id"] == str(doc.id))
    assert failed_row["ocr_text"] is None
    assert failed_row["ocr_snippet"].startswith("Needle")

    detail = db_session.get(Document, doc.id)
    assert detail.ocr_text == full_text


class pytest_raises_http:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        assert isinstance(exc, HTTPException)
        assert exc.status_code == self.status_code
        assert self.text.lower() in str(exc.detail).lower()
        return True
