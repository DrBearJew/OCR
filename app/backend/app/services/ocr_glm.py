from __future__ import annotations

from dataclasses import dataclass
import base64
import mimetypes
from pathlib import Path
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.services.prompt_loader import PromptLoader, RenderedPrompt


class OCRProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class OCRResult:
    text: str
    raw_response: dict
    prompt_name: str | None = None
    prompt_version: str | None = None
    model_role: str | None = None
    model_endpoint: str | None = None
    model_name: str | None = None
    model_response_text: str | None = None


class OCRProvider(Protocol):
    def extract_text(self, file_path: str) -> OCRResult:
        ...


class FakeOCRProvider:
    def extract_text(self, file_path: str) -> OCRResult:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f"Fake OCR text for {path.name}"
        return OCRResult(
            text=text,
            raw_response={"provider": "fake", "filename": path.name},
            prompt_name="fake",
            prompt_version="fake",
            model_role="fake_ocr",
            model_endpoint="local",
            model_name="fake",
            model_response_text=text,
        )


class GLMLlamaCppOCRProvider:
    """GLM OCR adapter for llama.cpp OpenAI-compatible multimodal server."""

    def __init__(
        self,
        settings: Settings | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.prompt_loader = prompt_loader or PromptLoader(settings=self.settings)

    def extract_text(self, file_path: str) -> OCRResult:
        path = Path(file_path)
        if not path.exists():
            raise OCRProviderError(f"File not found: {file_path}")
        self._validate_multimodal_config()
        prompt = self.prompt_loader.render("ocr_prompt.tmpl")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        payload = {
            "model": self.settings.glm_model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt.text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{data}"},
                        },
                    ],
                }
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        url = llama_chat_completions_url(self.settings.glm_llamacpp_base_url)
        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.settings.llm_request_timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.TimeoutException as exc:
            raise OCRProviderError(f"GLM OCR request timed out after {self.settings.llm_request_timeout_seconds}s") from exc
        except httpx.HTTPStatusError as exc:
            raise OCRProviderError(f"GLM OCR request failed with HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise OCRProviderError(f"GLM OCR request failed: {exc}") from exc
        except ValueError as exc:
            raise OCRProviderError("GLM OCR returned invalid JSON") from exc

        choices = raw.get("choices") or []
        if not choices:
            raise OCRProviderError("GLM OCR returned no choices")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise OCRProviderError("GLM OCR returned empty text")
        return OCRResult(
            text=text,
            raw_response=raw,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            model_role="glm_ocr",
            model_endpoint=self.settings.glm_llamacpp_base_url,
            model_name=self.settings.glm_model_name,
            model_response_text=text,
        )

    def _validate_multimodal_config(self) -> None:
        if not str(self.settings.glm_mmproj_path or "").strip():
            raise OCRProviderError("GLM OCR multimodal configuration error: GLM_MMPROJ_PATH is empty")
        model_ids = list_llama_model_ids(self.settings.glm_llamacpp_base_url, timeout_s=5.0)
        configured_names = {self.settings.glm_model_name}
        path = Path(self.settings.glm_model_path)
        if path.suffix.lower() == ".gguf":
            configured_names.add(path.stem)
        if model_ids and not configured_names.intersection(model_ids):
            raise OCRProviderError(
                "GLM OCR model configuration error: "
                f"configured model '{self.settings.glm_model_name}' is not in /v1/models ({', '.join(model_ids)})"
            )


def llama_chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def llama_health_urls(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    return [f"{root}/health", f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"]


def llama_models_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def list_llama_model_ids(base_url: str, *, timeout_s: float = 5.0) -> list[str]:
    try:
        response = httpx.get(llama_models_url(base_url), timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def build_ocr_provider(settings: Settings | None = None) -> OCRProvider:
    settings = settings or get_settings()
    if settings.ocr_provider == "glm":
        return GLMLlamaCppOCRProvider(settings)
    return FakeOCRProvider()
