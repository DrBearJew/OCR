from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path
import threading
import time
from typing import Any

import httpx
import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.ocr_glm import list_llama_model_ids, llama_health_urls, openai_auth_headers
from app.services.model_setup import settings_with_model_setup


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IntegrationStatus:
    name: str
    ok: bool
    detail: str
    latency_ms: int | None = None
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata or {},
        }


def check_database(db: Session) -> IntegrationStatus:
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        return IntegrationStatus("database", True, "reachable", _elapsed_ms(start))
    except Exception as exc:  # noqa: BLE001
        return IntegrationStatus("database", False, str(exc), _elapsed_ms(start))


def check_redis(settings: Settings | None = None) -> IntegrationStatus:
    settings = settings or get_settings()
    start = time.perf_counter()
    try:
        client = redis.Redis.from_url(settings.redis_url)
        client.ping()
        return IntegrationStatus("redis", True, "reachable", _elapsed_ms(start))
    except Exception as exc:  # noqa: BLE001
        return IntegrationStatus("redis", False, str(exc), _elapsed_ms(start))


def check_llama(
    name: str,
    base_url: str,
    model: str,
    timeout_s: float,
    health_cache: dict[str, tuple[bool, str, int | None, int]] | None = None,
    cache_lock: threading.Lock | None = None,
    api_key: str | None = None,
) -> IntegrationStatus:
    start = time.perf_counter()
    normalized_url = (base_url or "").strip().rstrip("/")
    cache_key = f"{normalized_url}|{'auth' if (api_key or '').strip() else 'anon'}"
    if health_cache is not None and normalized_url:
        with cache_lock or threading.Lock():
            cached = health_cache.get(cache_key)
        if cached is not None:
            ok, detail, status_code, latency_ms = cached
            meta: dict[str, Any] = {"base_url": base_url, "model": model}
            if status_code is not None:
                meta["status_code"] = status_code
            return IntegrationStatus(name, ok, detail, latency_ms, meta)

    headers = openai_auth_headers(api_key, content_type=False)
    get_kwargs: dict[str, Any] = {"timeout": min(5.0, timeout_s)}
    if headers:
        get_kwargs["headers"] = headers
    last_error = "not checked"
    for url in llama_health_urls(base_url):
        try:
            response = httpx.get(url, **get_kwargs)
            if 200 <= response.status_code < 400:
                latency = _elapsed_ms(start)
                detail = f"reachable via {url}"
                if health_cache is not None and normalized_url:
                    with cache_lock or threading.Lock():
                        health_cache[cache_key] = (True, detail, response.status_code, latency)
                return IntegrationStatus(
                    name,
                    True,
                    detail,
                    latency,
                    {"base_url": base_url, "model": model, "status_code": response.status_code},
                )
            if response.status_code in {401, 403}:
                last_error = f"Authentication failed (HTTP {response.status_code}) at {url}"
                break
            last_error = f"HTTP {response.status_code} from {url}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
    latency = _elapsed_ms(start)
    if health_cache is not None and normalized_url:
        with cache_lock or threading.Lock():
            health_cache[cache_key] = (False, last_error, None, latency)
    return IntegrationStatus(name, False, last_error, latency, {"base_url": base_url, "model": model})


def _cached_model_ids(
    base_url: str,
    timeout_s: float,
    models_cache: dict[str, list[str]] | None = None,
    cache_lock: threading.Lock | None = None,
    api_key: str | None = None,
) -> list[str]:
    normalized_url = (base_url or "").strip().rstrip("/")
    cache_key = f"{normalized_url}|{'auth' if (api_key or '').strip() else 'anon'}"
    if models_cache is not None and normalized_url:
        with cache_lock or threading.Lock():
            cached = models_cache.get(cache_key)
        if cached is not None:
            return list(cached)
    model_ids = list_llama_model_ids(base_url, timeout_s=timeout_s, api_key=api_key)
    if models_cache is not None and normalized_url:
        with cache_lock or threading.Lock():
            models_cache[cache_key] = list(model_ids)
    return model_ids


