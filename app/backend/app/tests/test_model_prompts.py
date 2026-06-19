from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Batch, Document, DocumentState, StageState
from app.services.extraction import ExtractionInput, extract_belege_title
from app.services.integrations import collect_integrations
from app.services.llm_qwen import QWEN_METADATA_MAX_TOKENS, QwenLlamaCppProvider, QwenProviderError, QwenRefinement, qwen_metadata_max_tokens_for_payload
from app.services.ocr_glm import GLMLlamaCppOCRProvider, OCRProviderError, PaddleVLLlamaCppOCRProvider, PPOCRv6Provider, _compact_repeated_ocr_lines, _format_diagram_ocr_markdown_if_needed, build_ocr_provider
from app.services.processing import run_metadata_for_document
from app.services.prompt_loader import PromptLoader
from app.services.rules import get_collection_rules, get_ocr_rules, validate_title_for_collection


REQUIRED_PROMPTS = {
    "adhoc-analysis_prompt.tmpl",
    "correspondent_prompt.tmpl",
    "created_date_prompt.tmpl",
    "custom_field_prompt.tmpl",
    "document_type_prompt.tmpl",
    "ocr_prompt.tmpl",
    "secondbrain_metadata_prompt.tmpl",
}


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeModelResponse(FakeResponse):
    pass


def test_prompt_loader_loads_required_templates_and_renders_variables() -> None:
    loader = PromptLoader()
    for name in REQUIRED_PROMPTS:
        rendered = loader.render(name, {"Language": "German", "Today": "2026-04-28"})
        assert rendered.name == name
        assert rendered.version
        assert "{{.Language}}" not in rendered.text
    custom = loader.render("created_date_prompt.tmpl", {"Language": "German", "Today": "2026-04-28", "Content": "Hallo"})
    assert "German" in custom.text
    assert "2026-04-28" in custom.text


def test_ocr_prompt_includes_diagram_guardrails() -> None:
    rendered = PromptLoader().render("ocr_prompt.tmpl")
    assert "Return Markdown only" in rendered.text
    assert "For diagrams or slides" in rendered.text
    assert "Do not repeat labels" in rendered.text


def test_rules_yaml_is_loaded_and_used_for_title_validation() -> None:
    assert "Belege" in get_collection_rules()["collections"]
    assert "sauglinge" in get_ocr_rules()["belege_bad_sender_substrings"]
    result = extract_belege_title(ExtractionInput("Belege", "Sauglingeund\nWORLD HEALTH ORGANIZATION"))
    assert result.title.startswith("Dok_B_")
    assert validate_title_for_collection("Belege", "Dok_B_04/26_NA_NA")


