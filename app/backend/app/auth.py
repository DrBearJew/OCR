from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import AppSetting


bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"
ADMIN_CREDENTIALS_KEY = "admin_credentials"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def validate_username(username: str) -> str:
    cleaned = username.strip()
    if not USERNAME_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username must be 1–64 characters using letters, digits, '.', '_', '@', or '-'",
        )
    return cleaned


def validate_new_password(password: str) -> str:
    if len(password) < 8 or len(password) > 128 or not password.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be between 8 and 128 characters",
        )
    if password.strip().lower() == "admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please choose a stronger password than 'admin'",
        )
    return password


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password_hash(password: str, encoded: str) -> bool:
    try:
        scheme, n_str, r_str, p_str, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_str),
            r=int(r_str),
            p=int(p_str),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _session_or_none(db: Any) -> Session | None:
    return db if isinstance(db, Session) else None


def get_auth_store(db: Any) -> dict[str, Any] | None:
    """Return normalized DB auth store ({accounts, allow_registration, setup_completed}) or None."""
    session = _session_or_none(db)
    if session is None:
        return None
    row = session.get(AppSetting, ADMIN_CREDENTIALS_KEY)
    if row is None or not isinstance(row.value_json, dict):
        return None
    data = row.value_json
    accounts: list[dict[str, Any]] = []
    raw_accounts = data.get("accounts")
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if (
                isinstance(item, dict)
                and isinstance(item.get("username"), str)
                and item["username"]
                and isinstance(item.get("password_hash"), str)
                and item["password_hash"]
            ):
                accounts.append(
                    {
                        "username": item["username"],
                        "password_hash": item["password_hash"],
                        "password_version": int(item.get("password_version", 1)),
                    }
                )
    elif (
        isinstance(data.get("username"), str)
        and data["username"]
        and isinstance(data.get("password_hash"), str)
        and data["password_hash"]
    ):
        accounts.append(
            {
                "username": data["username"],
                "password_hash": data["password_hash"],
                "password_version": int(data.get("password_version", 1)),
            }
        )
    if not accounts:
        return None
    return {
        "accounts": accounts,
        "allow_registration": bool(data.get("allow_registration", False)),
        "setup_completed": bool(data.get("setup_completed", True)),
    }


def ensure_auth_store(db: Session, settings: Settings) -> dict[str, Any]:
    """Return existing DB auth store, or materialize the .env admin account into a new store dict."""
    existing = get_auth_store(db)
    if existing is not None:
        return existing
    return {
        "accounts": [
            {
                "username": settings.admin_username,
                "password_hash": hash_password(settings.admin_password),
                "password_version": 0,
            }
        ],
        "allow_registration": False,
        "setup_completed": True,
    }


def save_auth_store(db: Session, store: dict[str, Any]) -> None:
    row = db.get(AppSetting, ADMIN_CREDENTIALS_KEY)
    payload = {
        "accounts": list(store["accounts"]),
        "allow_registration": bool(store.get("allow_registration", False)),
        "setup_completed": True,
    }
    if row is None:
        db.add(AppSetting(key=ADMIN_CREDENTIALS_KEY, value_json=payload))
    else:
        row.value_json = payload


def find_account(accounts: list[dict[str, Any]], username: str) -> dict[str, Any] | None:
    target = username.lower()
    for account in accounts:
        if account["username"].lower() == target:
            return account
    return None


def is_initial_setup_needed(db: Any, settings: Settings) -> bool:
    return bool(settings.allow_initial_setup) and get_auth_store(db) is None


def is_registration_allowed(db: Any, settings: Settings) -> bool:
    store = get_auth_store(db)
    if store is None:
        return False
    return bool(store.get("allow_registration", False))


def verify_admin_credentials(
    db: Any,
    settings: Settings,
    username: str,
    password: str,
) -> tuple[bool, str, int]:
    store = get_auth_store(db)
    if store is not None:
        for account in store["accounts"]:
            if secrets.compare_digest(username, account["username"]):
                if verify_password_hash(password, account["password_hash"]):
                    return True, account["username"], int(account.get("password_version", 1))
                return False, account["username"], int(account.get("password_version", 1))
        return False, username, 0
    user_ok = secrets.compare_digest(username, settings.admin_username)
    pass_ok = secrets.compare_digest(password, settings.admin_password)
    return (user_ok and pass_ok), settings.admin_username, 0


def _verify_active_identity(db: Any, settings: Settings, subject: str, token_pv: int) -> bool:
    store = get_auth_store(db)
    if store is not None:
        for account in store["accounts"]:
            if secrets.compare_digest(subject, account["username"]):
                return token_pv == int(account.get("password_version", 1))
        return False
    return secrets.compare_digest(subject, settings.admin_username) and token_pv == 0


def create_access_token(
    subject: str,
    settings: Settings | None = None,
    password_version: int = 0,
) -> str:
    settings = settings or get_settings()
    issued_at = datetime.now(timezone.utc)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": subject,
        "pv": password_version,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def require_admin(
    cookie_token: str | None = Cookie(default=None, alias="dokocr_session"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
    db: Session | None = Depends(get_db),
) -> str:
    token = credentials.credentials if credentials is not None else cookie_token
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require_iat": True, "require_nbf": True, "require_exp": True},
        )
        subject = payload.get("sub")
        token_pv = int(payload.get("pv", 0))
    except (JWTError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if not isinstance(subject, str) or not _verify_active_identity(db, settings, subject, token_pv):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return subject
