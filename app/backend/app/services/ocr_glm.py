from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import base64
import io
import logging
import mimetypes
from pathlib import Path
import tempfile
import threading
from typing import Protocol

import httpx
from PIL import Image

from app.config import Settings, get_settings
from app.services.prompt_loader import PromptLoader, RenderedPrompt

logger = logging.getLogger(__name__)
_PP_OCR_PIPELINE_CACHE: dict[tuple[str, str, str], object] = {}
_PP_OCR_PIPELINE_LOCK = threading.Lock()


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
        mime_type, data = _image_data_for_llama(path)
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


class PaddleVLLlamaCppOCRProvider:
    """PaddleOCR-VL adapter for llama.cpp OpenAI-compatible multimodal server."""

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
        mime_type, data = _image_data_for_llama(path)
        payload = {
            "model": self.settings.paddle_vl_model_name,
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
        url = llama_chat_completions_url(self.settings.paddle_vl_llamacpp_base_url)
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
            raise OCRProviderError(f"PaddleOCR-VL request timed out after {self.settings.llm_request_timeout_seconds}s") from exc
        except httpx.HTTPStatusError as exc:
            raise OCRProviderError(f"PaddleOCR-VL request failed with HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise OCRProviderError(f"PaddleOCR-VL request failed: {exc}") from exc
        except ValueError as exc:
            raise OCRProviderError("PaddleOCR-VL returned invalid JSON") from exc

        choices = raw.get("choices") or []
        if not choices:
            raise OCRProviderError("PaddleOCR-VL returned no choices")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise OCRProviderError("PaddleOCR-VL returned empty text")
        return OCRResult(
            text=text,
            raw_response={"provider": "paddle_vl", "raw": raw},
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            model_role="paddleocr_vl",
            model_endpoint=self.settings.paddle_vl_llamacpp_base_url,
            model_name=self.settings.paddle_vl_model_name,
            model_response_text=text,
        )

    def _validate_multimodal_config(self) -> None:
        if not str(self.settings.paddle_vl_mmproj_path or "").strip():
            raise OCRProviderError("PaddleOCR-VL multimodal configuration error: PADDLE_VL_MMPROJ_PATH is empty")
        model_ids = list_llama_model_ids(self.settings.paddle_vl_llamacpp_base_url, timeout_s=5.0)
        configured_names = {self.settings.paddle_vl_model_name}
        path = Path(self.settings.paddle_vl_model_path)
        if path.suffix.lower() == ".gguf":
            configured_names.add(path.stem)
        if model_ids and not configured_names.intersection(model_ids):
            raise OCRProviderError(
                "PaddleOCR-VL model configuration error: "
                f"configured model '{self.settings.paddle_vl_model_name}' is not in /v1/models ({', '.join(model_ids)})"
            )


def _image_data_for_llama(path: Path) -> tuple[str, str]:
    # Explicit fallback for image formats that Python's mimetypes may miss in containers.
    image_mime_fallback = {
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime_type = mimetypes.guess_type(path.name)[0]
    if not mime_type:
        mime_type = image_mime_fallback.get(path.suffix.lower(), "image/png")
    supported_formats = {"image/png", "image/jpeg"}
    if mime_type not in supported_formats:
        try:
            logger.info("Converting %s from %s to PNG for llama.cpp compatibility", path.name, mime_type)
            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return "image/png", base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as exc:
            raise OCRProviderError(
                f"Failed to convert image {path.name} from {mime_type} to PNG: {exc}"
            ) from exc
    return mime_type, base64.b64encode(path.read_bytes()).decode("ascii")


class PPOCRv6Provider:
    """Fast/simple OCR provider backed by PaddleOCR PP-OCRv6 via ONNX Runtime."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract_text(self, file_path: str) -> OCRResult:
        path = Path(file_path)
        if not path.exists():
            raise OCRProviderError(f"File not found: {file_path}")
        pipeline = self._pipeline()
        with _paddle_compatible_image_path(path) as input_path:
            try:
                results = pipeline.predict(str(input_path))
            except Exception as exc:  # noqa: BLE001
                raise OCRProviderError(f"PP-OCRv6 request failed: {exc}") from exc
        page_results = [_ppocr_result_summary(result) for result in results]
        texts: list[str] = []
        scores: list[float] = []
        for result in page_results:
            rec_texts = result.get("rec_texts") or []
            rec_scores = result.get("rec_scores") or []
            texts.extend(str(item).strip() for item in rec_texts if str(item).strip())
            for score in rec_scores:
                try:
                    scores.append(float(score))
                except (TypeError, ValueError):
                    pass
        text = "\n".join(texts).strip()
        if not text:
            raise OCRProviderError("PP-OCRv6 returned empty text")
        tier = self.settings.ppocrv6_tier
        engine = self.settings.ppocrv6_engine
        return OCRResult(
            text=text,
            raw_response={
                "provider": "ppocrv6",
                "tier": tier,
                "engine": engine,
                "device": self.settings.ppocrv6_device,
                "average_score": sum(scores) / len(scores) if scores else None,
                "raw_results": page_results,
            },
            prompt_name="ppocrv6_fast_ocr",
            prompt_version="ppocrv6-3.7.0",
            model_role="ppocrv6_fast_ocr",
            model_endpoint="local",
            model_name=f"PP-OCRv6_{tier}_{engine}",
            model_response_text=text,
        )

    def _pipeline(self):
        tier = self.settings.ppocrv6_tier
        engine = self.settings.ppocrv6_engine
        device = self.settings.ppocrv6_device
        key = (tier, engine, device)
        with _PP_OCR_PIPELINE_LOCK:
            cached = _PP_OCR_PIPELINE_CACHE.get(key)
            if cached is not None:
                return cached
            try:
                from paddleocr import PaddleOCR
            except Exception as exc:  # noqa: BLE001
                raise OCRProviderError("PP-OCRv6 runtime is not installed") from exc
            pipeline = PaddleOCR(
                            text_detection_model_name=f"PP-OCRv6_{tier}_det",
                text_recognition_model_name=f"PP-OCRv6_{tier}_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=device,
                engine=engine,
            )
            _PP_OCR_PIPELINE_CACHE[key] = pipeline
            return pipeline


@contextmanager
def _paddle_compatible_image_path(path: Path):
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
        yield path
        return
    tmp_name: str | None = None
    try:
        with Image.open(path) as img:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_name = tmp.name
                img.convert("RGB").save(tmp, format="PNG")
        yield Path(tmp_name)
    except Exception as exc:  # noqa: BLE001
        raise OCRProviderError(f"Failed to convert image {path.name} for PP-OCRv6: {exc}") from exc
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)


def _ppocr_result_to_dict(result: object) -> dict:
    try:
        data = dict(result)  # PaddleOCR result objects behave like mappings.
    except Exception:  # noqa: BLE001
        data = {"raw": repr(result)}
    return _to_jsonable(data)


def _ppocr_result_summary(result: object) -> dict:
    """Return a compact JSON-safe PP-OCR result.

    PaddleOCR result objects can contain very large image/box tensors. Storing the
    full mapping in PostgreSQL JSONB can exceed the JSONB per-array limit. Keep
    only the recognized text, scores, and lightweight counts needed for traces.
    """
    try:
        data = dict(result)
    except Exception:  # noqa: BLE001
        return {"raw_repr": repr(result)[:1000]}
    rec_texts = _to_jsonable(data.get("rec_texts") or [])
    rec_scores = _to_jsonable(data.get("rec_scores") or [])
    rec_boxes = data.get("rec_boxes")
    if rec_boxes is None:
        rec_boxes = data.get("dt_polys")
    if rec_boxes is None:
        rec_boxes = []
    try:
        box_count = len(rec_boxes)
    except TypeError:
        box_count = None
    return {
        "rec_texts": rec_texts[:500] if isinstance(rec_texts, list) else rec_texts,
        "rec_scores": rec_scores[:500] if isinstance(rec_scores, list) else rec_scores,
        "text_count": len(rec_texts) if isinstance(rec_texts, list) else None,
        "box_count": box_count,
    }


def _to_jsonable(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


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


def build_ocr_provider(settings: Settings | None = None, provider_name: str | None = None) -> OCRProvider:
    settings = settings or get_settings()
    selected = provider_name or settings.ocr_provider
    if selected == "glm":
        return GLMLlamaCppOCRProvider(settings)
    if selected == "paddle_vl":
        return PaddleVLLlamaCppOCRProvider(settings)
    if selected == "ppocrv6":
        return PPOCRv6Provider(settings)
    return FakeOCRProvider()