def test_glm_ocr_adapter_uses_prompt_and_mocked_llama_response(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": "OCR text from GLM"}}]})

    monkeypatch.setattr("app.services.ocr_glm.httpx.post", fake_post)
    path = tmp_path / "scan.png"
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(path)
    settings = Settings(
        ocr_provider="glm",
        glm_llamacpp_base_url="http://glm-llama:8080",
        glm_model_path="/llm-models/glm.gguf",
        llm_request_timeout_seconds=7,
    )
    result = GLMLlamaCppOCRProvider(settings).extract_text(str(path))
    assert result.text == "OCR text from GLM"
    assert result.prompt_name == "ocr_prompt.tmpl"
    assert result.model_role == "glm_ocr"
    assert captured["url"] == "http://glm-llama:8080/v1/chat/completions"
    assert captured["json"]["model"] == "glm.gguf"
    assert captured["timeout"] == 7


def test_paddle_vl_adapter_uses_prompt_and_mocked_llama_response(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": "OCR text from PaddleOCR-VL"}}]})

    monkeypatch.setattr("app.services.ocr_glm.httpx.post", fake_post)
    path = tmp_path / "scan.png"
    from PIL import Image

    Image.new("RGB", (8, 8), "white").save(path)
    settings = Settings(
        ocr_provider="paddle_vl",
        paddle_vl_llamacpp_base_url="http://smart-proxy:8081/v1",
        paddle_vl_model_path="paddleocr-vl",
        paddle_vl_mmproj_path="/llm-models/paddleocr-vl-mmproj.gguf",
        llm_request_timeout_seconds=11,
    )
    result = PaddleVLLlamaCppOCRProvider(settings).extract_text(str(path))
    assert result.text == "OCR text from PaddleOCR-VL"
    assert result.prompt_name == "ocr_prompt.tmpl"
    assert result.model_role == "paddleocr_vl"
    assert captured["url"] == "http://smart-proxy:8081/v1/chat/completions"
    assert captured["json"]["model"] == "paddleocr-vl"
    assert captured["json"]["temperature"] == 0.0
    assert captured["json"]["max_tokens"] == 2048
    assert captured["json"]["repeat_penalty"] == 1.18
    assert captured["json"]["repeat_last_n"] == 512
    assert captured["timeout"] == 11


def test_ocr_provider_can_be_overridden_per_document_engine() -> None:
    settings = Settings(ocr_provider="paddle_vl")
    assert isinstance(build_ocr_provider(settings, provider_name="paddle_vl"), PaddleVLLlamaCppOCRProvider)
    assert isinstance(build_ocr_provider(settings, provider_name="ppocrv6"), PPOCRv6Provider)


def test_glm_ocr_config_reports_model_mismatch_and_missing_mmproj(monkeypatch, tmp_path: Path) -> None:
    def fake_get(url: str, timeout: float) -> FakeResponse:
        return FakeResponse({"data": [{"id": "glm"}]})

    monkeypatch.setattr("app.services.ocr_glm.httpx.get", fake_get)
    path = tmp_path / "scan.txt"
    path.write_text("image-ish", encoding="utf-8")

    missing_mmproj = Settings(
        ocr_provider="glm",
        glm_llamacpp_base_url="http://smart-proxy:8081/v1",
        glm_model_path="glm",
        glm_mmproj_path="",
    )
    try:
        GLMLlamaCppOCRProvider(missing_mmproj).extract_text(str(path))
    except OCRProviderError as exc:
        assert "GLM_MMPROJ_PATH is empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("missing mmproj should fail before OCR request")

    mismatched_model = Settings(
        ocr_provider="glm",
        glm_llamacpp_base_url="http://smart-proxy:8081/v1",
        glm_model_path="glm-ocr",
        glm_mmproj_path="/root/llm-models/glm-mmproj.gguf",
    )
    try:
        GLMLlamaCppOCRProvider(mismatched_model).extract_text(str(path))
    except OCRProviderError as exc:
        assert "configured model 'glm-ocr'" in str(exc)
        assert "glm" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("model alias mismatch should fail before OCR request")


def test_qwen_refinement_adapter_is_mockable(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": "[{\"field\":\"amount\",\"value\":\"EUR205.25\"}]"}}]})

    monkeypatch.setattr("app.services.llm_qwen.httpx.post", fake_post)
    settings = Settings(
        qwen_llamacpp_base_url="http://qwen-llama:8080",
        qwen_model_path="/llm-models/qwen.gguf",
        llm_request_timeout_seconds=9,
        llm_metadata_refinement_enabled=True,
    )
    result = QwenLlamaCppProvider(settings).refine_metadata(
        {
            "collection_name": "Eingangsrechnung",
            "ocr_text": "Demo Rechnung",
            "title": "Demo_PR400000005_12/10/2020_205,25",
            "created_date": "2020-10-12",
        }
    )
    assert result.model == "qwen.gguf"
    assert result.prompt.name == "custom_field_prompt.tmpl"
    assert "EUR205.25" in result.raw_text
    assert captured["url"] == "http://qwen-llama:8080/v1/chat/completions"
    assert captured["json"]["model"] == "qwen.gguf"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert "<|think_off|>" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["messages"][1]["role"] == "user"


def test_qwen_metadata_candidate_adapter_requests_json_mode(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": "{\"summary\":\"ok\"}"}}]})

    monkeypatch.setattr("app.services.llm_qwen.httpx.post", fake_post)
    settings = Settings(
        qwen_llamacpp_base_url="http://qwen-llama:8080",
        qwen_model_path="/llm-models/qwen.gguf",
        llm_request_timeout_seconds=9,
        llm_metadata_refinement_enabled=True,
    )
    result = QwenLlamaCppProvider(settings).generate_metadata_candidates(
        {
            "collection_name": "Eingangsrechnung",
            "ocr_text": "Demo Rechnung",
            "title": "Demo",
        }
    )

    assert result.raw_text == '{"summary":"ok"}'
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["max_tokens"] == 2048
    assert "<|think_off|>" not in captured["json"]["messages"][0]["content"]
    assert "private reasoning channel" in captured["json"]["messages"][0]["content"]


