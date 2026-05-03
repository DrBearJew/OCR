from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.ocr_glm import llama_chat_completions_url, llama_health_urls
from app.services.prompt_loader import PromptLoader, RenderedPrompt


logger = logging.getLogger(__name__)


class QwenProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class QwenRefinement:
    raw_text: str
    raw_response: dict[str, Any]
    prompt: RenderedPrompt
    endpoint: str
    model: str


class QwenLlamaCppProvider:
    """Qwen text-reasoning adapter for an external llama.cpp server."""

    def __init__(
        self,
        settings: Settings | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.prompt_loader = prompt_loader or PromptLoader(settings=self.settings)

    def is_reachable(self) -> bool:
        for url in llama_health_urls(self.settings.qwen_llamacpp_base_url):
            try:
                response = httpx.get(url, timeout=min(3.0, self.settings.llm_request_timeout_seconds))
                if response.status_code < 500:
                    return True
            except httpx.HTTPError:
                continue
        return False

    def refine_metadata(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "custom_field_prompt.tmpl",
            {
                "Language": payload.get("language", "German"),
                "Title": payload.get("title", ""),
                "CreatedDate": payload.get("created_date", ""),
                "Content": payload.get("ocr_text", ""),
                "DocumentType": payload.get("collection_name", ""),
                "CustomFieldsXML": payload.get("custom_fields_xml", ""),
            },
        )
        return self._chat(prompt, role_name="refinement")

    def generate_metadata_candidates(self, payload: dict[str, Any]) -> QwenRefinement:
        """Run Qwen as the text-reasoning metadata brain after OCR.

        This is the primary structured call. Smaller paperless-gpt style helpers
        below stay available for targeted/debug workflows, but normal processing
        should prefer this one coherent JSON candidate prompt.
        """
        prompt = self.prompt_loader.render(
            "secondbrain_metadata_prompt.tmpl",
            {
                "Collection": payload.get("collection_name", ""),
                "Title": payload.get("title", ""),
                "CollectionSchema": _json_for_prompt(payload.get("collection_schema") or {}),
                "TitleRule": _json_for_prompt(payload.get("title_rule") or {}),
                "CustomFields": _json_for_prompt(payload.get("custom_fields") or []),
                "DeterministicMetadata": _json_for_prompt(payload.get("deterministic_metadata") or {}),
                "ManualLockedFields": _json_for_prompt(payload.get("manual_locked_fields") or {}),
                "SimilarDocuments": _json_for_prompt(payload.get("similar_documents") or []),
                "ProcessingOptions": _json_for_prompt(payload.get("processing_options") or {}),
                "OcrText": payload.get("ocr_text", ""),
            },
        )
        return self._chat(prompt, role_name="metadata candidates")

    def extract_correspondent(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "correspondent_prompt.tmpl",
            {
                "Content": payload.get("ocr_text", ""),
                "DocumentType": payload.get("collection_name", ""),
                "Title": payload.get("title", ""),
            },
        )
        return self._chat(prompt, role_name="correspondent extraction")

    def extract_created_date(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "created_date_prompt.tmpl",
            {
                "Content": payload.get("ocr_text", ""),
                "DocumentType": payload.get("collection_name", ""),
                "Title": payload.get("title", ""),
            },
        )
        return self._chat(prompt, role_name="created date extraction")

    def extract_document_type(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "document_type_prompt.tmpl",
            {
                "Content": payload.get("ocr_text", ""),
                "Title": payload.get("title", ""),
            },
        )
        return self._chat(prompt, role_name="document type classification")

    def extract_custom_fields(self, payload: dict[str, Any]) -> QwenRefinement:
        return self.refine_metadata(payload)

    def analyze_adhoc(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "adhoc-analysis_prompt.tmpl",
            {
                "Question": payload.get("question", ""),
                "Documents": _json_for_prompt(payload.get("documents") or []),
                "Context": _json_for_prompt(payload.get("context") or {}),
            },
        )
        return self._chat(prompt, role_name="ad hoc analysis")

    def enrich_metadata(self, payload: dict[str, Any]) -> QwenRefinement:
        prompt = self.prompt_loader.render(
            "secondbrain_metadata_prompt.tmpl",
            {
                "Collection": payload.get("collection_name", ""),
                "Title": payload.get("title", ""),
                "DeterministicMetadata": _json_for_prompt(payload.get("deterministic_metadata") or {}),
                "SimilarDocuments": _json_for_prompt(payload.get("similar_documents") or []),
                "OcrText": payload.get("ocr_text", ""),
            },
        )
        return self._chat(prompt, role_name="secondbrain enrichment")

    def _chat(self, prompt: RenderedPrompt, *, role_name: str) -> QwenRefinement:
        body = {
            "model": self.settings.qwen_model_name,
            "messages": [{"role": "user", "content": prompt.text}],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        url = llama_chat_completions_url(self.settings.qwen_llamacpp_base_url)
        try:
            response = httpx.post(
                url,
                json=body,
                timeout=self.settings.llm_request_timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.HTTPError as exc:
            raise QwenProviderError(f"Qwen request failed: {exc}") from exc
        except ValueError as exc:
            raise QwenProviderError("Qwen returned invalid JSON") from exc

        choices = raw.get("choices") or []
        message = choices[0].get("message") if choices else {}
        text = str((message or {}).get("content") or "").strip()
        logger.info("Qwen %s completed prompt=%s model=%s", role_name, prompt.name, self.settings.qwen_model_name)
        return QwenRefinement(
            raw_text=text,
            raw_response=raw,
            prompt=prompt,
            endpoint=self.settings.qwen_llamacpp_base_url,
            model=self.settings.qwen_model_name,
        )


class DisabledQwenProvider:
    def is_reachable(self) -> bool:
        return False

    def refine_metadata(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen metadata refinement is disabled")

    def generate_metadata_candidates(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen metadata candidates are disabled")

    def extract_correspondent(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen correspondent extraction is disabled")

    def extract_created_date(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen created date extraction is disabled")

    def extract_document_type(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen document type extraction is disabled")

    def extract_custom_fields(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen custom field extraction is disabled")

    def analyze_adhoc(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen ad hoc analysis is disabled")

    def enrich_metadata(self, payload: dict[str, Any]) -> QwenRefinement:
        raise QwenProviderError("Qwen metadata enrichment is disabled")


def parse_json_suggestion(raw_text: str) -> Any:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        candidate = _extract_json_region(text)
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        return {"text": raw_text}


def _extract_json_region(text: str) -> str | None:
    starts = [index for index in [text.find("{"), text.find("[")] if index >= 0]
    if not starts:
        return None
    start = min(starts)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    end = text.rfind(closer)
    if end <= start:
        return None
    return text[start : end + 1]


def build_qwen_provider(settings: Settings | None = None) -> QwenLlamaCppProvider | DisabledQwenProvider:
    settings = settings or get_settings()
    if not settings.llm_metadata_refinement_enabled:
        return DisabledQwenProvider()
    return QwenLlamaCppProvider(settings)


def _json_for_prompt(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)
