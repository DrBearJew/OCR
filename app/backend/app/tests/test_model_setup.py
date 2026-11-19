from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import ModelSetupRead, ModelSetupWrite
from app.services.model_setup import check_model_endpoint, get_model_setup, save_model_setup, settings_with_model_setup


def test_model_setup_defaults_from_settings(db_session):
    settings = Settings(
        ocr_provider="ppocrv6",
        paddle_vl_llamacpp_base_url="http://paddle.local/v1",
        paddle_vl_model_path="paddleocr-vl",
        qwen_llamacpp_base_url="http://qwen.local/v1",
        qwen_model_path="lmstudio-community/qwen",
        llm_metadata_refinement_enabled=True,
        ocr_pdf_text_layer_auto_enabled=False,
        ocr_pdf_text_layer_min_chars=150,
        ocr_pdf_text_layer_min_chars_per_page=35,
    )

    setup = get_model_setup(db_session, settings)

    assert setup["mode"] == "local"
    assert setup["ocr_provider"] == "ppocrv6"
    assert setup["paddle_vl_base_url"] == "http://paddle.local/v1"
    assert setup["qwen_model"] == "lmstudio-community/qwen"
    assert setup["qwen_enabled"] is True
    read = ModelSetupRead(**setup)
    assert read.ocr_pdf_text_layer_auto_enabled is False
    assert read.ocr_pdf_text_layer_min_chars == 150
    assert read.ocr_pdf_text_layer_min_chars_per_page == 35


def test_saved_model_setup_overrides_settings_and_preserves_lmstudio_model_id(db_session):
    save_model_setup(db_session, {
        "mode": "smart",
        "ocr_provider": "paddle_vl",
        "paddle_vl_base_url": "http://host.docker.internal:1234/v1",
        "paddle_vl_model": "lmstudio-community/paddleocr-vl",
        "qwen_enabled": True,
        "qwen_base_url": "http://host.docker.internal:1234/v1",
        "qwen_model": "lmstudio-community/qwen3",
    })

    settings = settings_with_model_setup(db_session, Settings(ocr_provider="fake"))

    assert settings.ocr_provider == "paddle_vl"
    assert settings.paddle_vl_llamacpp_base_url == "http://host.docker.internal:1234/v1"
    assert settings.paddle_vl_model_name == "lmstudio-community/paddleocr-vl"
    assert settings.qwen_model_name == "lmstudio-community/qwen3"
    assert settings.llm_metadata_refinement_enabled is True


def test_saved_model_setup_overrides_ocr_timeout_budget(db_session):
    save_model_setup(db_session, {
        "ocr_task_soft_time_limit": 900,
        "ocr_task_time_limit": 990,
        "ocr_task_hard_time_limit_grace_seconds": 180,
        "ocr_task_lease_grace_seconds": 420,
        "ocr_task_base_overhead_seconds": 240,
        "ocr_task_paddle_vl_seconds_per_chunk": 150,
        "ocr_task_glm_seconds_per_page": 210,
        "ocr_task_ppocrv6_seconds_per_page": 45,
        "ocr_pdf_text_layer_auto_enabled": False,
        "ocr_pdf_text_layer_min_chars": 120,
        "ocr_pdf_text_layer_min_chars_per_page": 30,
    })

    settings = settings_with_model_setup(db_session, Settings())

    assert settings.ocr_task_soft_time_limit == 900
    assert settings.ocr_task_time_limit == 990
    assert settings.ocr_task_hard_time_limit_grace_seconds == 180
    assert settings.ocr_task_lease_grace_seconds == 420
    assert settings.ocr_task_base_overhead_seconds == 240
    assert settings.ocr_task_paddle_vl_seconds_per_chunk == 150
    assert settings.ocr_task_glm_seconds_per_page == 210
    assert settings.ocr_task_ppocrv6_seconds_per_page == 45
    assert settings.ocr_pdf_text_layer_auto_enabled is False
    assert settings.ocr_pdf_text_layer_min_chars == 120
    assert settings.ocr_pdf_text_layer_min_chars_per_page == 30


@pytest.mark.parametrize("field", ["ocr_pdf_text_layer_min_chars", "ocr_pdf_text_layer_min_chars_per_page"])
@pytest.mark.parametrize("value", [0, -1])
def test_model_setup_schema_rejects_nonpositive_pdf_text_thresholds(field, value):
    with pytest.raises(ValidationError):
        ModelSetupWrite(**{field: value})


def test_model_setup_rejects_invalid_ocr_provider(db_session):
    saved = save_model_setup(db_session, {"ocr_provider": "qwen", "mode": "smart"})

    assert saved["ocr_provider"] in {"fake", "ppocrv6", "paddle_vl", "glm", "openai_vision"}
    assert saved["ocr_provider"] != "qwen"
    assert saved["mode"] == "smart"


def test_endpoint_test_requires_base_url():
    result = check_model_endpoint({"base_url": "", "model": "anything"})

    assert result["ok"] is False
    assert "Base URL" in result["detail"]