def test_qwen_metadata_candidate_budget_scales_with_custom_fields_and_ocr_length() -> None:
    assert QWEN_METADATA_MAX_TOKENS == 4096
    assert qwen_metadata_max_tokens_for_payload({"custom_fields": []}, settings_max_tokens=4096) == 2048
    assert qwen_metadata_max_tokens_for_payload({"custom_fields": [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]}, settings_max_tokens=4096) == 2336
    assert qwen_metadata_max_tokens_for_payload({"ocr_text": "x" * 4000}, settings_max_tokens=4096) == 2048
    assert qwen_metadata_max_tokens_for_payload({"ocr_text": "x" * 4001}, settings_max_tokens=4096) == 2560
    assert qwen_metadata_max_tokens_for_payload({"ocr_text": "x" * 12000}, settings_max_tokens=4096) == 3072
    assert qwen_metadata_max_tokens_for_payload({"custom_fields": [{"slug": str(i)} for i in range(100)], "ocr_text": "x" * 12000}, settings_max_tokens=4096) == 4096
    assert qwen_metadata_max_tokens_for_payload({"custom_fields": [{"slug": str(i)} for i in range(100)], "ocr_text": "x" * 12000}, settings_max_tokens=2048) == 2048


def test_qwen_json_mode_fallback_failure_is_provider_error() -> None:
    settings = Settings(
        qwen_llamacpp_base_url="http://qwen-llama:8080",
        qwen_model_path="/llm-models/qwen.gguf",
        llm_request_timeout_seconds=9,
        llm_metadata_refinement_enabled=True,
    )
    provider = QwenLlamaCppProvider(settings)
    calls: list[dict[str, Any]] = []

    def fake_post_chat(url: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append(body)
        request = httpx.Request("POST", url)
        response = httpx.Response(400, request=request, text="bad request")
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    provider._post_chat = fake_post_chat  # type: ignore[method-assign]

    try:
        provider.generate_metadata_candidates({"collection_name": "Dokumente", "ocr_text": "Demo", "title": "Demo"})
    except QwenProviderError as exc:
        assert "response_format fallback" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("fallback HTTP error escaped without becoming QwenProviderError")

    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]


def test_qwen_metadata_brain_prompt_requires_structured_candidates() -> None:
    rendered = PromptLoader().render(
        "secondbrain_metadata_prompt.tmpl",
        {
            "Collection": "Eingangsrechnung",
            "Title": "Demo",
            "CollectionSchema": "{}",
            "TitleRule": "{}",
            "CustomFields": "[]",
            "DeterministicMetadata": "{}",
            "ManualLockedFields": "{}",
            "SimilarDocuments": "[]",
            "ProcessingOptions": "{}",
            "OcrText": "Rechnung",
        },
    )
    assert "FINAL OUTPUT CONTRACT" in rendered.text
    assert "valid MINIFIED JSON object" in rendered.text
    assert "Close the JSON object even for long documents" in rendered.text
    assert "ISO 8601 YYYY-MM-DD" in rendered.text
    assert "ISO 639-1 lowercase" in rendered.text
    assert "amount.value must be a JSON number" in rendered.text
    assert '"sender"' in rendered.text
    assert '"custom_fields"' in rendered.text
    assert "Deterministic extraction is a candidate source, not automatic truth" in rendered.text


def test_metadata_extraction_still_succeeds_when_qwen_disabled(db_session: Session, tmp_path: Path) -> None:
    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    path = tmp_path / "demo.txt"
    path.write_text(text, encoding="utf-8")
    batch = Batch(collection_name="Eingangsrechnung", document_count=1)
    db_session.add(batch)
    db_session.flush()
    doc = Document(
        batch_id=batch.id,
        collection_name="Eingangsrechnung",
        original_filename="demo.txt",
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="2" * 64,
        processing_state=DocumentState.ocr_done,
        ocr_state=StageState.done,
        final_state=DocumentState.ocr_done,
        ocr_text=text,
    )
    db_session.add(doc)
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_enabled=False)
    db_session.refresh(doc)
    assert doc.processing_state == DocumentState.complete
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert doc.metadata_json["qwen_refinement"]["disabled"]


