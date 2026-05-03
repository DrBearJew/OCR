from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Batch, Document, DocumentState, StageState
from app.services.search import search_documents


def test_ocr_full_text_search_finds_expected_documents(db_session: Session, tmp_path: Path) -> None:
    batch = Batch(collection_name="Eingangsrechnung", document_count=1)
    db_session.add(batch)
    db_session.flush()
    path = tmp_path / "demo.txt"
    path.write_text("demo", encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        collection_name="Eingangsrechnung",
        original_filename="demo.txt",
        storage_path=str(path),
        mime_type="text/plain",
        file_size=4,
        sha256="1" * 64,
        processing_state=DocumentState.complete,
        ocr_state=StageState.done,
        metadata_state=StageState.done,
        final_state=DocumentState.complete,
        ocr_text="This invoice contains a rare search token AlphaNeedle.",
        extracted_title="Demo_PR400000005_12/10/2020_205,25",
    )
    db_session.add(doc)
    db_session.commit()

    results = search_documents(db_session, "AlphaNeedle")
    assert len(results) == 1
    assert results[0].document_id == doc.id
    assert "AlphaNeedle" in results[0].snippet

