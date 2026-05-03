from __future__ import annotations

from pathlib import Path

from app.config import Settings, get_settings


CONVERTIBLE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".eml",
    ".msg",
}


class ConverterError(RuntimeError):
    pass


def requires_converter(path: str) -> bool:
    return Path(path).suffix.lower() in CONVERTIBLE_EXTENSIONS


def ensure_convertible_allowed(path: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if requires_converter(path) and not settings.converters_enabled:
        raise ConverterError(
            "Office/email documents require optional Tika/Gotenberg converters. "
            "Set CONVERTERS_ENABLED=true and configure TIKA_BASE_URL/GOTENBERG_BASE_URL."
        )


def convert_if_needed(path: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    ensure_convertible_allowed(path, settings)
    if not requires_converter(path):
        return path
    # V1 keeps converters as an external boundary. The adapter is intentionally
    # mockable; live conversion can be added without changing ingestion flow.
    return path
