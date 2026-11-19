from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AppSetting
from app.services.ocr_glm import llama_health_urls, list_llama_model_ids, openai_auth_headers

MODEL_SETUP_KEY = "model_setup"


def _raw_model_setup(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    row = db.get(AppSetting, MODEL_SETUP_KEY)
    data = row.value_json if row and isinstance(row.value_json, dict) else {}
    return {**default_model_setup(settings), **data}


def default_model_setup(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "mode": "fake" if settings.ocr_provider == "fake" else ("local" if settings.ocr_provider == "ppocrv6" else "smart"),
        "ocr_provider": settings.ocr_provider,
        "paddle_vl_base_url": settings.paddle_vl_llamacpp_base_url,
        "paddle_vl_model": settings.paddle_vl_model_path,
        "glm_base_url": settings.glm_llamacpp_base_url,
        "glm_model": settings.glm_model_path,
        "openai_vision_base_url": settings.openai_vision_base_url,
        "openai_vision_model": settings.openai_vision_model,
        "ocr_api_key": settings.ocr_api_key,
        "qwen_enabled": settings.llm_metadata_refinement_enabled,
        "qwen_base_url": settings.qwen_llamacpp_base_url,
        "qwen_model": settings.qwen_model_path,
        "qwen_api_key": settings.qwen_api_key,
        "timeout_seconds": settings.llm_request_timeout_seconds,
        "ocr_task_soft_time_limit": settings.ocr_task_soft_time_limit,
        "ocr_task_time_limit": settings.ocr_task_time_limit,
        "ocr_task_hard_time_limit_grace_seconds": settings.ocr_task_hard_time_limit_grace_seconds,
        "ocr_task_lease_grace_seconds": settings.ocr_task_lease_grace_seconds,
        "ocr_task_base_overhead_seconds": settings.ocr_task_base_overhead_seconds,
        "ocr_task_paddle_vl_seconds_per_chunk": settings.ocr_task_paddle_vl_seconds_per_chunk,
        "ocr_task_glm_seconds_per_page": settings.ocr_task_glm_seconds_per_page,
        "ocr_task_openai_vision_seconds_per_page": settings.ocr_task_openai_vision_seconds_per_page,
        "ocr_task_ppocrv6_seconds_per_page": settings.ocr_task_ppocrv6_seconds_per_page,
        "ocr_pdf_text_layer_auto_enabled": settings.ocr_pdf_text_layer_auto_enabled,
        "ocr_pdf_text_layer_min_chars": settings.ocr_pdf_text_layer_min_chars,
        "ocr_pdf_text_layer_min_chars_per_page": settings.ocr_pdf_text_layer_min_chars_per_page,
    }


def _public_model_setup(raw: dict[str, Any]) -> dict[str, Any]:
    public = {k: v for k, v in raw.items() if k not in {"ocr_api_key", "qwen_api_key"}}
    public["ocr_api_key_configured"] = bool(str(raw.get("ocr_api_key") or "").strip())
    public["qwen_api_key_configured"] = bool(str(raw.get("qwen_api_key") or "").strip())
    return public


def get_model_setup(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    return _public_model_setup(_raw_model_setup(db, settings))


def save_model_setup(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = _raw_model_setup(db)
    cleaned = _clean_payload(payload)
    if payload.get("clear_ocr_api_key"):
        cleaned["ocr_api_key"] = ""
    elif "ocr_api_key" in cleaned and not str(cleaned["ocr_api_key"] or "").strip():
        cleaned.pop("ocr_api_key", None)
    if payload.get("clear_qwen_api_key"):
        cleaned["qwen_api_key"] = ""
    elif "qwen_api_key" in cleaned and not str(cleaned["qwen_api_key"] or "").strip():
        cleaned.pop("qwen_api_key", None)
    next_value = {**current, **cleaned}
    row = db.get(AppSetting, MODEL_SETUP_KEY)
    if row is None:
        row = AppSetting(key=MODEL_SETUP_KEY, value_json=next_value)
        db.add(row)
    else:
        row.value_json = next_value
    db.commit()
    return _public_model_setup(next_value)


def settings_with_model_setup(db: Session, settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    setup = _raw_model_setup(db, settings)
    updates: dict[str, Any] = {
        "ocr_provider": setup.get("ocr_provider") or settings.ocr_provider,
        "paddle_vl_llamacpp_base_url": setup.get("paddle_vl_base_url") or settings.paddle_vl_llamacpp_base_url,
        "paddle_vl_model_path": setup.get("paddle_vl_model") or settings.paddle_vl_model_path,
        "glm_llamacpp_base_url": setup.get("glm_base_url") or settings.glm_llamacpp_base_url,
        "glm_model_path": setup.get("glm_model") or settings.glm_model_path,
        "openai_vision_base_url": setup.get("openai_vision_base_url") or settings.openai_vision_base_url,
        "openai_vision_model": setup.get("openai_vision_model") if setup.get("openai_vision_model") is not None else settings.openai_vision_model,
        "ocr_api_key": str(setup.get("ocr_api_key") or settings.ocr_api_key or ""),
        "qwen_llamacpp_base_url": setup.get("qwen_base_url") or settings.qwen_llamacpp_base_url,
        "qwen_model_path": setup.get("qwen_model") or settings.qwen_model_path,
        "qwen_api_key": str(setup.get("qwen_api_key") or settings.qwen_api_key or ""),
        "llm_metadata_refinement_enabled": bool(setup.get("qwen_enabled")),
        "ocr_pdf_text_layer_auto_enabled": bool(setup.get("ocr_pdf_text_layer_auto_enabled")),
    }
    if setup.get("timeout_seconds"):
        updates["llm_request_timeout_seconds"] = float(setup["timeout_seconds"])
    for key in (
        "ocr_task_soft_time_limit",
        "ocr_task_time_limit",
        "ocr_task_hard_time_limit_grace_seconds",
        "ocr_task_lease_grace_seconds",
        "ocr_task_base_overhead_seconds",
        "ocr_task_paddle_vl_seconds_per_chunk",
        "ocr_task_glm_seconds_per_page",
        "ocr_task_openai_vision_seconds_per_page",
        "ocr_task_ppocrv6_seconds_per_page",
        "ocr_pdf_text_layer_min_chars",
        "ocr_pdf_text_layer_min_chars_per_page",
    ):
        if setup.get(key) is not None:
            updates[key] = int(setup[key])
    return settings.model_copy(update=updates)


def check_model_endpoint(
    payload: dict[str, Any],
    settings: Settings | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    timeout_s = float(payload.get("timeout_seconds") or settings.llm_request_timeout_seconds)
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key and db is not None:
        key_role = str(payload.get("use_saved_key_for") or "").strip().lower()
        if key_role in {"ocr", "qwen"}:
            raw_setup = _raw_model_setup(db, settings)
            api_key = str(raw_setup.get("ocr_api_key" if key_role == "ocr" else "qwen_api_key") or "").strip()
    if not base_url:
        return {"ok": False, "detail": "Base URL is required", "available_models": []}
    headers = openai_auth_headers(api_key, content_type=False)
    get_kwargs: dict[str, Any] = {"timeout": min(5.0, timeout_s)}
    if headers:
        get_kwargs["headers"] = headers
    health_detail = "not checked"
    auth_error = False
    for url in llama_health_urls(base_url):
        try:
            response = httpx.get(url, **get_kwargs)
            if 200 <= response.status_code < 400:
                health_detail = f"reachable via {url}"
                break
            if response.status_code in {401, 403}:
                health_detail = f"Authentication failed (HTTP {response.status_code}) at {url}"
                auth_error = True
                break
            health_detail = f"HTTP {response.status_code} from {url}"
        except httpx.HTTPError as exc:
            health_detail = str(exc)
    models = [] if auth_error else list_llama_model_ids(base_url, timeout_s=min(5.0, timeout_s), api_key=api_key)
    model_is_auto = not model or model.lower() == "auto"
    model_ok = model_is_auto or not models or model in models
    ok = (not auth_error) and health_detail.startswith("reachable") and model_ok
    detail = health_detail
    if not auth_error and not model_ok:
        detail = f"Model '{model}' was not found in /v1/models"
    return {"ok": ok, "detail": detail, "available_models": models, "base_url": base_url, "model": model}


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "mode", "ocr_provider", "paddle_vl_base_url", "paddle_vl_model",
        "glm_base_url", "glm_model", "openai_vision_base_url", "openai_vision_model",
        "ocr_api_key", "qwen_enabled", "qwen_base_url", "qwen_model", "qwen_api_key",
        "timeout_seconds",
        "ocr_task_soft_time_limit", "ocr_task_time_limit",
        "ocr_task_hard_time_limit_grace_seconds", "ocr_task_lease_grace_seconds",
        "ocr_task_base_overhead_seconds", "ocr_task_paddle_vl_seconds_per_chunk",
        "ocr_task_glm_seconds_per_page", "ocr_task_openai_vision_seconds_per_page",
        "ocr_task_ppocrv6_seconds_per_page",
        "ocr_pdf_text_layer_auto_enabled", "ocr_pdf_text_layer_min_chars",
        "ocr_pdf_text_layer_min_chars_per_page",
    }
    cleaned = {key: value for key, value in payload.items() if key in allowed}
    if cleaned.get("ocr_provider") not in {"fake", "ppocrv6", "paddle_vl", "glm", "openai_vision", None}:
        cleaned.pop("ocr_provider", None)
    if "qwen_enabled" in cleaned:
        cleaned["qwen_enabled"] = bool(cleaned["qwen_enabled"])
    for key in ("ocr_api_key", "qwen_api_key"):
        if key in cleaned and cleaned[key] is not None:
            cleaned[key] = str(cleaned[key]).strip()
    for key in (
        "ocr_task_soft_time_limit",
        "ocr_task_time_limit",
        "ocr_task_hard_time_limit_grace_seconds",
        "ocr_task_lease_grace_seconds",
        "ocr_task_base_overhead_seconds",
        "ocr_task_paddle_vl_seconds_per_chunk",
        "ocr_task_glm_seconds_per_page",
        "ocr_task_openai_vision_seconds_per_page",
        "ocr_task_ppocrv6_seconds_per_page",
        "ocr_pdf_text_layer_min_chars",
        "ocr_pdf_text_layer_min_chars_per_page",
    ):
        if key in cleaned:
            try:
                cleaned[key] = max(1, int(cleaned[key]))
            except (TypeError, ValueError):
                cleaned.pop(key, None)
    return cleaned
