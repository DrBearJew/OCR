from __future__ import annotations

import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis import Redis
from redis.exceptions import RedisError

from app.auth import create_access_token
from app.config import Settings, get_settings
from app.schemas import LoginRequest, TokenResponse


router = APIRouter(prefix="/api/auth", tags=["auth"])
_FALLBACK_ATTEMPTS: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _check_rate_limit(request, payload.username, settings)
    username_ok = secrets.compare_digest(payload.username, settings.admin_username)
    password_ok = secrets.compare_digest(payload.password, settings.admin_password)
    if not (username_ok and password_ok):
        _record_failed_login(request, payload.username, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    _clear_failed_login(request, payload.username, settings)
    token = create_access_token(settings.admin_username, settings)
    response.set_cookie(
        "dokocr_session",
        token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return TokenResponse(access_token=token)


def _login_key(request: Request, username: str) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"dokocr:login:{client_host}:{username}"


def _ip_key(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"dokocr:login-ip:{client_host}"


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _check_rate_limit(request: Request, username: str, settings: Settings) -> None:
    keys = [_ip_key(request), _login_key(request, username)]
    try:
        client = _redis(settings)
        attempts = [client.get(key) for key in keys]
    except RedisError:
        if settings.is_production:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login rate limiter unavailable")
        _check_fallback_rate_limit(keys, settings)
        return
    if any(value is not None and int(value) >= settings.login_rate_limit_attempts for value in attempts):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed login attempts")


def _record_failed_login(request: Request, username: str, settings: Settings) -> None:
    try:
        client = _redis(settings)
        for key in [_ip_key(request), _login_key(request, username)]:
            attempts = client.incr(key)
            if attempts == 1:
                client.expire(key, settings.login_rate_limit_window_seconds)
    except RedisError:
        for key in [_ip_key(request), _login_key(request, username)]:
            _record_fallback_failure(key, settings)
        return


def _clear_failed_login(request: Request, username: str, settings: Settings) -> None:
    try:
        client = _redis(settings)
        for key in [_ip_key(request), _login_key(request, username)]:
            client.delete(key)
    except RedisError:
        for key in [_ip_key(request), _login_key(request, username)]:
            _FALLBACK_ATTEMPTS.pop(key, None)
        return


def _check_fallback_rate_limit(keys: list[str], settings: Settings) -> None:
    now = time.monotonic()
    for key in keys:
        attempts, expires_at = _FALLBACK_ATTEMPTS.get(key, (0, 0.0))
        if expires_at <= now:
            _FALLBACK_ATTEMPTS.pop(key, None)
            continue
        if attempts >= settings.login_rate_limit_attempts:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed login attempts")


def _record_fallback_failure(key: str, settings: Settings) -> None:
    now = time.monotonic()
    attempts, expires_at = _FALLBACK_ATTEMPTS.get(key, (0, 0.0))
    if expires_at <= now:
        attempts = 0
        expires_at = now + settings.login_rate_limit_window_seconds
    _FALLBACK_ATTEMPTS[key] = (attempts + 1, expires_at)
