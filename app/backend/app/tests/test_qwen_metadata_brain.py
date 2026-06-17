from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import Batch, CustomFieldDefinition, CustomFieldType, Document, DocumentState, FieldValueSource, ReviewState, StageState
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.llm_qwen import QwenProviderError, QwenRefinement, parse_json_suggestion
from app.services.processing import run_metadata_for_document
from app.services.prompt_loader import PromptLoader


def test_qwen_json_parser_repairs_extra_evidence_strings() -> None:
    parsed = parse_json_suggestion(
        '{"entities":{"organizations":[{"value":"O2","confidence":0.99,"evidence":"O2 Team", "O2 Mobile Unlimited Smart", "O2"}]}}'
    )

    assert parsed["entities"]["organizations"][0]["evidence"] == "O2 Team; O2 Mobile Unlimited Smart; O2"


def test_qwen_json_parser_keeps_first_object_with_extra_closing_brace() -> None:
    parsed = parse_json_suggestion(
        """{
          "sender": {"value": "Telefonica Germany GmbH & Co. OHG", "confidence": 0.95, "evidence": "Sender address"},
          "created_date": {"value": "2025-07-28", "confidence": 0.99, "evidence": "Rechnungsdatum"},
          "invoice_number": {"value": "1318249263/08", "confidence": 0.99, "evidence": "Rechnungsnummer"},
          "amount": {"value": "26,49", "confidence": 0.99, "evidence": "Rechnungsbetrag"},
          "entities": {"amounts": [{"value": "26,49", "confidence": 0.99}]}
        },
        "document_purpose": "extra data after an accidental root close"
        }"""
    )

    assert parsed["sender"]["value"] == "Telefonica Germany GmbH & Co. OHG"
    assert parsed["amount"]["value"] == "26,49"


class CandidateQwen:
    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text
        self.last_payload: dict[str, Any] | None = None

    def generate_metadata_candidates(self, payload: dict[str, Any]) -> QwenRefinement:
        self.last_payload = payload
        prompt = PromptLoader().render(
            "secondbrain_metadata_prompt.tmpl",
            {
                "Collection": payload["collection_name"],
                "Title": payload["title"],
                "CollectionSchema": "{}",
                "TitleRule": "{}",
                "CustomFields": "[]",
                "DeterministicMetadata": "{}",
                "ManualLockedFields": "{}",
                "SimilarDocuments": "[]",
                "ProcessingOptions": "{}",
                "OcrText": payload["ocr_text"],
            },
        )
        return QwenRefinement(
            raw_text=self.raw_text,
            raw_response={"ok": True},
            prompt=prompt,
            endpoint="http://qwen",
            model="qwen.gguf",
        )


def make_record_document(db: Session, tmp_path: Path, text: str, collection_name: str = "Dokumente") -> Document:
    collection = ensure_collection(db, collection_name)
    record = create_record_for_upload(db, collection, "Qwen test")
    path = tmp_path / f"{collection_name}.txt"
    path.write_text(text, encoding="utf-8")
    batch = Batch(collection_name=collection_name, document_count=1)
    db.add(batch)
    db.flush()
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name=collection_name,
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="q" * 64,
        processing_state=DocumentState.ocr_done,
        final_state=DocumentState.ocr_done,
        ocr_state=StageState.done,
        ocr_text=text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_qwen_fills_real_metadata_fields_sources_evidence_and_custom_fields(db_session: Session, tmp_path: Path) -> None:
    collection = ensure_collection(db_session, "Dokumente")
    field = CustomFieldDefinition(
        collection_id=collection.id,
        name="Project",
        slug="project",
        field_type=CustomFieldType.string,
        searchable=True,
    )
    db_session.add(field)
    db_session.commit()
    doc = make_record_document(db_session, tmp_path, "OCR has ambiguous mail from Alpha to Beta about Project Atlas.")
    doc.record.collection_id = collection.id
    db_session.commit()

    qwen = CandidateQwen(
        """
        {
          "sender": {"value":"Alpha GmbH","confidence":0.91,"evidence":"Alpha letterhead"},
          "recipient": {"value":"Beta KG","confidence":0.89,"evidence":"address block"},
          "document_type": {"value":"Brief","confidence":0.8,"evidence":"mail format"},
          "created_date": {"value":"2024-10-13","confidence":0.7,"evidence":"dated line"},
          "custom_fields": {"project": {"value":"Atlas","confidence":0.86,"evidence":"Project Atlas"}},
          "suggested_tags": ["atlas", "mail"],
          "suggested_folder": "Dokumente/Alpha/2024",
          "search_keywords": ["Alpha Beta Atlas"],
          "summary": "Letter about Project Atlas.",
          "related_search_queries": ["Alpha Atlas documents"],
          "uncertain_fields": []
        }
        """
    )

    run_metadata_for_document(db_session, doc.id, qwen_provider=qwen, qwen_enabled=True)
    db_session.refresh(doc)

    assert doc.extracted_sender == "Alpha GmbH"
    assert doc.extracted_recipient == "Beta KG"
    assert doc.extracted_date == "13/10/2024"
    assert doc.metadata_json["document_type"] == "Brief"
    assert doc.metadata_sources_json["sender"]["source"] == "qwen"
    assert doc.metadata_sources_json["sender"]["confidence"] == 91
    assert doc.metadata_sources_json["sender"]["evidence"] == "Alpha letterhead"
    assert doc.llm_summary == "Letter about Project Atlas."
    assert doc.llm_keywords == ["Alpha Beta Atlas"]
    assert doc.llm_suggested_tags == ["atlas", "mail"]
    assert doc.llm_suggested_folder == "Dokumente/Alpha/2024"
    saved = doc.custom_field_values[0]
    assert saved.normalized_value == "Atlas"
    assert saved.source == FieldValueSource.qwen
    assert qwen.last_payload is not None
    assert qwen.last_payload["custom_fields"][0]["slug"] == "project"


