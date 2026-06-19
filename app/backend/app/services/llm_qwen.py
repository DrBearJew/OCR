from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.model_gateway_lock import ModelGatewayLockTimeout, exclusive_model_gateway_lock
from app.services.ocr_glm import llama_chat_completions_url, llama_health_urls
from app.services.prompt_loader import PromptLoader, RenderedPrompt


logger = logging.getLogger(__name__)

QWEN_METADATA_BASE_MAX_TOKENS = 2048
QWEN_METADATA_PER_CUSTOM_FIELD_TOKENS = 96
QWEN_METADATA_OCR_TEXT_BASE_CHARS = 4_000
QWEN_METADATA_OCR_TEXT_STEP_CHARS = 4_000
QWEN_METADATA_PER_OCR_TEXT_STEP_TOKENS = 512
QWEN_METADATA_MAX_TOKENS = 4096


QWEN_THINKING_DISABLED_SYSTEM_PROMPT = (
    "<|think_off|>\n"
    "You are a precise metadata extraction engine. Return only the requested final answer "
    "in assistant message content. Do not put output in reasoning_content."
)


QWEN_METADATA_THINKING_SYSTEM_PROMPT = (
    "You are a precise metadata extraction engine. You may reason internally if the runtime "
    "supports a private reasoning channel, but the final assistant message content must contain "
    "only the requested final answer. Do not include reasoning, analysis, or chain-of-thought "
    "in assistant message content."
)


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
        max_tokens = qwen_metadata_max_tokens_for_payload(payload, settings_max_tokens=int(self.settings.llm_max_tokens))
        return self._chat(prompt, role_name="metadata candidates", json_only=True, max_tokens=max_tokens)

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

    def _chat(self, prompt: RenderedPrompt, *, role_name: str, json_only: bool = False, max_tokens: int | None = None) -> QwenRefinement:
        body = {
            "model": self.settings.qwen_model_name,
            "messages": [
                {"role": "system", "content": self._system_prompt(json_only=json_only)},
                {"role": "user", "content": prompt.text},
            ],
            "temperature": self.settings.llm_temperature,
            "max_tokens": max_tokens or min(int(self.settings.llm_max_tokens), QWEN_METADATA_BASE_MAX_TOKENS),
        }
        if json_only:
            body["response_format"] = {"type": "json_object"}
        url = llama_chat_completions_url(self.settings.qwen_llamacpp_base_url)
        try:
            with exclusive_model_gateway_lock(
                "qwen:metadata",
                settings=self.settings,
                wait_timeout_seconds=max(self.settings.ocr_task_time_limit, self.settings.llm_request_timeout_seconds),
                lease_seconds=max(self.settings.llm_request_timeout_seconds + 60, 180),
            ):
                raw = self._post_chat(url, body)
                if json_only and not _chat_content(raw) and body.get("response_format"):
                    retry_messages = [dict(message) for message in body["messages"]]
                    retry_messages[-1]["content"] = (
                        str(retry_messages[-1]["content"]).rstrip()
                        + "\n\nReturn one valid compact JSON object now. Do not return an empty answer."
                    )
                    retry_body = {**body, "messages": retry_messages}
                    raw = self._post_chat(url, retry_body)
        except httpx.HTTPStatusError as exc:
            if json_only and body.get("response_format") and exc.response.status_code in {400, 422}:
                fallback_body = {key: value for key, value in body.items() if key != "response_format"}
                try:
                    with exclusive_model_gateway_lock(
                        "qwen:metadata",
                        settings=self.settings,
                        wait_timeout_seconds=max(self.settings.ocr_task_time_limit, self.settings.llm_request_timeout_seconds),
                        lease_seconds=max(self.settings.llm_request_timeout_seconds + 60, 180),
                    ):
                        raw = self._post_chat(url, fallback_body)
                except httpx.HTTPError as fallback_exc:
                    raise QwenProviderError(f"Qwen request failed after response_format fallback: {fallback_exc}") from fallback_exc
                except ValueError as fallback_exc:
                    raise QwenProviderError("Qwen fallback returned invalid JSON") from fallback_exc
                except ModelGatewayLockTimeout as fallback_exc:
                    raise QwenProviderError(f"Qwen model gateway lock timeout after response_format fallback: {fallback_exc}") from fallback_exc
            else:
                raise QwenProviderError(f"Qwen request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise QwenProviderError(f"Qwen request failed: {exc}") from exc
        except ValueError as exc:
            raise QwenProviderError("Qwen returned invalid JSON") from exc
        except ModelGatewayLockTimeout as exc:
            raise QwenProviderError(f"Qwen model gateway lock timeout: {exc}") from exc

        text = _chat_content(raw)
        logger.info("Qwen %s completed prompt=%s model=%s", role_name, prompt.name, self.settings.qwen_model_name)
        return QwenRefinement(
            raw_text=text,
            raw_response=raw,
            prompt=prompt,
            endpoint=self.settings.qwen_llamacpp_base_url,
            model=self.settings.qwen_model_name,
        )

    def _system_prompt(self, *, json_only: bool) -> str:
        if json_only and self.settings.qwen_metadata_thinking_enabled:
            return QWEN_METADATA_THINKING_SYSTEM_PROMPT
        return QWEN_THINKING_DISABLED_SYSTEM_PROMPT

    def _post_chat(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            url,
            json=body,
            timeout=self.settings.llm_request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


def qwen_metadata_max_tokens_for_payload(payload: dict[str, Any], *, settings_max_tokens: int) -> int:
    custom_field_count = _custom_field_count(payload.get("custom_fields"))
    requested = (
        QWEN_METADATA_BASE_MAX_TOKENS
        + (custom_field_count * QWEN_METADATA_PER_CUSTOM_FIELD_TOKENS)
        + _ocr_text_budget_tokens(payload.get("ocr_text"))
    )
    return max(1, min(int(settings_max_tokens), QWEN_METADATA_MAX_TOKENS, requested))


def _ocr_text_budget_tokens(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    extra_chars = max(0, len(value) - QWEN_METADATA_OCR_TEXT_BASE_CHARS)
    if extra_chars <= 0:
        return 0
    steps = (extra_chars + QWEN_METADATA_OCR_TEXT_STEP_CHARS - 1) // QWEN_METADATA_OCR_TEXT_STEP_CHARS
    return steps * QWEN_METADATA_PER_OCR_TEXT_STEP_TOKENS


def _custom_field_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return 0


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
    for candidate_text in (text, _repair_extra_string_literals_after_evidence(text)):
        try:
            return json.loads(candidate_text)
        except json.JSONDecodeError:
            first_value = _decode_first_json_value(candidate_text)
            if first_value is not None:
                return first_value
            candidate = _extract_json_region(candidate_text)
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    first_value = _decode_first_json_value(candidate)
                    if first_value is not None:
                        return first_value
                    repaired = _repair_extra_string_literals_after_evidence(candidate)
                    if repaired != candidate:
                        try:
                            return json.loads(repaired)
                        except json.JSONDecodeError:
                            first_value = _decode_first_json_value(repaired)
                            if first_value is not None:
                                return first_value
    return {"text": raw_text}


def _decode_first_json_value(text: str) -> Any | None:
    """Return the first complete JSON value when a model appends extra data.

    Qwen sometimes emits one extra closing brace before continuing with more
    top-level keys. The core metadata fields are often already inside the first
    complete object, so keeping that object is safer than discarding the whole
    response as invalid.
    """
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, (dict, list)) else None


def _repair_extra_string_literals_after_evidence(text: str) -> str:
    """Repair Qwen objects like: "evidence": "A", "B", "C".

    This is intentionally narrow. It only folds anonymous string literals that
    immediately follow an evidence property into that evidence string.
    """
    pattern = re.compile(r'"evidence"\s*:\s*"((?:[^"\\]|\\.)*)"((?:\s*,\s*"(?:[^"\\]|\\.)*")+)')

    def repl(match: re.Match[str]) -> str:
        values = [match.group(1), *re.findall(r'\s*,\s*"((?:[^"\\]|\\.)*)"', match.group(2))]
        decoded: list[str] = []
        for value in values:
            try:
                decoded.append(json.loads(f'"{value}"'))
            except json.JSONDecodeError:
                decoded.append(value)
        return '"evidence": ' + json.dumps("; ".join(item for item in decoded if item), ensure_ascii=False)

    return pattern.sub(repl, text)


def _chat_content(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    message = choices[0].get("message") if choices else {}
    return str((message or {}).get("content") or "").strip()


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
