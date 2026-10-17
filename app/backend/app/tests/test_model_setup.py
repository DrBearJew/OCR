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

    assert saved["ocr_provider"] in {"fake", "ppocrv6", "paddle_vl", "glm"}
    assert saved["ocr_provider"] != "qwen"
    assert saved["mode"] == "smart"


def test_endpoint_test_requires_base_url():
    result = check_model_endpoint({"base_url": "", "model": "anything"})

    assert result["ok"] is False
    assert "Base URL" in result["detail"]
