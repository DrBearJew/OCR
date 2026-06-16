from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import AppSetting
from app.services.ocr_glm import llama_health_urls, list_llama_model_ids

MODEL_SETUP_KEY = "model_setup"


def default_model_setup(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "mode": "fake" if settings.ocr_provider == "fake" else ("local" if settings.ocr_provider == "ppocrv6" else "smart"),
        "ocr_provider": settings.ocr_provider,
        "paddle_vl_base_url": settings.paddle_vl_llamacpp_base_url,
        "paddle_vl_model": settings.paddle_vl_model_path,
        "glm_base_url": settings.glm_llamacpp_base_url,
        "glm_model": settings.glm_model_path,
        "qwen_enabled": settings.llm_metadata_refinement_enabled,
        "qwen_base_url": settings.qwen_llamacpp_base_url,
        "qwen_model": settings.qwen_model_path,
        "timeout_seconds": settings.llm_request_timeout_seconds,
    }


def get_model_setup(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    row = db.get(AppSetting, MODEL_SETUP_KEY)
    data = row.value_json if row and isinstance(row.value_json, dict) else {}
    return {**default_model_setup(settings), **data}


def save_model_setup(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_model_setup(db)
    next_value = {**current, **_clean_payload(payload)}
    row = db.get(AppSetting, MODEL_SETUP_KEY)
    if row is None:
        row = AppSetting(key=MODEL_SETUP_KEY, value_json=next_value)
        db.add(row)
    else:
        row.value_json = next_value
    db.commit()
    return next_value


def settings_with_model_setup(db: Session, settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    setup = get_model_setup(db, settings)
    updates: dict[str, Any] = {
        "ocr_provider": setup.get("ocr_provider") or settings.ocr_provider,
        "paddle_vl_llamacpp_base_url": setup.get("paddle_vl_base_url") or settings.paddle_vl_llamacpp_base_url,
        "paddle_vl_model_path": setup.get("paddle_vl_model") or settings.paddle_vl_model_path,
        "glm_llamacpp_base_url": setup.get("glm_base_url") or settings.glm_llamacpp_base_url,
        "glm_model_path": setup.get("glm_model") or settings.glm_model_path,
        "qwen_llamacpp_base_url": setup.get("qwen_base_url") or settings.qwen_llamacpp_base_url,
        "qwen_model_path": setup.get("qwen_model") or settings.qwen_model_path,
        "llm_metadata_refinement_enabled": bool(setup.get("qwen_enabled")),
    }
    if setup.get("timeout_seconds"):
        updates["llm_request_timeout_seconds"] = float(setup["timeout_seconds"])
    return settings.model_copy(update=updates)


def check_model_endpoint(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    timeout_s = float(payload.get("timeout_seconds") or settings.llm_request_timeout_seconds)
    if not base_url:
        return {"ok": False, "detail": "Base URL is required", "available_models": []}
    health_detail = "not checked"
    for url in llama_health_urls(base_url):
        try:
            response = httpx.get(url, timeout=min(5.0, timeout_s))
            if response.status_code < 500:
                health_detail = f"reachable via {url}"
                break
            health_detail = f"HTTP {response.status_code} from {url}"
        except httpx.HTTPError as exc:
            health_detail = str(exc)
    models = list_llama_model_ids(base_url, timeout_s=min(5.0, timeout_s))
    model_ok = not model or not models or model in models
    ok = health_detail.startswith("reachable") and model_ok
    detail = health_detail
    if not model_ok:
        detail = f"Model '{model}' was not found in /v1/models"
    return {"ok": ok, "detail": detail, "available_models": models, "base_url": base_url, "model": model}


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "mode", "ocr_provider", "paddle_vl_base_url", "paddle_vl_model",
        "glm_base_url", "glm_model", "qwen_enabled", "qwen_base_url",
        "qwen_model", "timeout_seconds",
    }
    cleaned = {key: value for key, value in payload.items() if key in allowed}
    if cleaned.get("ocr_provider") not in {"fake", "ppocrv6", "paddle_vl", "glm", None}:
        cleaned.pop("ocr_provider", None)
    if "qwen_enabled" in cleaned:
        cleaned["qwen_enabled"] = bool(cleaned["qwen_enabled"])
    return cleaned
