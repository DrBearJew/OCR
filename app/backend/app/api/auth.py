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
    ensure_auth_store,
    find_account,
    get_auth_store,
    hash_password,
    is_initial_setup_needed,
    is_registration_allowed,
    require_admin,
    save_auth_store,
    validate_new_password,
    validate_username,
    verify_admin_credentials,
)
from app.config import Settings, get_settings
from app.db import get_db
from app.models import AppSetting
from app.schemas import (
    AccountSummary,
    AuthAccountsResponse,
    AuthMeResponse,
    AuthStatusResponse,
    ChangeCredentialsRequest,
    ChangeCredentialsResponse,
    InitialSetupRequest,
    LoginRequest,
    RegisterAccountRequest,
    RegistrationSettingRequest,
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
        allow_registration=False if needs_setup else is_registration_allowed(db, settings),
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
            "accounts": [
                {
                    "username": username,
                    "password_hash": hash_password(password),
                    "password_version": 1,
                }
            ],
            "allow_registration": False,
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


@router.post("/register", response_model=TokenResponse)
def register_account(
    payload: RegisterAccountRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    _check_rate_limit(request, "__register__", settings)
    if not is_registration_allowed(db, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account self-registration is disabled by the administrator",
        )
    store = get_auth_store(db)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account self-registration is disabled by the administrator",
        )
    username = validate_username(payload.username)
    password = validate_new_password(payload.password)
    if find_account(store["accounts"], username) is not None:
        _record_failed_login(request, "__register__", settings)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this username already exists",
        )
    store["accounts"].append(
        {
            "username": username,
            "password_hash": hash_password(password),
            "password_version": 1,
        }
    )
    save_auth_store(db, store)
    db.commit()
    _clear_failed_login(request, "__register__", settings)
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


@router.get("/accounts", response_model=AuthAccountsResponse)
def list_accounts(
    current_user: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthAccountsResponse:
    store = get_auth_store(db)
    if store is None:
        return AuthAccountsResponse(
            current_username=current_user,
            allow_registration=False,
            accounts=[AccountSummary(username=settings.admin_username)],
        )
    return AuthAccountsResponse(
        current_username=current_user,
        allow_registration=bool(store.get("allow_registration", False)),
        accounts=[AccountSummary(username=item["username"]) for item in store["accounts"]],
    )


@router.post("/accounts", response_model=AuthAccountsResponse)
def create_account(
    payload: RegisterAccountRequest,
    current_user: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthAccountsResponse:
    username = validate_username(payload.username)
    password = validate_new_password(payload.password)
    store = ensure_auth_store(db, settings)
    if find_account(store["accounts"], username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this username already exists",
        )
    store["accounts"].append(
        {
            "username": username,
            "password_hash": hash_password(password),
            "password_version": 1,
        }
    )
    save_auth_store(db, store)
    db.commit()
    return AuthAccountsResponse(
        current_username=current_user,
        allow_registration=bool(store.get("allow_registration", False)),
        accounts=[AccountSummary(username=item["username"]) for item in store["accounts"]],
    )


@router.delete("/accounts/{username}", response_model=AuthAccountsResponse)
def delete_account(
    username: str,
    current_user: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthAccountsResponse:
    store = ensure_auth_store(db, settings)
    if username.lower() == current_user.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove the currently signed-in account",
        )
    remaining = [item for item in store["accounts"] if item["username"].lower() != username.lower()]
    if len(remaining) == len(store["accounts"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not remaining:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one account must remain",
        )
    store["accounts"] = remaining
    save_auth_store(db, store)
    db.commit()
    return AuthAccountsResponse(
        current_username=current_user,
        allow_registration=bool(store.get("allow_registration", False)),
        accounts=[AccountSummary(username=item["username"]) for item in store["accounts"]],
    )


@router.patch("/registration", response_model=AuthAccountsResponse)
def update_registration_setting(
    payload: RegistrationSettingRequest,
    current_user: str = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthAccountsResponse:
    store = ensure_auth_store(db, settings)
    store["allow_registration"] = bool(payload.allow_registration)
    save_auth_store(db, store)
    db.commit()
    return AuthAccountsResponse(
        current_username=current_user,
        allow_registration=bool(store["allow_registration"]),
        accounts=[AccountSummary(username=item["username"]) for item in store["accounts"]],
    )


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
    store = ensure_auth_store(db, settings)
    existing = find_account(store["accounts"], new_username)
    if existing is not None and existing["username"].lower() != current_user.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another account already uses this username",
        )
    next_pv = max(current_pv, 0) + 1
    updated = False
    for account in store["accounts"]:
        if account["username"].lower() == current_user.lower():
            account["username"] = new_username
            account["password_hash"] = hash_password(new_password)
            account["password_version"] = next_pv
            updated = True
            break
    if not updated:
        store["accounts"].append(
            {
                "username": new_username,
                "password_hash": hash_password(new_password),
                "password_version": next_pv,
            }
        )
    save_auth_store(db, store)
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
