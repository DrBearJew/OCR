from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Batch,
    Correspondent,
    Document,
    DocumentPage,
    DocumentState,
    DocumentType,
    HookKind,
    HookStage,
    IngestionSource,
    IngestionSourceType,
    OCRMode,
    ProcessingHook,
    RecordGrouping,
    StageState,
    StoragePathRule,
    Tag,
)
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.converters import ConverterError, ensure_convertible_allowed
from app.services.hooks import execute_hooks
from app.services.ingestion import scan_source
from app.services.ocr_glm import OCRResult
from app.services.model_setup import save_model_setup
from app.services.processing import queue_ocr, reserve_processing_task, run_ocr_for_document
from app.services.search import search_documents


class CountingProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def extract_text(self, file_path: str) -> OCRResult:
        self.calls += 1
        return OCRResult(text=self.text, raw_response={"ok": True})


class ExplodingProvider:
    def extract_text(self, file_path: str) -> OCRResult:
        raise AssertionError("provider should not be called")


def make_document(db: Session, tmp_path: Path, text: str = "needle") -> Document:
    collection = ensure_collection(db, "Dokumente")
    record = create_record_for_upload(db, collection, "Pipeline")
    batch = Batch(collection_name="Dokumente", document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / "doc.txt"
    path.write_text(text, encoding="utf-8")
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Dokumente",
        original_filename=path.name,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="7" * 64,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def write_searchable_pdf(path: Path, text: str | list[str]) -> None:
    texts = [text] if isinstance(text, str) else text
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(len(texts)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(texts)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, page_text in enumerate(texts):
        safe = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT\n/F1 18 Tf\n72 720 Td\n({safe}) Tj\nET\n".encode()
        objects.extend([
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + index * 2} 0 R >>".encode(),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        ])
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def make_pdf_document(db: Session, tmp_path: Path, text: str | list[str]) -> Document:
    collection = ensure_collection(db, "Dokumente")
    record = create_record_for_upload(db, collection, "PDF Pipeline")
    batch = Batch(collection_name="Dokumente", document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / "doc.pdf"
    write_searchable_pdf(path, text)
    doc = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Dokumente",
        original_filename=path.name,
        storage_path=str(path),
        mime_type="application/pdf",
        file_size=path.stat().st_size,
        sha256="8" * 64,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_ocr_skip_redo_force_modes(db_session: Session, tmp_path: Path) -> None:
    doc = make_document(db_session, tmp_path, "existing")
    doc.ocr_text = "existing OCR"
    doc.ocr_mode = OCRMode.skip
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, ExplodingProvider(), enqueue_metadata=False)
    db_session.refresh(doc)
    assert doc.ocr_text == "existing OCR"
    assert doc.processing_state == DocumentState.ocr_done

    provider = CountingProvider("redo OCR")
    queue_ocr(db_session, doc, force=True)
    db_session.commit()
    run_ocr_for_document(db_session, doc.id, provider, enqueue_metadata=False, ocr_mode="redo")
    db_session.refresh(doc)
    assert provider.calls == 1
    assert doc.ocr_text == "redo OCR"
    assert doc.prompt_trace_json["ocr_config"]["ocr_mode"] == "redo"

    doc.processing_state = DocumentState.complete
    db_session.commit()
    forced = CountingProvider("forced OCR")
    run_ocr_for_document(db_session, doc.id, forced, enqueue_metadata=False, force=True, ocr_mode="force")
    assert forced.calls == 1


def test_searchable_pdf_text_layer_is_used_before_model_ocr(db_session: Session, tmp_path: Path) -> None:
    text = "ACME GmbH Invoice No INV-2026-0619-01 Total Amount EUR 1123.45 Bill To Example AG"
    doc = make_pdf_document(db_session, tmp_path, text)
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, ExplodingProvider(), enqueue_metadata=False)
    db_session.refresh(doc)

    assert "INV-2026-0619-01" in doc.ocr_text
    assert "EUR 1123.45" in doc.ocr_text
    assert doc.raw_ocr_json["source"] == "pdf_text_layer"
    assert doc.model_trace_json["ocr_pipeline"]["source"] == "pdf_text_layer"
    assert doc.ocr_state == StageState.done


@pytest.mark.parametrize("missing_text", ["", "   ", "A " * 19])
def test_mixed_pdf_text_layer_falls_back_for_every_selected_page(db_session: Session, tmp_path: Path, missing_text: str) -> None:
    text = "Invoice ACME Amount EUR 1123.45 Bill To Example AG " * 3
    doc = make_pdf_document(db_session, tmp_path, [text, missing_text])
    queue_ocr(db_session, doc)
    db_session.commit()
    provider = CountingProvider("model OCR including scanned content")

    run_ocr_for_document(db_session, doc.id, provider, enqueue_metadata=False)
    db_session.refresh(doc)

    assert provider.calls == 2
    assert doc.raw_ocr_json["source"] == "pdf_page_rendering"
    assert doc.ocr_text == "\f".join([provider.text, provider.text])
    pages = db_session.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)).all()
    assert [page.ocr_text for page in pages] == [provider.text, provider.text]
    rejected = next(event for event in doc.events if event.event_type == "ocr_pdf_text_layer_rejected")
    assert rejected.event_metadata["pages_with_text"] == 1
    assert rejected.event_metadata["reason"] == "too_few_text_pages"


