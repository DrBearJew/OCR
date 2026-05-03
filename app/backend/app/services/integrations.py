from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any

import httpx
import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.ocr_glm import list_llama_model_ids, llama_health_urls


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


def check_llama(name: str, base_url: str, model: str, timeout_s: float) -> IntegrationStatus:
    start = time.perf_counter()
    last_error = "not checked"
    for url in llama_health_urls(base_url):
        try:
            response = httpx.get(url, timeout=min(5.0, timeout_s))
            if response.status_code < 500:
                return IntegrationStatus(
                    name,
                    True,
                    f"reachable via {url}",
                    _elapsed_ms(start),
                    {"base_url": base_url, "model": model, "status_code": response.status_code},
                )
            last_error = f"HTTP {response.status_code} from {url}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
    return IntegrationStatus(name, False, last_error, _elapsed_ms(start), {"base_url": base_url, "model": model})


def check_glm_multimodal(settings: Settings | None = None) -> IntegrationStatus:
    settings = settings or get_settings()
    start = time.perf_counter()
    metadata: dict[str, Any] = {
        "base_url": settings.glm_llamacpp_base_url,
        "model": settings.glm_model_name,
        "mmproj_configured": bool(str(settings.glm_mmproj_path or "").strip()),
    }
    if not metadata["mmproj_configured"]:
        return IntegrationStatus("glm_multimodal_ocr", False, "GLM_MMPROJ_PATH is empty; text chat may work but image OCR is not configured", _elapsed_ms(start), metadata)
    model_ids = list_llama_model_ids(settings.glm_llamacpp_base_url, timeout_s=min(5.0, settings.llm_request_timeout_seconds))
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
    # A full smoke OCR request would consume model time. This check validates the
    # two configuration failures that caused text-health to look green while OCR hung.
    return IntegrationStatus("glm_multimodal_ocr", True, "multimodal OCR config looks usable", _elapsed_ms(start), metadata)


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

        inspect = celery_app.control.inspect(timeout=1.0)
        ping = inspect.ping() or {}
        active = inspect.active() or {}
        metadata["workers"] = sorted(ping.keys())
        metadata["active_tasks"] = {
            worker: [
                {"id": item.get("id"), "name": item.get("name"), "delivery_info": item.get("delivery_info", {})}
                for item in tasks
            ]
            for worker, tasks in active.items()
        }
        ok = bool(ping)
        return IntegrationStatus("celery_workers", ok, "workers reachable" if ok else "no Celery workers responded", _elapsed_ms(start), metadata)
    except Exception as exc:  # noqa: BLE001
        return IntegrationStatus("celery_workers", False, str(exc), _elapsed_ms(start), metadata)


def collect_integrations(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    statuses = [
        check_database(db),
        check_redis(settings),
        check_llama("glm_llama", settings.glm_llamacpp_base_url, settings.glm_model_name, settings.llm_request_timeout_seconds),
        check_glm_multimodal(settings),
        check_llama("qwen_llama", settings.qwen_llamacpp_base_url, settings.qwen_model_name, settings.llm_request_timeout_seconds),
        check_celery_workers(settings),
    ]
    return {
        "ok": all(item.ok for item in statuses[:2]),
        "integrations": [item.as_dict() for item in statuses],
    }


def log_startup_model_status(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for name, base_url, model in (
        ("glm_llama", settings.glm_llamacpp_base_url, settings.glm_model_name),
        ("qwen_llama", settings.qwen_llamacpp_base_url, settings.qwen_model_name),
    ):
        status = check_llama(name, base_url, model, settings.llm_request_timeout_seconds)
        level = logging.INFO if status.ok else logging.WARNING
        logger.log(level, "Integration startup check %s ok=%s detail=%s", name, status.ok, status.detail)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
