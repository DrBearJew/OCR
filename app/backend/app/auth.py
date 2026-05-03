from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import Settings, get_settings


bearer = HTTPBearer(auto_error=False)
ALGORITHM = "HS256"


def create_access_token(subject: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    issued_at = datetime.now(timezone.utc)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": subject,
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
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if subject != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return subject