@pytest.mark.parametrize("page_limit", [1, 2])
def test_pdf_text_layer_preserves_selected_page_fragments_and_trace(db_session: Session, tmp_path: Path, page_limit: int) -> None:
    texts = ["Invoice ACME Amount EUR 1123.45 " * 3, "Second page Contract Example AG " * 3, ""]
    doc = make_pdf_document(db_session, tmp_path, texts)
    doc.ocr_config_json = {"page_limit": page_limit}
    queue_ocr(db_session, doc)
    db_session.commit()

    run_ocr_for_document(db_session, doc.id, ExplodingProvider(), enqueue_metadata=False)
    db_session.refresh(doc)

    assert doc.raw_ocr_json["validation"]["page_count"] == 3
    assert doc.raw_ocr_json["validation"]["checked_pages"] == page_limit
    pages = db_session.scalars(select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_number)).all()
    assert [page.page_number for page in pages] == list(range(1, page_limit + 1))
    assert [page.ocr_text for page in pages] == [text.strip() for text in texts[:page_limit]]
    assert doc.ocr_text == "\f".join(page.ocr_text for page in pages)
    assert doc.prompt_trace_json["ocr"] == {"name": "pdf_text_layer", "version": "1"}
    assert doc.prompt_trace_json["ocr_config"]["page_limit"] == page_limit
    assert doc.model_trace_json["ocr"]["model"] == "embedded_pdf_text"


@pytest.mark.parametrize("publish_fails", [False, True])
def test_pdf_text_layer_commits_before_metadata_publish(db_session: Session, tmp_path: Path, monkeypatch, publish_fails: bool) -> None:
    import app.workers.tasks as tasks

    doc = make_pdf_document(db_session, tmp_path, "Invoice ACME Amount EUR 1123.45 " * 3)
    queue_ocr(db_session, doc)
    reserve_processing_task(doc, task_id="ocr-owner", stage="ocr")
    db_session.commit()
    published = []
    committed_task_ids = []
    event.listen(db_session, "after_commit", lambda session: committed_task_ids.append(doc.processing_task_id))

    def fake_apply_async(*, args, kwargs, task_id, queue, **options):
        assert committed_task_ids == [task_id]
        # Read as the metadata consumer, not from the producer's identity map.
        with Session(db_session.get_bind()) as consumer:
            saved = consumer.get(Document, doc.id)
            assert saved.ocr_state == StageState.done
            assert saved.processing_state == DocumentState.ocr_done
            assert saved.raw_ocr_json["source"] == "pdf_text_layer"
            assert saved.current_stage == "metadata"
            assert saved.processing_task_id == task_id != "ocr-owner"
            assert consumer.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id)).ocr_text == saved.ocr_text
        assert args == [str(doc.id)]
        assert queue == "metadata"
        published.append(task_id)
        if publish_fails:
            raise RuntimeError("isolated broker failure")

    monkeypatch.setattr(tasks.extract_metadata_task, "apply_async", fake_apply_async)
    if publish_fails:
        with pytest.raises(RuntimeError, match="isolated broker failure"):
            run_ocr_for_document(db_session, doc.id, ExplodingProvider(), task_id="ocr-owner")
    else:
        run_ocr_for_document(db_session, doc.id, ExplodingProvider(), task_id="ocr-owner")
    db_session.refresh(doc)

    assert len(published) == 1
    assert doc.ocr_state == StageState.done
    assert doc.processing_state == DocumentState.ocr_done
    if publish_fails:
        assert doc.processing_task_id is None
        assert doc.processing_lease_until is None
        assert "Task publish failed for metadata" in doc.error_message
        assert any(event.event_type == "task_publish_failed" for event in doc.events)
    else:
        assert doc.processing_task_id == published[0]
        assert doc.current_stage == "metadata"


def test_disabled_pdf_text_layer_setting_runs_model_ocr(db_session: Session, tmp_path: Path) -> None:
    save_model_setup(db_session, {"ocr_pdf_text_layer_auto_enabled": False})
    doc = make_pdf_document(db_session, tmp_path, "Invoice ACME Amount EUR 1123.45 " * 3)
    queue_ocr(db_session, doc)
    db_session.commit()
    provider = CountingProvider("model OCR")

    run_ocr_for_document(db_session, doc.id, provider, enqueue_metadata=False)
    db_session.refresh(doc)

    assert provider.calls == 1
    assert doc.raw_ocr_json["source"] == "pdf_page_rendering"
    assert not any(event.event_type == "ocr_pdf_text_layer_used" for event in doc.events)