def check_glm_multimodal(
    settings: Settings | None = None,
    models_cache: dict[str, list[str]] | None = None,
    cache_lock: threading.Lock | None = None,
) -> IntegrationStatus:
    settings = settings or get_settings()
    start = time.perf_counter()
    metadata: dict[str, Any] = {
        "base_url": settings.glm_llamacpp_base_url,
        "model": settings.glm_model_name,
        "mmproj_configured": bool(str(settings.glm_mmproj_path or "").strip()),
    }
    if not metadata["mmproj_configured"]:
        return IntegrationStatus("glm_multimodal_ocr", False, "GLM_MMPROJ_PATH is empty; text chat may work but image OCR is not configured", _elapsed_ms(start), metadata)
    model_ids = _cached_model_ids(
        settings.glm_llamacpp_base_url,
        timeout_s=min(5.0, settings.llm_request_timeout_seconds),
        models_cache=models_cache,
        cache_lock=cache_lock,
        api_key=settings.ocr_api_key,
    )
    metadata["available_models"] = model_ids
    configured_names = {settings.glm_model_name}
    path = Path(settings.glm_model_path)
    if path.suffix.lower() == ".gguf":
        configured_names.add(path.stem)
    if model_ids and not configured_names.intersection(model_ids):
        return IntegrationStatus(
            "glm_multimodal_ocr",
            False,
            f"Configured GLM model '{settings.glm_model_name}' not found in /v1/models",
            _elapsed_ms(start),
            metadata,
        )
    return IntegrationStatus("glm_multimodal_ocr", True, "multimodal OCR config looks usable", _elapsed_ms(start), metadata)


def check_paddle_vl_multimodal(
    settings: Settings | None = None,
    models_cache: dict[str, list[str]] | None = None,
    cache_lock: threading.Lock | None = None,
) -> IntegrationStatus:
    settings = settings or get_settings()
    start = time.perf_counter()
    metadata: dict[str, Any] = {
        "base_url": settings.paddle_vl_llamacpp_base_url,
        "model": settings.paddle_vl_model_name,
        "mmproj_configured": bool(str(settings.paddle_vl_mmproj_path or "").strip()),
    }
    if not metadata["mmproj_configured"]:
        return IntegrationStatus("paddle_vl_multimodal_ocr", False, "PADDLE_VL_MMPROJ_PATH is empty; image parsing is not configured", _elapsed_ms(start), metadata)
    model_ids = _cached_model_ids(
        settings.paddle_vl_llamacpp_base_url,
        timeout_s=min(5.0, settings.llm_request_timeout_seconds),
        models_cache=models_cache,
        cache_lock=cache_lock,
        api_key=settings.ocr_api_key,
    )
    metadata["available_models"] = model_ids
    configured_names = {settings.paddle_vl_model_name}
    path = Path(settings.paddle_vl_model_path)
    if path.suffix.lower() == ".gguf":
        configured_names.add(path.stem)
    if model_ids and not configured_names.intersection(model_ids):
        return IntegrationStatus(
            "paddle_vl_multimodal_ocr",
            False,
            f"Configured PaddleOCR-VL model '{settings.paddle_vl_model_name}' not found in /v1/models",
            _elapsed_ms(start),
            metadata,
        )
    return IntegrationStatus("paddle_vl_multimodal_ocr", True, "PaddleOCR-VL multimodal parser config looks usable", _elapsed_ms(start), metadata)