def test_model_setup_api_keys_are_write_only_and_preserved(db_session):
    saved = save_model_setup(db_session, {
        "ocr_provider": "openai_vision",
        "openai_vision_base_url": "http://host.docker.internal:1234/v1",
        "openai_vision_model": "auto",
        "ocr_api_key": "sk-ocr-secret-123",
        "qwen_enabled": True,
        "qwen_base_url": "http://host.docker.internal:1234/v1",
        "qwen_model": "auto",
        "qwen_api_key": "sk-meta-secret-456",
    })

    assert saved["ocr_provider"] == "openai_vision"
    assert saved["ocr_api_key_configured"] is True
    assert saved["qwen_api_key_configured"] is True
    assert "ocr_api_key" not in saved
    assert "qwen_api_key" not in saved

    # Blank update preserves saved keys
    updated = save_model_setup(db_session, {
        "ocr_provider": "openai_vision",
        "ocr_api_key": "",
        "qwen_api_key": "",
    })
    assert updated["ocr_api_key_configured"] is True
    assert updated["qwen_api_key_configured"] is True

    runtime_settings = settings_with_model_setup(db_session, Settings(ocr_provider="fake"))
    assert runtime_settings.ocr_provider == "openai_vision"
    assert runtime_settings.ocr_api_key == "sk-ocr-secret-123"
    assert runtime_settings.qwen_api_key == "sk-meta-secret-456"

    # Explicit clear removes only the requested key
    cleared = save_model_setup(db_session, {"clear_ocr_api_key": True})
    assert cleared["ocr_api_key_configured"] is False
    assert cleared["qwen_api_key_configured"] is True


def test_check_model_endpoint_handles_lmstudio_404_health_and_401_auth(db_session, monkeypatch):
    import httpx
    from app.services import model_setup as ms_mod
    from app.services import ocr_glm as ocr_mod

    save_model_setup(db_session, {"ocr_api_key": "sk-saved-key"})
    seen_headers: list[dict] = []

    class FakeResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=self)  # type: ignore[arg-type]

    def fake_get(url: str, headers=None, timeout=None):
        seen_headers.append(dict(headers or {}))
        if url.endswith("/health"):
            return FakeResp(404, {"error": "not found"})
        if (headers or {}).get("Authorization") != "Bearer sk-saved-key":
            return FakeResp(401, {"error": "unauthorized"})
        return FakeResp(200, {"data": [{"id": "qwen2.5-vl-7b"}, {"id": "lfm2.5-8b"}]})

    monkeypatch.setattr(ms_mod.httpx, "get", fake_get)
    monkeypatch.setattr(ocr_mod.httpx, "get", fake_get)

    # Unauthenticated request fails with auth error (never false-positive)
    denied = check_model_endpoint({"base_url": "http://lmstudio.local:1234/v1", "model": "auto"})
    assert denied["ok"] is False
    assert "401" in denied["detail"]

    # Saved-key request succeeds via /v1/models fallback and returns models
    ok_res = check_model_endpoint(
        {"base_url": "http://lmstudio.local:1234/v1", "model": "auto", "use_saved_key_for": "ocr"},
        db=db_session,
    )
    assert ok_res["ok"] is True
    assert ok_res["available_models"] == ["qwen2.5-vl-7b", "lfm2.5-8b"]


def test_openai_vision_provider_auto_model_and_clean_payload(tmp_path, monkeypatch):
    from PIL import Image
    from app.services import ocr_glm as ocr_mod
    from app.services.ocr_glm import OpenAIVisionOCRProvider, build_ocr_provider

    img_path = tmp_path / "invoice.png"
    Image.new("RGB", (64, 64), color=(255, 255, 255)).save(img_path)

    captured: dict = {}

    class FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=None):
        captured["models_auth"] = (headers or {}).get("Authorization")
        return FakeResp({"data": [{"id": "lmstudio/qwen2.5-vl-7b"}]})

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResp({"choices": [{"message": {"content": "Rechnung 42,00 EUR"}}]})

    monkeypatch.setattr(ocr_mod.httpx, "get", fake_get)
    monkeypatch.setattr(ocr_mod.httpx, "post", fake_post)

    settings = Settings(
        ocr_provider="openai_vision",
        openai_vision_base_url="http://host.docker.internal:1234/v1",
        openai_vision_model="auto",
        ocr_api_key="sk-vision-test",
    )
    provider = build_ocr_provider(settings)
    assert isinstance(provider, OpenAIVisionOCRProvider)

    result = provider.extract_text(str(img_path))
    assert result.text == "Rechnung 42,00 EUR"
    assert result.model_name == "lmstudio/qwen2.5-vl-7b"
    assert captured["models_auth"] == "Bearer sk-vision-test"
    assert captured["headers"]["Authorization"] == "Bearer sk-vision-test"
    assert "repeat_penalty" not in captured["json"]
    assert "cache_prompt" not in captured["json"]


def test_qwen_provider_strips_chat_template_kwargs_and_sends_bearer_on_external_server(monkeypatch):
    import httpx
    from app.services import llm_qwen as qwen_mod
    from app.services.llm_qwen import QwenLlamaCppProvider

    calls: list[dict] = []

    class FakeResp:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("bad request", request=None, response=self)  # type: ignore[arg-type]

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if "chat_template_kwargs" in (json or {}):
            return FakeResp(400, {"error": "unknown field chat_template_kwargs"})
        return FakeResp(200, {"choices": [{"message": {"content": '{"sender": {"value": "Acme", "confidence": 0.9, "evidence": "Acme"}}'}}]})

    monkeypatch.setattr(qwen_mod.httpx, "post", fake_post)
    monkeypatch.setattr(qwen_mod, "list_llama_model_ids", lambda *a, **kw: ["lmstudio/qwen3-8b"])

    settings = Settings(
        qwen_llamacpp_base_url="http://host.docker.internal:1234/v1",
        qwen_model_path="auto",
        qwen_api_key="sk-meta-key",
        llm_metadata_refinement_enabled=True,
    )
    provider = QwenLlamaCppProvider(settings)
    res = provider.generate_metadata_candidates({"collection_name": "Dokumente", "ocr_text": "Acme Invoice 10 EUR"})

    assert len(calls) == 2
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-meta-key"
    assert calls[0]["json"]["model"] == "lmstudio/qwen3-8b"
    assert "chat_template_kwargs" not in calls[1]["json"]
    assert "response_format" not in calls[1]["json"]
    assert "Acme" in res.raw_text
