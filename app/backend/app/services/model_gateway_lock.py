from __future__ import annotations

from contextlib import contextmanager
import logging
import time
import uuid
from typing import Iterator

from redis import Redis
from redis.exceptions import RedisError

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

LOCK_KEY = "dokocr:model_gateway:exclusive"
_UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class ModelGatewayLockTimeout(RuntimeError):
    pass


@contextmanager
def exclusive_model_gateway_lock(
    owner: str,
    *,
    settings: Settings | None = None,
    wait_timeout_seconds: float | None = None,
    lease_seconds: float | None = None,
) -> Iterator[None]:
    """Coordinate callers that share the single local llama.cpp/LM Studio gateway.

    The smart proxy can accept concurrent HTTP requests, but the upstream model
    runtime can fail when Qwen/model-switching and PaddleVL OCR overlap. This lock
    gates whole logical operations. A PaddleVL PDF batch acquires the lock once,
    then can still send multiple same-model page requests inside that protected
    section.
    """
    settings = settings or get_settings()
    wait_timeout_seconds = float(wait_timeout_seconds if wait_timeout_seconds is not None else max(settings.ocr_task_time_limit, 60))
    lease_seconds = float(lease_seconds if lease_seconds is not None else max(settings.ocr_task_time_limit + 120, 900))
    token = f"{owner}:{uuid.uuid4()}"
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        deadline = time.monotonic() + wait_timeout_seconds
        lease_ms = max(1000, int(lease_seconds * 1000))
        while True:
            if client.set(LOCK_KEY, token, nx=True, px=lease_ms):
                logger.info("Acquired model gateway lock owner=%s lease_seconds=%s", owner, lease_seconds)
                break
            if time.monotonic() >= deadline:
                raise ModelGatewayLockTimeout(f"Timed out waiting for model gateway lock owner={owner}")
            time.sleep(0.25)
        try:
            yield
        finally:
            try:
                client.eval(_UNLOCK_SCRIPT, 1, LOCK_KEY, token)
                logger.info("Released model gateway lock owner=%s", owner)
            except RedisError as exc:
                logger.warning("Could not release model gateway lock owner=%s error=%s", owner, exc)
    except RedisError as exc:
        logger.warning("Model gateway lock unavailable; continuing without lock owner=%s error=%s", owner, exc)
        yield
