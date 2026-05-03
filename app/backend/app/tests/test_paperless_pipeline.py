from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Batch,
    Correspondent,
    Document,
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
from app.services.processing import queue_ocr, run_ocr_for_document
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
