from __future__ import annotations

from fastapi import HTTPException, Response
from redis.exceptions import RedisError
from starlette.requests import Request

from app.api import auth as auth_api
from app.auth import create_access_token, require_admin
from app.config import Settings, validate_production_settings
from app.schemas import LoginRequest
from app.models import HookKind, HookStage, ProcessingHook
from app.services.hooks import execute_hook


class FakeRedis:
    def __init__(self, initial: int = 0) -> None:
        self.values: dict[str, int] = {}
        self.initial = initial
        self.deleted = False

    def get(self, key: str) -> str | None:
        value = self.values.get(key, self.initial)
        return str(value) if value else None

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, self.initial) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        return None

    def delete(self, key: str) -> None:
        self.deleted = True


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})


def test_login_sets_httponly_cookie_and_clears_rate_limit(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(auth_api, "_redis", lambda settings: fake)
    settings = Settings(admin_username="admin", admin_password="secret", secret_key="test-secret")
    response = Response()

    token = auth_api.login(LoginRequest(username="admin", password="secret"), _request(), response, settings)

    assert token.access_token
    assert "httponly" in response.headers["set-cookie"].lower()
    assert fake.deleted is True


def test_login_rate_limit_blocks_repeated_failures(monkeypatch) -> None:
    monkeypatch.setattr(auth_api, "_redis", lambda settings: FakeRedis(initial=5))
    settings = Settings(admin_username="admin", admin_password="secret", secret_key="test-secret")

    try:
        auth_api.login(LoginRequest(username="admin", password="wrong"), _request(), Response(), settings)
    except HTTPException as exc:
        assert exc.status_code == 429
    else:  # pragma: no cover
        raise AssertionError("rate-limited login was accepted")


def test_login_rate_limit_uses_fallback_when_redis_is_down(monkeypatch) -> None:
    def broken_redis(settings):
        raise RedisError("down")

    auth_api._FALLBACK_ATTEMPTS.clear()
    monkeypatch.setattr(auth_api, "_redis", broken_redis)
    settings = Settings(admin_username="admin", admin_password="secret", secret_key="test-secret", login_rate_limit_attempts=1)
    request = _request()

    try:
        auth_api.login(LoginRequest(username="wrong", password="bad"), request, Response(), settings)
    except HTTPException as exc:
        assert exc.status_code == 401
    try:
        auth_api.login(LoginRequest(username="another", password="bad"), request, Response(), settings)
    except HTTPException as exc:
        assert exc.status_code == 429
    else:  # pragma: no cover
        raise AssertionError("IP fallback rate limit was bypassed")


def test_production_settings_reject_default_secret_and_password() -> None:
    for settings in [
        Settings(environment="production", admin_password="admin", secret_key="x" * 40, cors_origins="https://example.test", frontend_origin="https://example.test"),
        Settings(environment="production", admin_password="secret", secret_key="change-me-before-real-use", cors_origins="https://example.test", frontend_origin="https://example.test"),
    ]:
        try:
            validate_production_settings(settings)
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("unsafe production settings were accepted")


def test_jwt_requires_issuer_audience_and_time_claims() -> None:
    settings = Settings(admin_username="admin", admin_password="secret", secret_key="test-secret")
    token = create_access_token("admin", settings)
    assert require_admin(cookie_token=token, credentials=None, settings=settings) == "admin"

    import jose.jwt

    bad = jose.jwt.encode({"sub": "admin"}, settings.secret_key, algorithm="HS256")
    try:
        require_admin(cookie_token=bad, credentials=None, settings=settings)
    except HTTPException as exc:
        assert exc.status_code == 401
    else:  # pragma: no cover
        raise AssertionError("token without required claims was accepted")


def test_command_hooks_reject_shell_and_allow_argv(monkeypatch) -> None:
    settings = Settings(command_hooks_enabled=True, command_hooks_allowed_commands="python")
    monkeypatch.setattr("app.services.hooks.get_settings", lambda: settings)
    shell_hook = ProcessingHook(name="bad", stage=HookStage.post_consume, hook_kind=HookKind.command, command="python --version; whoami")
    try:
        execute_hook(shell_hook)
    except ValueError as exc:
        assert "metacharacters" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("shell command hook was accepted")


def test_webhook_hooks_require_allowlist_and_block_private(monkeypatch) -> None:
    hook = ProcessingHook(name="web", stage=HookStage.post_consume, hook_kind=HookKind.webhook, webhook_url="http://localhost:8000/hook")
    monkeypatch.setattr("app.services.hooks.get_settings", lambda: Settings(hook_webhook_allowed_hosts=""))
    try:
        execute_hook(hook)
    except ValueError as exc:
        assert "ALLOWED_HOSTS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("webhook without allowlist was accepted")

    monkeypatch.setattr("app.services.hooks.get_settings", lambda: Settings(hook_webhook_allowed_hosts="localhost"))
    try:
        execute_hook(hook)
    except ValueError as exc:
        assert "blocked address" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("private webhook target was accepted")
