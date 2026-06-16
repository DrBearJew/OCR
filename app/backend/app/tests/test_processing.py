from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.models import Batch, BatchStatus, Document, DocumentState, OCRMode, ReviewState, StageState
from app.services.llm_qwen import QwenRefinement
from app.services.prompt_loader import PromptLoader
from app.services.ocr_glm import OCRProviderError, OCRResult
from app.services.processing import determine_next_processing_state, queue_ocr, run_metadata_for_document, run_ocr_for_document, update_batch_status


class StaticProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self, file_path: str) -> OCRResult:
        return OCRResult(text=self.text, raw_response={"ok": True})


class FailingProvider:
    def extract_text(self, file_path: str) -> OCRResult:
        raise OCRProviderError("boom")


def make_doc(db: Session, tmp_path: Path, text: str, collection: str = "Eingangsrechnung", sha: str = "0" * 64) -> Document:
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


def test_complete_only_after_ocr_and_metadata(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, StaticProvider(text), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.ocr_done
    assert doc.ocr_state == StageState.done
    assert doc.processing_state != DocumentState.complete

    run_metadata_for_document(db_session, doc.id)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.complete
    assert doc.metadata_state == StageState.done
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"


def test_state_machine_requires_metadata_and_title(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "OCR text only")
    doc.ocr_text = "OCR text only"
    doc.ocr_state = StageState.done
    doc.metadata_state = StageState.pending
    doc.processing_state = DocumentState.ocr_done
    assert determine_next_processing_state(doc) == DocumentState.ocr_done

    doc.metadata_state = StageState.done
    doc.extracted_title = None
    assert determine_next_processing_state(doc) == DocumentState.metadata_done

    doc.extracted_title = "Final_Title"
    assert determine_next_processing_state(doc) == DocumentState.complete

    assert determine_next_processing_state(doc, ["invoice_number"]) == DocumentState.needs_review


def test_all_failed_batch_status_is_failed(db_session: Session, tmp_path: Path) -> None:
    first = make_doc(db_session, tmp_path, "one", sha="1" * 64)
    second = make_doc(db_session, tmp_path, "two", sha="2" * 64)
    second.batch_id = first.batch_id
    first.processing_state = DocumentState.failed
    first.final_state = DocumentState.failed
    second.processing_state = DocumentState.failed
    second.final_state = DocumentState.failed
    db_session.commit()

    status = update_batch_status(db_session, first.batch_id)
    assert status == BatchStatus.failed

    second.processing_state = DocumentState.complete
    second.final_state = DocumentState.complete
    db_session.commit()
    status = update_batch_status(db_session, first.batch_id)
    assert status == BatchStatus.partially_failed


def test_failed_ocr_is_retryable(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "bad")
    queue_ocr(db_session, doc)
    db_session.commit()
    with pytest.raises(OCRProviderError):
        run_ocr_for_document(db_session, doc.id, FailingProvider(), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.failed
    assert doc.error_message == "boom"

    queue_ocr(db_session, doc)
    db_session.commit()
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.queued_for_ocr
    assert doc.error_message is None


def test_multi_doc_batch_keeps_per_document_titles(db_session: Session, tmp_path: Path) -> None:
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
            collection_name="Eingangsrechnung",
            original_filename=filename,
            storage_path=str(path),
            mime_type="text/plain",
            file_size=len(text),
            sha256=filename.ljust(64, "0")[:64],
            ocr_text=text,
            ocr_state=StageState.done,
            processing_state=DocumentState.ocr_done,
            final_state=DocumentState.ocr_done,
        )
        db_session.add(doc)
        docs.append(doc)
    db_session.commit()

    for doc in docs:
        run_metadata_for_document(db_session, doc.id)
    titles = {db_session.get(Document, doc.id).extracted_title for doc in docs}  # type: ignore[union-attr]
    assert titles == {"Demo_PR400000005_12/10/2020_205,25", "Muster_M1675_29/10/2020_222,51"}


def test_manual_override_survives_locked_reprocessing(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    doc.ocr_text = text
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.ocr_done
    db_session.commit()
    run_metadata_for_document(db_session, doc.id)

    doc = db_session.get(Document, doc.id)
    assert doc is not None
    doc.extracted_title = "Manual_Title"
    doc.manual_title_override = "Shown_Title"
    doc.metadata_locked = True
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, force=False)
    db_session.refresh(doc)
    assert doc.extracted_title == "Manual_Title"
    assert doc.manual_title_override == "Shown_Title"

    run_metadata_for_document(db_session, doc.id, force=True)
    db_session.refresh(doc)
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"

    batch = db_session.get(Batch, doc.batch_id)
    assert batch is not None
    assert batch.status == BatchStatus.complete


def test_neutral_file_in_invoice_collection_completes_without_na_review(db_session: Session, tmp_path: Path) -> None:
    class MockQwen:
        def generate_metadata_candidates(self, payload: dict) -> QwenRefinement:
            prompt = PromptLoader().render("custom_field_prompt.tmpl", {"Content": payload["ocr_text"]})
            return QwenRefinement(
                raw_text=(
                    '{"sender":{"value":"Natürliche Aktivierung","confidence":0.9},'
                    '"invoice_number":{"value":"NA","confidence":0.5},'
                    '"created_date":{"value":"2026-06-15","confidence":0.8},'
                    '"amount":{"value":"42,00","confidence":0.8},'
                    '"summary":"Neutral health graphic","suggested_tags":["neutral"]}'
                ),
                raw_response={"ok": True},
                prompt=prompt,
                endpoint="http://qwen",
                model="qwen.gguf",
            )

    text = "Natürliche Aktivierung\nAktiviert körpereigene Prozesse\nohne Fremdstoffe."
    doc = make_doc(db_session, tmp_path, text, collection="Eingangsrechnung", sha="n" * 64)
    doc.ocr_text = text
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.ocr_done
    doc.review_state = ReviewState.needs_review
    doc.review_reason = "Fallback title or missing title segment used"
    doc.extracted_sender = "Old Sender"
    doc.extracted_date = "15/06/2026"
    doc.extracted_amount = "42,00"
    doc.metadata_sources_json = {
        "sender": {"source": "qwen", "confidence": 80},
        "date": {"source": "qwen", "confidence": 80},
        "amount": {"source": "qwen", "confidence": 80},
    }
    doc.metadata_json = {"review_warnings": ["Fallback title or missing title segment used"], "missing_required_fields": ["amount"]}
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_provider=MockQwen(), qwen_enabled=True, force=True)
    db_session.refresh(doc)

    assert doc.processing_state == DocumentState.complete
    assert doc.review_state == ReviewState.unreviewed
    assert doc.review_reason is None
    assert doc.extracted_title == "NaturlicheAktivierung"
    assert doc.extracted_sender is None
    assert doc.extracted_invoice_number is None
    assert doc.extracted_date is None
    assert doc.extracted_amount is None
    assert doc.llm_summary == "Neutral health graphic"
    assert doc.llm_suggested_tags == ["neutral"]
    assert doc.metadata_json["neutral_file"] is True
    assert doc.metadata_json["document_kind"] == "neutral"
    assert doc.metadata_json["qwen_refinement"]["neutral_core_fields_suppressed"] is True
    assert doc.metadata_json["qwen_candidates"]["sender"]["value"] is None
    assert "review_warnings" not in doc.metadata_json
    assert "missing_required_fields" not in doc.metadata_json

