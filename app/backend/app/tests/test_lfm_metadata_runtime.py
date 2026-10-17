from contextlib import nullcontext
import json

import httpx
import pytest

from app.config import Settings
from app.services.llm_qwen import QwenLlamaCppProvider


@pytest.mark.parametrize("method", [
    "generate_metadata_candidates", "extract_correspondent", "refine_metadata",
    "extract_created_date", "extract_document_type", "analyze_adhoc", "enrich_metadata",
])
def test_reasoning_metadata_preserves_names_and_has_room_to_finish(monkeypatch, method):
    calls = []
    leases = []

    def post(self, url, body):
        calls.append(body)
        return {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}

    def lock(*args, **kwargs):
        leases.append(kwargs["lease_seconds"])
        return nullcontext()

    monkeypatch.setattr(QwenLlamaCppProvider, "_post_chat", post)
    monkeypatch.setattr("app.services.llm_qwen.exclusive_model_gateway_lock", lock)
    provider = QwenLlamaCppProvider(Settings(qwen_metadata_thinking_enabled=True, llm_max_tokens=4096))
    getattr(provider, method)({"ocr_text": "Beispiel GmbH", "question": "Extract the sender"})
    body = calls[0]
    system = body["messages"][0]["content"]
    assert "Copy company and person names exactly" in system
    assert "Never translate company or person names" in system
    assert "<|think_off|>" not in system
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert body["max_tokens"] == 4096
    assert leases == [540]
    if method == "generate_metadata_candidates":
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["required"] == list(schema["properties"])
        for field in schema["properties"].values():
            assert field["type"] == "object"
            assert field["required"] == ["value", "confidence", "evidence"]
            assert field["additionalProperties"] is False
        assert schema["properties"]["amount"]["properties"]["value"]["type"] == ["number", "string"]


@pytest.mark.parametrize("thinking,limit,expected", [(True, 256, 256), (False, 4096, 2048)])
def test_metadata_respects_token_ceiling_and_thinking_off(monkeypatch, thinking, limit, expected):
    calls = []

    def post(self, url, body):
        calls.append(body)
        return {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}

    monkeypatch.setattr(QwenLlamaCppProvider, "_post_chat", post)
    monkeypatch.setattr("app.services.llm_qwen.exclusive_model_gateway_lock", lambda *a, **kw: nullcontext())
    provider = QwenLlamaCppProvider(Settings(qwen_metadata_thinking_enabled=thinking, llm_max_tokens=limit))
    provider.generate_metadata_candidates({"ocr_text": "Beispiel GmbH"})
    assert calls[0]["max_tokens"] == expected
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": thinking}
    assert ("<|think_off|>" in calls[0]["messages"][0]["content"]) == (not thinking)


@pytest.mark.parametrize("thinking,configured,expected", [(True, 120, 240), (True, 300, 300), (False, 120, 120)])
def test_reasoning_timeout_covers_cold_start_without_changing_non_reasoning(monkeypatch, thinking, configured, expected):
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={"choices": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.llm_qwen.httpx.post", post)
    provider = QwenLlamaCppProvider(Settings(qwen_metadata_thinking_enabled=thinking, llm_request_timeout_seconds=configured))
    provider._post_chat("http://localhost/v1/chat/completions", {})
    assert calls[0]["timeout"] == expected


@pytest.mark.parametrize("fenced", [False, True])
def test_metadata_json_preserves_literal_name_and_evidence_characters(monkeypatch, fenced):
    candidate = {"sender": {"value": "Beispiel `IT` GmbH", "confidence": 0.9, "evidence": "<content>Beispiel `IT` GmbH</content>"}}
    content = json.dumps(candidate)
    if fenced:
        content = "```json\n" + content + "\n```"
    monkeypatch.setattr(QwenLlamaCppProvider, "_post_chat", lambda *args: {"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr("app.services.llm_qwen.exclusive_model_gateway_lock", lambda *args, **kwargs: nullcontext())
    result = QwenLlamaCppProvider(Settings()).generate_metadata_candidates({"ocr_text": candidate["sender"]["value"]})
    assert json.loads(result.raw_text) == candidate