def test_qwen_payload_truncates_long_ocr_text_before_prompt(db_session: Session, tmp_path: Path) -> None:
    long_text = "Header important sender\n" + ("middle filler " * 2000) + "\nTail important amount 42,00"
    doc = make_record_document(db_session, tmp_path, long_text, "Eingangsrechnung")
    qwen = CandidateQwen("{}")

    run_metadata_for_document(db_session, doc.id, qwen_provider=qwen, qwen_enabled=True)

    assert qwen.last_payload is not None
    prompt_text = qwen.last_payload["ocr_text"]
    assert len(prompt_text) < len(long_text)
    assert "OCR text truncated for Qwen metadata prompt" in prompt_text
    assert prompt_text.startswith("Header important sender")
    assert prompt_text.endswith("Tail important amount 42,00")


def test_qwen_preserves_manual_locked_values_and_records_invalid_json(db_session: Session, tmp_path: Path) -> None:
    doc = make_record_document(db_session, tmp_path, "Demo GmbH\nRechnungsnummer PR400000005\nEndsumme 205,25", "Eingangsrechnung")
    doc.extracted_sender = "Manual Sender"
    doc.metadata_sources_json = {"sender": {"source": "manual", "confidence": 100}}
    doc.field_locks_json = {"sender": True}
    db_session.commit()

    qwen = CandidateQwen('{"sender":{"value":"Qwen Sender","confidence":0.99,"evidence":"header"}}')
    run_metadata_for_document(db_session, doc.id, qwen_provider=qwen, qwen_enabled=True)
    db_session.refresh(doc)
    assert doc.extracted_sender == "Manual Sender"
    assert doc.metadata_sources_json["sender"]["source"] == "manual"

    doc.processing_state = DocumentState.ocr_done
    doc.metadata_state = StageState.pending
    db_session.commit()
    run_metadata_for_document(db_session, doc.id, qwen_provider=CandidateQwen("not json"), qwen_enabled=True)
    db_session.refresh(doc)
    assert doc.extracted_invoice_number == "PR400000005"
    assert doc.metadata_json["qwen_candidates"] == {}


def test_invalid_qwen_json_does_not_force_review_when_metadata_is_valid(db_session: Session, tmp_path: Path) -> None:
    text = """Demo GmbH
Rechnungsnummer PR400000005
Rechnungsdatum 12.10.2020
Endsumme 205,25"""
    doc = make_record_document(db_session, tmp_path, text, "Eingangsrechnung")

    run_metadata_for_document(db_session, doc.id, qwen_provider=CandidateQwen("not json"), qwen_enabled=True)
    db_session.refresh(doc)

    assert doc.processing_state == DocumentState.complete
    assert doc.review_state != ReviewState.needs_review
    assert doc.metadata_json["qwen_candidates"] == {}
    assert doc.metadata_json["qwen_refinement"]["error"] == "Qwen returned invalid metadata candidate JSON"


def test_metadata_rerun_recovers_stored_qwen_response_when_live_qwen_fails(db_session: Session, tmp_path: Path) -> None:
    class FailingQwen:
        def generate_metadata_candidates(self, payload: dict[str, Any]) -> QwenRefinement:
            raise QwenProviderError("live qwen down")

    text = """Telefonica Germany GmbH & Co. OHG
Rechnungsnummer
1318249263/08
Rechnungsdatum
28.07.2025
Rechnungsbetrag
26,49 €"""
    doc = make_record_document(db_session, tmp_path, text, "Eingangsrechnung")
    doc.qwen_response_text = """{
      "sender": {"value": "Telefonica Germany GmbH & Co. OHG", "confidence": 0.95, "evidence": "Sender address"},
      "created_date": {"value": "2025-07-28", "confidence": 0.99, "evidence": "Rechnungsdatum"},
      "invoice_number": {"value": "1318249263/08", "confidence": 0.99, "evidence": "Rechnungsnummer"},
      "amount": {"value": "26,49", "confidence": 0.99, "evidence": "Rechnungsbetrag"},
      "entities": {"amounts": [{"value": "26,49", "confidence": 0.99}]}
    },
    "document_purpose": "extra trailing model data"
    }"""
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_provider=FailingQwen(), qwen_enabled=True, force=True)
    db_session.refresh(doc)

    assert doc.processing_state == DocumentState.complete
    assert doc.metadata_json["qwen_refinement"]["recovered_from_stored_raw"] is True
    assert doc.extracted_amount == "26,49"
    assert doc.extracted_invoice_number == "1318249263/08"


def test_qwen_suggested_title_base_only_replaces_weak_base(db_session: Session, tmp_path: Path) -> None:
    doc = make_record_document(db_session, tmp_path, "Rechnung Nr. 2400\nRechnungsdatum 15.07.2019\nGesamtbetrag 2539,46", "Ausgangsrechnung")
    qwen = CandidateQwen(
        '{"suggested_title_base":{"value":"MusterkundeCo","confidence":0.94,"evidence":"customer block"}}'
    )

    run_metadata_for_document(db_session, doc.id, qwen_provider=qwen, qwen_enabled=True)
    db_session.refresh(doc)

    assert doc.extracted_title == "MusterkundeCo_2400_15/07/2019_2539,46"
    assert doc.metadata_json["qwen_candidates"]["suggested_title_base"]["value"] == "MusterkundeCo"