def test_qwen_autofill_fills_empty_fields_and_records_source(db_session: Session, tmp_path: Path) -> None:
    class MockQwen:
        def refine_metadata(self, payload: dict) -> QwenRefinement:
            prompt = PromptLoader().render("custom_field_prompt.tmpl", {"Content": payload["ocr_text"]})
            return QwenRefinement(
                raw_text='{"metadata":{"recipient":"Qwen Customer"},"confidence":{"recipient":0.87}}',
                raw_response={"ok": True},
                prompt=prompt,
                endpoint="http://qwen",
                model="qwen.gguf",
            )

    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    doc.ocr_text = text
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.ocr_done
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_provider=MockQwen(), qwen_enabled=True)
    db_session.refresh(doc)
    assert doc.extracted_recipient == "Qwen Customer"
    assert doc.metadata_sources_json["recipient"]["source"] == "qwen"
    assert doc.metadata_sources_json["recipient"]["confidence"] == 87


def test_qwen_preserves_manual_and_locked_fields_unless_overwrite_enabled(db_session: Session, tmp_path: Path) -> None:
    class MockQwen:
        def refine_metadata(self, payload: dict) -> QwenRefinement:
            prompt = PromptLoader().render("custom_field_prompt.tmpl", {"Content": payload["ocr_text"]})
            return QwenRefinement(
                raw_text='{"metadata":{"sender":"Qwen Sender"}}',
                raw_response={"ok": True},
                prompt=prompt,
                endpoint="http://qwen",
                model="qwen.gguf",
            )

    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    doc = make_doc(db_session, tmp_path, text)
    doc.ocr_text = text
    doc.ocr_state = StageState.done
    doc.processing_state = DocumentState.ocr_done
    doc.extracted_sender = "Manual Sender"
    doc.metadata_sources_json = {"sender": {"source": "manual", "confidence": 100}}
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_provider=MockQwen(), qwen_enabled=True)
    db_session.refresh(doc)
    assert doc.extracted_sender == "Manual Sender"

    doc.processing_state = DocumentState.ocr_done
    doc.metadata_state = StageState.pending
    db_session.commit()
    run_metadata_for_document(db_session, doc.id, qwen_provider=MockQwen(), qwen_enabled=True, overwrite_manual_values=True)
    db_session.refresh(doc)
    assert doc.extracted_sender == "Qwen Sender"
    assert doc.metadata_sources_json["sender"]["source"] == "qwen"


def test_skip_states_can_complete_without_hard_failure(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "", collection="Dokumente")
    doc.ocr_mode = OCRMode.skip
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, StaticProvider("should not run"), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.ocr_state == StageState.skipped
    assert doc.processing_state == DocumentState.ocr_done

    run_metadata_for_document(db_session, doc.id, skip_metadata=True)
    db_session.refresh(doc)
    assert doc.metadata_state == StageState.skipped
    assert doc.processing_state == DocumentState.complete
