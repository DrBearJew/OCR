from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings, get_settings


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Rule file must be a mapping: {path}")
    return payload


@lru_cache(maxsize=1)
def get_collection_rules() -> dict[str, Any]:
    settings = get_settings()
    return _read_yaml(settings.rules_dir / "collection_rules.yaml")


@lru_cache(maxsize=1)
def get_ocr_rules() -> dict[str, Any]:
    settings = get_settings()
    return _read_yaml(settings.rules_dir / "ocr_rules.yaml")


def validate_title_for_collection(collection_name: str, title: str) -> bool:
    import re

    collections = get_collection_rules().get("collections", {})
    rules = collections.get(collection_name) or collections.get(collection_name.strip())
    if not isinstance(rules, dict):
        return True
    regex = rules.get("title_regex")
    if not regex:
        return True
    return bool(re.match(str(regex), title or ""))