def test_metadata_processing_can_store_mocked_qwen_refinement(db_session: Session, tmp_path: Path) -> None:
    class MockQwen:
        def refine_metadata(self, payload: dict[str, Any]) -> QwenRefinement:
            prompt = PromptLoader().render("custom_field_prompt.tmpl", {"Content": payload["ocr_text"]})
            return QwenRefinement(
                raw_text='[{"field":"amount","value":"EUR205.25"}]',
                raw_response={"ok": True},
                prompt=prompt,
                endpoint="http://qwen-llama:8080",
                model="qwen.gguf",
            )

    text = "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"
    path = tmp_path / "demo-qwen.txt"
    path.write_text(text, encoding="utf-8")
    batch = Batch(collection_name="Eingangsrechnung", document_count=1)
    db_session.add(batch)
    db_session.flush()
    doc = Document(
        batch_id=batch.id,
        collection_name="Eingangsrechnung",
        original_filename="demo-qwen.txt",
        storage_path=str(path),
        mime_type="text/plain",
        file_size=len(text),
        sha256="3" * 64,
        processing_state=DocumentState.ocr_done,
        ocr_state=StageState.done,
        final_state=DocumentState.ocr_done,
        ocr_text=text,
    )
    db_session.add(doc)
    db_session.commit()

    run_metadata_for_document(db_session, doc.id, qwen_provider=MockQwen(), qwen_enabled=True)
    db_session.refresh(doc)
    assert doc.extracted_title == "Demo_PR400000005_12/10/2020_205,25"
    assert doc.qwen_response_text is not None
    assert doc.prompt_trace_json["metadata_refinement"]["name"] == "custom_field_prompt.tmpl"
    assert doc.model_trace_json["metadata_refinement"]["model"] == "qwen.gguf"


def test_integration_status_serializes_db_redis_and_models(monkeypatch, db_session: Session) -> None:
    class FakeRedis:
        def ping(self) -> bool:
            return True

    monkeypatch.setattr("app.services.integrations.redis.Redis.from_url", lambda url: FakeRedis())
    monkeypatch.setattr("app.services.integrations.httpx.get", lambda url, timeout: FakeResponse({}, 200))
    settings = Settings(
        redis_url="redis://example/0",
        glm_llamacpp_base_url="http://glm-llama:8080",
        qwen_llamacpp_base_url="http://qwen-llama:8080",
    )
    status = collect_integrations(db_session, settings)
    names = {row["name"] for row in status["integrations"]}
    assert status["ok"] is True
    assert {"database", "redis", "glm_llama", "qwen_llama"} <= names


def test_ocr_loop_compactor_removes_repeated_blocks_and_keeps_first_occurrence() -> None:
    text = """Title
A
B
A
B
A
B
Footer
Footer
Footer
Footer"""
    assert _compact_repeated_ocr_lines(text) == "Title\nA\nB\nFooter\nFooter\nFooter"


def test_ocr_loop_compactor_removes_inline_token_loops() -> None:
    text = "Latency 20s 16s 1s 1s 1s 1s 1s 1s done"
    assert _compact_repeated_ocr_lines(text) == "Latency 20s 16s 1s 1s done"


def test_ocr_loop_compactor_removes_inline_phrase_loops() -> None:
    text = "KV Length 1M tokens 1M tokens 1M tokens 1M tokens done"
    assert _compact_repeated_ocr_lines(text) == "KV Length 1M tokens 1M tokens done"


def test_ocr_loop_compactor_cuts_generated_numeric_arrow_chain() -> None:
    text = "01 → Q2 → KV1 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13"
    assert _compact_repeated_ocr_lines(text) == "01 → Q2 → KV1 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10"


def test_diagram_ocr_markdown_formatter_promotes_titles_and_bullets_labels() -> None:
    text = """MiniMax Sparse Attention
GQA-based Attention Block
Index Branch
Step 1 - Index Attention
Q1
Top-k
Sequence Length
512k
1M tokens"""
    assert _format_diagram_ocr_markdown_if_needed(text) == """# MiniMax Sparse Attention

## GQA-based Attention Block

## Index Branch

### Step 1 - Index Attention
- Q1

### Top-k

## Sequence Length
- 512k
- 1M tokens"""


def test_diagram_ocr_markdown_formatter_leaves_existing_markdown_alone() -> None:
    text = """# Already Markdown

- Attention
- Block"""
    assert _format_diagram_ocr_markdown_if_needed(text) == text