def test_short_pdf_text_layer_falls_back_to_provider(db_session: Session, tmp_path: Path) -> None:
    doc = make_pdf_document(db_session, tmp_path, "Hi")
    queue_ocr(db_session, doc)
    db_session.commit()
    provider = CountingProvider("fallback OCR")

    run_ocr_for_document(db_session, doc.id, provider, enqueue_metadata=False)
    db_session.refresh(doc)

    assert provider.calls == 1
    assert doc.ocr_text == "fallback OCR"
    assert doc.raw_ocr_json["source"] == "pdf_page_rendering"
    assert doc.raw_ocr_json["pages"][0]["raw_response"] == {"ok": True}


@pytest.mark.parametrize("force", [False, True])
def test_force_mode_ignores_searchable_pdf_text_layer(db_session: Session, tmp_path: Path, force: bool) -> None:
    doc = make_pdf_document(db_session, tmp_path, "ACME GmbH Invoice No INV-2026-0619-01 Total Amount EUR 1123.45 " * 3)
    queue_ocr(db_session, doc)
    db_session.commit()
    provider = CountingProvider("forced model OCR")

    run_ocr_for_document(db_session, doc.id, provider, enqueue_metadata=False, force=force, ocr_mode="force")
    db_session.refresh(doc)

    assert provider.calls == 1
    assert doc.ocr_text == "forced model OCR"
    assert doc.model_trace_json["ocr_pipeline"]["mode"] == "force"


def test_ingestion_polling_creates_one_document_and_skips_existing_hash(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    queued: list[str] = []
    import app.workers.tasks as tasks

    monkeypatch.setattr(tasks.ocr_document_task, "delay", lambda doc_id: queued.append(doc_id))
    collection = ensure_collection(db_session, "Belege")
    consume = tmp_path / "consume"
    consume.mkdir()
    file_path = consume / "receipt.txt"
    file_path.write_text("ACME\nDatum 04.04.2026", encoding="utf-8")
    source = IngestionSource(
        name="Local consume",
        source_type=IngestionSourceType.consume_folder,
        path=str(consume),
        collection_id=collection.id,
        record_grouping=RecordGrouping.one_record_per_file,
    )
    db_session.add(source)
    db_session.commit()

    first = scan_source(db_session, source)
    assert first["imported"] == 1
    assert len(queued) == 1
    assert db_session.query(Document).count() == 1
    assert db_session.query(Batch).count() == 1

    second = scan_source(db_session, source)
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert db_session.query(Document).count() == 1
    assert db_session.query(Batch).count() == 1


def test_hooks_record_success_events(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COMMAND_HOOKS_ENABLED", "true")
    import app.config as config_module

    config_module.get_settings.cache_clear()
    doc = make_document(db_session, tmp_path)
    hook = ProcessingHook(
        name="echo",
        stage=HookStage.post_consume,
        hook_kind=HookKind.command,
        command=f'"{sys.executable}" --version',
        blocking=True,
        timeout_seconds=10,
    )
    db_session.add(hook)
    db_session.commit()
    execute_hooks(db_session, HookStage.post_consume, document=doc, context={"test": True})
    db_session.commit()
    assert any(event.event_type == "post_consume_hook_done" for event in doc.events)
    config_module.get_settings.cache_clear()


def test_converter_boundary_rejects_office_when_disabled() -> None:
    with pytest.raises(ConverterError):
        ensure_convertible_allowed("invoice.docx", Settings(converters_enabled=False))
    ensure_convertible_allowed("invoice.docx", Settings(converters_enabled=True))


def test_search_filters_paperless_metadata(db_session: Session, tmp_path: Path) -> None:
    doc = make_document(db_session, tmp_path, "needle body")
    collection = doc.record.collection
    correspondent = Correspondent(collection_id=collection.id, name="ACME", slug="acme")
    document_type = DocumentType(collection_id=collection.id, name="Invoice", slug="invoice")
    tag = Tag(collection_id=collection.id, name="Tax", slug="tax")
    storage = StoragePathRule(collection_id=collection.id, name="Default", slug="default")
    db_session.add_all([correspondent, document_type, tag, storage])
    db_session.flush()
    doc.ocr_text = "needle body"
    doc.correspondent_id = correspondent.id
    doc.document_type_id = document_type.id
    doc.storage_path_id = storage.id
    doc.ocr_mode = OCRMode.redo
    doc.tags.append(tag)
    doc.processing_state = DocumentState.complete
    doc.ocr_state = StageState.done
    doc.metadata_state = StageState.done
    db_session.commit()

    assert search_documents(db_session, "needle", correspondent_id=str(correspondent.id))[0].document_id == doc.id
    assert search_documents(db_session, "needle", document_type_id=str(document_type.id))[0].document_id == doc.id
    assert search_documents(db_session, "needle", tag_id=str(tag.id))[0].document_id == doc.id
    assert search_documents(db_session, "needle", storage_path_id=str(storage.id), ocr_mode="redo")[0].document_id == doc.id
