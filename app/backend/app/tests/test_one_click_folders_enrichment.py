from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Batch, Document, DocumentState, Record, ReviewState, StageState
from app.api.documents import process_document as process_document_endpoint
from app.api.records import process_record_documents
from app.services.collections import create_record_for_upload, ensure_collection
from app.services.folders import ensure_folder_path, purge_document_storage, restore_document, soft_delete_document
from app.services.llm_qwen import QwenRefinement
from app.services.processing import run_full_process_for_document
from app.services.prompt_loader import PromptLoader
from app.services.ocr_glm import OCRResult
from app.services.search import search_documents


class StaticOCR:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self, file_path: str) -> OCRResult:
        return OCRResult(text=self.text, raw_response={"provider": "test"})


class MockQwen:
    def __init__(self, raw_text: str | None = None) -> None:
        self.raw_text = raw_text or (
            '{"summary":"Invoice from Demo for technical parts.",'
            '"keywords":["demo","invoice","technical parts","205,25"],'
            '"entities":{"people":[],"organizations":["Demo"],"locations":[],"dates":["12/10/2020"],"amounts":["205,25"]},'
            '"document_purpose":"Supplier invoice for accounting and later search.",'
            '"suggested_tags":["invoice","supplier"],'
            '"suggested_folder":"Eingangsrechnung/Demo/2020",'
            '"related_search_queries":["Demo invoice PR400000005"],'
            '"uncertain_fields":[],"confidence":0.91}'
        )
        self.last_payload: dict | None = None
        self.calls = 0

    def generate_metadata_candidates(self, payload: dict) -> QwenRefinement:
        self.last_payload = payload
        self.calls += 1
        prompt = PromptLoader().render(
            "secondbrain_metadata_prompt.tmpl",
            {
                "Collection": payload["collection_name"],
                "Title": payload["title"],
                "DeterministicMetadata": payload["deterministic_metadata"],
                "SimilarDocuments": payload["similar_documents"],
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


def make_document(db: Session, tmp_path: Path, text: str, *, title: str = "doc.txt", processing_options: dict | None = None) -> Document:
    collection = ensure_collection(db, "Eingangsrechnung")
    record = create_record_for_upload(db, collection, "Record")
    batch = Batch(collection_name="Eingangsrechnung", document_count=1)
    db.add(batch)
    db.flush()
    path = tmp_path / title
    path.write_text(text, encoding="utf-8")
    document = Document(
        batch_id=batch.id,
        record_id=record.id,
        collection_name="Eingangsrechnung",
        original_filename=title,
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256=title.ljust(64, "0")[:64],
        processing_options_json={"qwen_enabled": False, "qwen_enrichment_enabled": True, **(processing_options or {})},
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def test_one_click_process_runs_ocr_metadata_qwen_title_without_auto_folder(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    document = make_document(db_session, tmp_path, text)
    qwen = MockQwen()

    run_full_process_for_document(db_session, document.id, ocr_provider=StaticOCR(text), qwen_provider=qwen)
    db_session.refresh(document)

    assert document.processing_state == DocumentState.complete
    assert document.ocr_state == StageState.done
    assert document.metadata_state == StageState.done
    assert document.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert document.llm_summary == "Invoice from Demo for technical parts."
    assert document.llm_keywords == ["demo", "invoice", "technical parts", "205,25"]
    assert document.llm_confidence == 91
    assert document.llm_suggested_folder == "Eingangsrechnung/Demo/2020"
    assert document.folder is None
    assert qwen.last_payload is not None
    assert qwen.last_payload["deterministic_metadata"]["invoice_number"] == "PR400000005"
    assert qwen.calls == 1


def test_one_click_process_assigns_folder_only_when_explicitly_enabled(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    document = make_document(db_session, tmp_path, text, title="auto-folder.txt", processing_options={"auto_folder_enabled": True, "use_qwen_folder_suggestion": True})

    run_full_process_for_document(db_session, document.id, ocr_provider=StaticOCR(text), qwen_provider=MockQwen())
    db_session.refresh(document)

    assert document.llm_suggested_folder == "Eingangsrechnung/Demo/2020"
    assert document.folder is not None
    assert document.folder.path == "Eingangsrechnung/Demo/2020"


def test_invalid_qwen_enrichment_preserves_deterministic_metadata(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    document = make_document(db_session, tmp_path, text, title="invalid-qwen.txt")

    run_full_process_for_document(db_session, document.id, ocr_provider=StaticOCR(text), qwen_provider=MockQwen("not json"))
    db_session.refresh(document)

    assert document.extracted_invoice_number == "PR400000005"
    assert document.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert document.review_state == ReviewState.unreviewed
    assert document.processing_state == DocumentState.complete
    assert document.llm_raw_response["metadata_brain"]["invalid"] is True



def test_empty_qwen_response_keeps_deterministic_completion(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    document = make_document(db_session, tmp_path, text, title="empty-qwen.txt")

    run_full_process_for_document(db_session, document.id, ocr_provider=StaticOCR(text), qwen_provider=MockQwen("   "))
    db_session.refresh(document)

    assert document.extracted_invoice_number == "PR400000005"
    assert document.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert document.review_state == ReviewState.unreviewed
    assert document.processing_state == DocumentState.complete
    assert document.llm_raw_response["metadata_brain"]["empty_response"] is True
    assert document.llm_raw_response["metadata_brain"]["invalid"] is False
    assert document.metadata_json["qwen_refinement"]["empty_response"] is True


def test_similar_document_context_is_passed_to_qwen(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    prior = make_document(db_session, tmp_path, text, title="prior.txt")
    prior.ocr_text = text
    prior.ocr_state = StageState.done
    prior.metadata_state = StageState.done
    prior.processing_state = DocumentState.complete
    prior.final_state = DocumentState.complete
    prior.extracted_title = "Demo_PR400000004_11/10/2020_120,00"
    prior.extracted_sender = "Demo"
    prior.llm_keywords = ["demo", "technical parts"]
    db_session.commit()
    document = make_document(db_session, tmp_path, text, title="current.txt")
    qwen = MockQwen()

    run_full_process_for_document(db_session, document.id, ocr_provider=StaticOCR(text), qwen_provider=qwen)

    assert qwen.last_payload is not None
    assert any(row["id"] == str(prior.id) for row in qwen.last_payload["similar_documents"])
    assert qwen.last_payload["deterministic_metadata"]["sender"] == "Demo"


def test_process_document_endpoint_persists_qwen_toggle_before_queue(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = make_document(db_session, tmp_path, "Demo GmbH", title="endpoint.txt")
    queued: list[tuple[str, bool]] = []
    monkeypatch.setattr("app.api.documents.process_document_task.delay", lambda document_id, force=False: queued.append((document_id, force)))

    result = process_document_endpoint(
        document.id,
        force=False,
        qwen_enabled=True,
        overwrite_manual_values=True,
        db=db_session,
        _admin="admin",
    )
    db_session.refresh(document)

    assert result.processing_options_json["qwen_enabled"] is True
    assert result.processing_options_json["qwen_enrichment_enabled"] is True
    assert result.processing_options_json["overwrite_manual_values"] is True
    assert queued == [(str(document.id), False)]
    assert document.processing_task_id
    assert document.current_stage == "process"

    second_result = process_document_endpoint(
        document.id,
        force=False,
        qwen_enabled=True,
        overwrite_manual_values=True,
        db=db_session,
        _admin="admin",
    )
    assert second_result.processing_task_id == document.processing_task_id
    assert queued == [(str(document.id), False)]


def test_process_all_enqueues_record_task_only_once_without_document_prequeue(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = make_document(db_session, tmp_path, "one", title="one.txt")
    second_path = tmp_path / "two.txt"
    second_path.write_text("two", encoding="utf-8")
    second = Document(
        batch_id=first.batch_id,
        record_id=first.record_id,
        collection_name=first.collection_name,
        original_filename="two.txt",
        storage_path=str(second_path),
        mime_type="text/plain",
        file_size=3,
        sha256="two".ljust(64, "2")[:64],
    )
    db_session.add(second)
    db_session.commit()

    queued_documents: list[tuple[str, bool]] = []
    monkeypatch.setattr("app.api.records.process_document_task.delay", lambda document_id, force=False: queued_documents.append((document_id, force)))

    result = process_record_documents(
        first.record_id,
        force=False,
        qwen_enabled=True,
        overwrite_manual_values=False,
        db=db_session,
    )
    db_session.refresh(first)
    db_session.refresh(second)

    assert result.queued == 2
    assert sorted(queued_documents) == sorted([(str(first.id), False), (str(second.id), False)])
    assert first.processing_state == DocumentState.queued_for_ocr
    assert second.processing_state == DocumentState.queued_for_ocr
    assert first.processing_options_json["qwen_enabled"] is True
    assert second.processing_options_json["qwen_enabled"] is True

    repeated = process_record_documents(
        first.record_id,
        force=False,
        qwen_enabled=True,
        overwrite_manual_values=False,
        db=db_session,
    )
    assert repeated.queued == 0
    assert repeated.skipped == 2
    assert sorted(queued_documents) == sorted([(str(first.id), False), (str(second.id), False)])


def test_process_publish_failure_releases_document_lease(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = make_document(db_session, tmp_path, "Demo GmbH", title="publish-fail.txt")

    def fail_publish(document_id: str, force: bool = False) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("app.api.documents.process_document_task.delay", fail_publish)

    try:
        process_document_endpoint(
            document.id,
            force=False,
            qwen_enabled=True,
            overwrite_manual_values=False,
            db=db_session,
            _admin="admin",
        )
    except RuntimeError as exc:
        assert "redis unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("publish failure should surface to caller")

    db_session.refresh(document)
    assert document.processing_state == DocumentState.queued_for_ocr
    assert document.processing_task_id is None
    assert document.processing_lease_until is None
    assert "Task publish failed" in (document.error_message or "")


def test_process_endpoint_publishes_with_reserved_task_id_when_delay_is_not_patched(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = make_document(db_session, tmp_path, "Demo GmbH", title="task-id.txt")
    published: dict[str, object] = {}

    def fake_apply_async(*, args, kwargs=None, task_id=None, queue=None, **options):
        published.update({"args": args, "kwargs": kwargs, "task_id": task_id, "queue": queue, **options})

    monkeypatch.setattr("app.api.documents.process_document_task.apply_async", fake_apply_async)

    process_document_endpoint(
        document.id,
        force=False,
        qwen_enabled=True,
        overwrite_manual_values=False,
        db=db_session,
        _admin="admin",
    )
    db_session.refresh(document)

    assert published["args"] == [str(document.id)]
    assert published["queue"] == "ocr"
    assert published["task_id"] == document.processing_task_id
    assert document.current_stage == "process"


def test_soft_delete_restore_and_search_exclusion(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH AlphaNeedle\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    document = make_document(db_session, tmp_path, text, title="delete.txt")
    document.ocr_text = text
    document.ocr_state = StageState.done
    document.metadata_state = StageState.done
    document.processing_state = DocumentState.complete
    document.final_state = DocumentState.complete
    db_session.commit()
    assert search_documents(db_session, "AlphaNeedle")

    soft_delete_document(db_session, document)
    db_session.commit()
    assert search_documents(db_session, "AlphaNeedle") == []

    restore_document(db_session, document)
    db_session.commit()
    assert search_documents(db_session, "AlphaNeedle")


def test_nested_folder_path_and_purge_removes_files(db_session: Session, tmp_path: Path) -> None:
    text = "purge me"
    document = make_document(db_session, tmp_path, text, title="purge.txt")
    folder = ensure_folder_path(db_session, "Ausgangsrechnung/2024/10")
    document.folder_id = folder.id
    db_session.commit()
    assert folder.path == "Ausgangsrechnung/2024/10"
    assert Path(document.storage_path).exists()

    purge_document_storage(document)
    assert not Path(document.storage_path).exists()