def check_celery_workers(settings: Settings | None = None) -> IntegrationStatus:
    settings = settings or get_settings()
    start = time.perf_counter()
    metadata: dict[str, Any] = {"queues": {}, "active_tasks": {}}
    try:
        client = redis.Redis.from_url(settings.broker_url)
        for queue in ("ocr", "metadata", "maintenance", "celery"):
            metadata["queues"][queue] = int(client.llen(queue))
    except Exception as exc:  # noqa: BLE001
        metadata["queue_error"] = str(exc)
    try:
        from app.workers.celery_app import celery_app

        inspect = celery_app.control.inspect(timeout=0.35)
        active = inspect.active() or {}
        if active:
            workers = sorted(active.keys())
        else:
            ping = inspect.ping() or {}
            workers = sorted(ping.keys())
        metadata["workers"] = workers
        metadata["active_tasks"] = {
            worker: [
                {"id": item.get("id"), "name": item.get("name"), "delivery_info": item.get("delivery_info", {})}
                for item in tasks
            ]
            for worker, tasks in active.items()
        }
        ok = bool(workers)
        return IntegrationStatus("celery_workers", ok, "workers reachable" if ok else "no Celery workers responded", _elapsed_ms(start), metadata)
    except Exception as exc:  # noqa: BLE001
        return IntegrationStatus("celery_workers", False, str(exc), _elapsed_ms(start), metadata)


def collect_integrations(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or settings_with_model_setup(db, get_settings())
    db_status = check_database(db)
    health_cache: dict[str, tuple[bool, str, int | None, int]] = {}
    models_cache: dict[str, list[str]] = {}
    cache_lock = threading.Lock()

    def _check_models_chain() -> tuple[IntegrationStatus, IntegrationStatus, IntegrationStatus, IntegrationStatus, IntegrationStatus]:
        paddle_llama = check_llama(
            "paddle_vl_llama",
            settings.paddle_vl_llamacpp_base_url,
            settings.paddle_vl_model_name,
            settings.llm_request_timeout_seconds,
            health_cache,
            cache_lock,
            api_key=settings.ocr_api_key,
        )
        paddle_mm = check_paddle_vl_multimodal(settings, models_cache, cache_lock)
        glm_llama = check_llama(
            "glm_llama",
            settings.glm_llamacpp_base_url,
            settings.glm_model_name,
            settings.llm_request_timeout_seconds,
            health_cache,
            cache_lock,
            api_key=settings.ocr_api_key,
        )
        glm_mm = check_glm_multimodal(settings, models_cache, cache_lock)
        qwen_llama = check_llama(
            "qwen_llama",
            settings.qwen_llamacpp_base_url,
            settings.qwen_model_name,
            settings.llm_request_timeout_seconds,
            health_cache,
            cache_lock,
            api_key=settings.qwen_api_key,
        )
        return paddle_llama, paddle_mm, glm_llama, glm_mm, qwen_llama

    with ThreadPoolExecutor(max_workers=3) as pool:
        redis_future = pool.submit(check_redis, settings)
        models_future = pool.submit(_check_models_chain)
        workers_future = pool.submit(check_celery_workers, settings)
        redis_status = redis_future.result()
        paddle_llama, paddle_mm, glm_llama, glm_mm, qwen_llama = models_future.result()
        workers_status = workers_future.result()

    statuses = [
        db_status,
        redis_status,
        paddle_llama,
        paddle_mm,
        glm_llama,
        glm_mm,
        qwen_llama,
        workers_status,
    ]
    if settings.ocr_provider == "openai_vision":
        openai_vision_status = check_llama(
            "openai_vision_ocr",
            settings.openai_vision_base_url,
            settings.openai_vision_model_name or "auto",
            settings.llm_request_timeout_seconds,
            health_cache,
            cache_lock,
            api_key=settings.ocr_api_key,
        )
        statuses.insert(2, openai_vision_status)
    return {
        "ok": all(item.ok for item in statuses[:2]),
        "integrations": [item.as_dict() for item in statuses],
    }


def log_startup_model_status(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for name, base_url, model in (
        ("paddle_vl_llama", settings.paddle_vl_llamacpp_base_url, settings.paddle_vl_model_name),
        ("glm_llama", settings.glm_llamacpp_base_url, settings.glm_model_name),
        ("qwen_llama", settings.qwen_llamacpp_base_url, settings.qwen_model_name),
    ):
        status = check_llama(name, base_url, model, settings.llm_request_timeout_seconds)
        level = logging.INFO if status.ok else logging.WARNING
        logger.log(level, "Integration startup check %s ok=%s detail=%s", name, status.ok, status.detail)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
