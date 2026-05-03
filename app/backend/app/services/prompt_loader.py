from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
from typing import Any

from app.config import Settings, get_settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RenderedPrompt:
    name: str
    version: str
    text: str
    path: str


class PromptLoader:
    def __init__(self, prompt_dir: Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.prompt_dir = prompt_dir or self.settings.prompt_dir

    def load(self, name: str) -> tuple[str, str, Path]:
        path = self.prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {name}")
        text = path.read_text(encoding="utf-8")
        version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        return text, version, path

    def render(self, name: str, variables: dict[str, Any] | None = None) -> RenderedPrompt:
        template, version, path = self.load(name)
        rendered = _render_go_style_template(template, variables or {})
        logger.info("Rendered prompt template=%s version=%s", name, version)
        return RenderedPrompt(name=name, version=version, text=rendered, path=str(path))


def _lookup(variables: dict[str, Any], key: str) -> Any:
    key = key.strip().lstrip(".")
    current: Any = variables
    for part in key.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part, "")
        else:
            current = getattr(current, part, "")
    return current


def _render_go_style_template(template: str, variables: dict[str, Any]) -> str:
    def replace_join(match: re.Match[str]) -> str:
        value = _lookup(variables, match.group("key"))
        if isinstance(value, (list, tuple, set)):
            return str(match.group("sep")).join(str(item) for item in value)
        return str(value or "")

    def replace_var(match: re.Match[str]) -> str:
        value = _lookup(variables, match.group("key"))
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value)
        return str(value if value is not None else "")

    rendered = re.sub(
        r"{{\s*(?P<key>\.?[A-Za-z0-9_.]+)\s*\|\s*join\s+\"(?P<sep>[^\"]*)\"\s*}}",
        replace_join,
        template,
    )
    rendered = re.sub(r"{{\s*(?P<key>\.?[A-Za-z0-9_.]+)\s*}}", replace_var, rendered)
    return rendered


def get_prompt_loader() -> PromptLoader:
    return PromptLoader()

