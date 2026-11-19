from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    ADMIN_CREDENTIALS_KEY,
    create_access_token,
    get_active_admin_identity,
    get_stored_credentials,
    hash_password,
    is_initial_setup_needed,
    require_admin,
    validate_new_password,
    validate_username,
    verify_admin_credentials,
)
from app.config import Settings, get_settings
from app.db import get_db
from app.models import AppSetting
from app.schemas import (
    AuthMeResponse,
    AuthStatusResponse,
    ChangeCredentialsRequest,
    ChangeCredentialsResponse,
    InitialSetupRequest,
    LoginRequest,
    TokenResponse,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])
_FALLBACK_ATTEMPTS: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        "dokocr_session",
        token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.get("/status", response_model=AuthStatusResponse)
def auth_status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthStatusResponse:
    needs_setup = is_initial_setup_needed(db, settings)
    return AuthStatusResponse(
        needs_setup=needs_setup,
        default_username=settings.admin_username if needs_setup else "",
    )


@router.post("/setup", response_model=TokenResponse)
def initial_setup(
    payload: InitialSetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _check_rate_limit(request, "__setup__", settings)
    if not is_initial_setup_needed(db, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial account setup is already completed or disabled",
        )
    username = validate_username(payload.username)
    password = validate_new_password(payload.password)
    row = AppSetting(
        key=ADMIN_CREDENTIALS_KEY,
        value_json={
            "username": username,
            "password_hash": hash_password(password),
            "password_version": 1,
            "setup_completed": True,
        },
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial account setup is already completed",
        )
    _clear_failed_login(request, "__setup__", settings)
    token = create_access_token(username, settings, password_version=1)
    _set_session_cookie(response, token, settings)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    db: Session | None = Depends(get_db),
) -> TokenResponse:
    _check_rate_limit(request, payload.username, settings)
    ok, active_user, active_pv = verify_admin_credentials(db, settings, payload.username, payload.password)
    if not ok:
        _record_failed_login(request, payload.username, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    _clear_failed_login(request, payload.username, settings)
    token = create_access_token(active_user, settings, password_version=active_pv)
    _set_session_cookie(response, token, settings)
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    response.delete_cookie(
        "dokocr_session",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me", response_model=AuthMeResponse)
def auth_me(
    current_user: str = Depends(require_admin),
) -> AuthMeResponse:
    return AuthMeResponse(username=current_user)


@router.post("/change-credentials", response_model=ChangeCredentialsResponse)
def change_credentials(
    payload: ChangeCredentialsRequest,
    request: Request,
    response: Response,
    current_user: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChangeCredentialsResponse:
    _check_rate_limit(request, current_user, settings)
    ok, _, current_pv = verify_admin_credentials(db, settings, current_user, payload.current_password)
    if not ok:
        _record_failed_login(request, current_user, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    new_username = validate_username(payload.new_username)
    new_password = validate_new_password(payload.new_password)
    next_pv = max(current_pv, 0) + 1
    new_value = {
        "username": new_username,
        "password_hash": hash_password(new_password),
        "password_version": next_pv,
        "setup_completed": True,
    }
    row = db.get(AppSetting, ADMIN_CREDENTIALS_KEY)
    if row is None:
        db.add(AppSetting(key=ADMIN_CREDENTIALS_KEY, value_json=new_value))
    else:
        row.value_json = new_value
    db.commit()
    _clear_failed_login(request, current_user, settings)
    token = create_access_token(new_username, settings, password_version=next_pv)
    _set_session_cookie(response, token, settings)
    return ChangeCredentialsResponse(access_token=token, username=new_username)


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
