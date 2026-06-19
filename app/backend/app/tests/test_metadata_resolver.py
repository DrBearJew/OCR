from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Batch, Document, StageState
from app.services.metadata_resolver import resolve_metadata_fields, review_warnings_for_resolution


def make_doc(db: Session, tmp_path: Path, text: str, collection: str = "Eingangsrechnung") -> Document:
    path = tmp_path / "resolver-test.txt"
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
        sha256="r" * 64,
        ocr_state=StageState.done,
        ocr_text=text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_qwen_grounded_candidates_win_over_weak_deterministic_and_regenerate_title(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "O2 invoice text")
    deterministic = {
        "title": "TelefnicaGermany_NA_17/06/2026_201055,00",
        "sender": "TelefnicaGermany",
        "recipient": None,
        "invoice_number": "NA",
        "date": "17/06/2026",
        "amount": "201055,00",
        "payment_method": None,
    }
    qwen = {
        "metadata": {
            "sender": "TelefonicaGermany",
            "invoice_number": "1318249263/08",
            "date": "2025-07-28",
            "amount": "26,49",
        },
        "confidence": {"sender": 95, "invoice_number": 95, "date": 95, "amount": 99},
        "evidence": {
            "sender": "TelefonicaGermany GmbH & Co. OHG RE 90345 Nürnberg",
            "invoice_number": "Rechnungsnummer 1318249263/08",
            "date": "Rechnungsdatum 28.07.2025",
            "amount": "Rechnungsbetrag 26,49 €",
        },
    }

    resolution = resolve_metadata_fields(doc, deterministic, qwen)
    warnings = review_warnings_for_resolution(doc, resolution.merged, resolution.sources, qwen, deterministic)

    assert resolution.merged["sender"] == "TelefonicaGermany"
    assert resolution.merged["invoice_number"] == "1318249263/08"
    assert resolution.merged["date"] == "28/07/2025"
    assert resolution.merged["amount"] == "26,49"
    assert resolution.merged["title"] == "TelefonicaGermany_1318249263/08_28/07/2025_26,49"
    assert resolution.sources["amount"]["source"] == "qwen"
    assert resolution.sources["title"]["source"] == "derived"
    assert resolution.as_metadata()["candidates"]["amount"][0]["authority"] == "weak_fallback"
    assert "Qwen disagrees with deterministic amount" not in warnings
    assert "Fallback title or missing title segment used" not in warnings




def test_missing_invoice_number_can_still_derive_non_fallback_title(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "O2 invoice without invoice number")
    deterministic = {
        "title": "TelefonicaGermany_NA_26/09/2025_26,49",
        "sender": "TelefonicaGermany",
        "recipient": None,
        "invoice_number": "NA",
        "date": "26/09/2025",
        "amount": "26,49",
        "payment_method": None,
    }
    qwen = {
        "metadata": {"sender": "TelefonicaGermany", "date": "2025-09-26", "amount": "26,49"},
        "confidence": {"sender": 95, "date": 90, "amount": 95},
        "evidence": {"sender": "Sender line", "date": "filename", "amount": "gross total"},
    }

    resolution = resolve_metadata_fields(doc, deterministic, qwen)
    warnings = review_warnings_for_resolution(doc, resolution.merged, resolution.sources, qwen, deterministic)

    assert resolution.merged["invoice_number"] is None
    assert resolution.merged["title"] == "TelefonicaGermany_26/09/2025_26,49"
    assert resolution.sources["title"]["source"] == "derived"
    assert "Fallback title or missing title segment used" not in warnings
    assert "Low confidence for title" not in warnings


def test_qwen_sender_legal_suffix_does_not_override_clean_deterministic(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "Muster invoice")
    deterministic = {
        "title": "Muster_M1675_29/10/2020_222,51",
        "sender": "Muster",
        "recipient": None,
        "invoice_number": "M1675",
        "date": "29/10/2020",
        "amount": "222,51",
        "payment_method": None,
    }
    qwen = {
        "metadata": {"sender": "Muster GmbH", "date": "29.10.2020"},
        "confidence": {"sender": 95, "date": 95},
        "evidence": {"sender": "Muster GmbH", "date": "Rechnungsdatum 29.10.2020"},
    }

    resolution = resolve_metadata_fields(doc, deterministic, qwen)
    warnings = review_warnings_for_resolution(doc, resolution.merged, resolution.sources, qwen, deterministic)

    assert resolution.merged["sender"] == "Muster"
    assert resolution.merged["date"] == "29/10/2020"
    assert resolution.merged["title"] == "Muster_M1675_29/10/2020_222,51"
    assert "Qwen disagrees with deterministic sender" not in warnings


def test_manual_source_still_wins_over_qwen(db_session: Session, tmp_path: Path) -> None:
    doc = make_doc(db_session, tmp_path, "Manual sender invoice")
    doc.extracted_sender = "Manual Sender"
    doc.metadata_sources_json = {"sender": {"source": "manual", "confidence": 100}}
    db_session.commit()
    deterministic = {
        "title": "Demo_PR400000005_12/10/2020_205,25",
        "sender": "Demo",
        "recipient": None,
        "invoice_number": "PR400000005",
        "date": "12/10/2020",
        "amount": "205,25",
        "payment_method": None,
    }
    qwen = {
        "metadata": {"sender": "Qwen Sender"},
        "confidence": {"sender": 99},
        "evidence": {"sender": "Qwen evidence"},
    }

    resolution = resolve_metadata_fields(doc, deterministic, qwen)

    assert resolution.merged["sender"] == "Manual Sender"
    assert resolution.sources["sender"]["source"] == "manual"
    assert resolution.decisions["sender"]["reason"] == "manual_value_protected"
