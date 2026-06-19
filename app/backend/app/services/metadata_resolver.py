from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re
import unicodedata

from app.models import Document


CORE_FIELD_ATTRS = {
    "title": "extracted_title",
    "sender": "extracted_sender",
    "recipient": "extracted_recipient",
    "invoice_number": "extracted_invoice_number",
    "date": "extracted_date",
    "amount": "extracted_amount",
    "payment_method": "extracted_payment_method",
}

EMPTY_VALUES = {"", "NA", "N/A", "00/00", "00/00/0000"}


@dataclass(slots=True)
class MetadataCandidate:
    field: str
    value: str | None
    source: str
    confidence: int | None = None
    evidence: str | None = None
    authority: str = "fallback"
    reason: str | None = None

    def is_empty(self) -> bool:
        return is_empty_value(self.value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "authority": self.authority,
            "reason": self.reason,
        }


@dataclass(slots=True)
class MetadataResolution:
    merged: dict[str, str | None]
    sources: dict[str, dict[str, Any]]
    candidates: dict[str, list[MetadataCandidate]] = field(default_factory=dict)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "authority_order": [
                "manual_lock",
                "explicit_manual_value",
                "qwen_grounded_candidate",
                "exact_deterministic_label",
                "learned_or_similar_document_candidate",
                "weak_fallback",
                "review",
            ],
            "candidates": {
                field_name: [candidate.as_dict() for candidate in field_candidates]
                for field_name, field_candidates in self.candidates.items()
            },
            "decisions": self.decisions,
        }


def resolve_metadata_fields(
    document: Document,
    deterministic: dict[str, str | None],
    qwen_suggestion: dict[str, Any] | None = None,
    *,
    overwrite_manual_values: bool = False,
    force: bool = False,
) -> MetadataResolution:
    existing_sources = document.metadata_sources_json or {}
    locks = document.field_locks_json or {}
    normalized_qwen = normalize_qwen_suggestion(qwen_suggestion or {})
    merged: dict[str, str | None] = {}
    sources: dict[str, dict[str, Any]] = {}
    all_candidates: dict[str, list[MetadataCandidate]] = {}
    decisions: dict[str, dict[str, Any]] = {}

    for field_name, attr in CORE_FIELD_ATTRS.items():
        current = getattr(document, attr, None)
        source_info = existing_sources.get(field_name) if isinstance(existing_sources.get(field_name), dict) else {}
        current_source = source_info.get("source")
        locked = bool(locks.get(field_name)) or (document.metadata_locked and not force)
        candidates = _candidates_for_field(field_name, deterministic, normalized_qwen, qwen_suggestion or {})
        all_candidates[field_name] = candidates

        protected_manual = current_source == "manual" and not force and not overwrite_manual_values and not is_empty_value(current)
        if locked or protected_manual:
            merged[field_name] = current
            sources[field_name] = {
                "source": current_source or "manual",
                "confidence": source_info.get("confidence") or 100,
                "evidence": source_info.get("evidence"),
            }
            decisions[field_name] = {
                "winner": "current",
                "reason": "locked" if locked else "manual_value_protected",
                "value": current,
            }
            continue

        winner, reason = _choose_winner(
            field_name,
            current,
            current_source,
            candidates,
            overwrite_manual_values=overwrite_manual_values,
            force=force,
        )
        if winner is not None:
            merged[field_name] = str(winner.value)
            sources[field_name] = {
                "source": winner.source,
                "confidence": winner.confidence,
                "evidence": winner.evidence,
            }
            decisions[field_name] = {"winner": winner.source, "reason": reason, "value": winner.value}
        elif force:
            merged[field_name] = None
            sources[field_name] = {"source": "deterministic", "confidence": None}
            decisions[field_name] = {"winner": None, "reason": "force_cleared_empty", "value": None}
        else:
            merged[field_name] = current
            sources[field_name] = {
                "source": current_source or "deterministic",
                "confidence": source_info.get("confidence"),
                "evidence": source_info.get("evidence"),
            }
            decisions[field_name] = {"winner": "current", "reason": "no_candidate", "value": current}

    _apply_derived_title(document, merged, sources, decisions, force=force, overwrite_manual_values=overwrite_manual_values)
    return MetadataResolution(merged=merged, sources=sources, candidates=all_candidates, decisions=decisions)


def _apply_derived_title(
    document: Document,
    merged: dict[str, str | None],
    sources: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    *,
    force: bool,
    overwrite_manual_values: bool,
) -> None:
    title_source = sources.get("title", {}).get("source")
    if title_source == "manual" and not (force or overwrite_manual_values):
        return
    if document.metadata_locked and not force:
        return
    if (document.field_locks_json or {}).get("title") and not force:
        return
    derived = derive_title_from_canonical_fields(document.collection_name, merged)
    if not derived:
        return
    current_title = merged.get("title")
    title_is_weak = is_empty_value(current_title) or str(current_title or "").startswith("Dok_") or "_NA" in str(current_title or "")
    dependency_sources = [sources.get(field, {}).get("source") for field in _title_dependency_fields(document.collection_name)]
    qwen_in_title = "qwen" in dependency_sources
    if derived == current_title and not title_is_weak:
        return
    if not (title_is_weak or qwen_in_title or force or overwrite_manual_values):
        return
    dependency_confidences = [
        sources.get(field, {}).get("confidence")
        for field in _title_dependency_fields(document.collection_name)
        if sources.get(field, {}).get("confidence") is not None
    ]
    confidence = min(int(value) for value in dependency_confidences) if dependency_confidences else None
    merged["title"] = derived
    sources["title"] = {
        "source": "derived",
        "confidence": confidence,
        "evidence": "title generated after canonical metadata resolution",
        "derived_from": _title_dependency_fields(document.collection_name),
    }
    decisions["title"] = {
        "winner": "derived",
        "reason": "title_derived_after_canonical_fields",
        "value": derived,
    }


def derive_title_from_canonical_fields(collection_name: str, merged: dict[str, str | None]) -> str | None:
    collection = collection_name.strip().lower()
    if collection == "eingangsrechnung":
        sender = _title_token(merged.get("sender"), strip_party=True)
        invoice_number = _title_token(merged.get("invoice_number"), keep_slash=True)
        date = _title_token(merged.get("date"), keep_slash=True)
        amount = _title_token(merged.get("amount"), keep_comma=True)
        if all(not is_empty_value(value) for value in [sender, invoice_number, date, amount]):
            return f"{sender}_{invoice_number}_{date}_{amount}"
        if all(not is_empty_value(value) for value in [sender, date, amount]):
            return f"{sender}_{date}_{amount}"
    if collection == "ausgangsrechnung":
        recipient = _title_token(merged.get("recipient"), strip_party=True)
        invoice_number = _title_token(merged.get("invoice_number"), keep_slash=True)
        date = _title_token(merged.get("date"), keep_slash=True)
        amount = _title_token(merged.get("amount"), keep_comma=True)
        if all(not is_empty_value(value) for value in [recipient, invoice_number, date, amount]):
            return f"{recipient}_{invoice_number}_{date}_{amount}"
        if all(not is_empty_value(value) for value in [recipient, date, amount]):
            return f"{recipient}_{date}_{amount}"
    if collection == "belege":
        sender = _title_token(merged.get("sender"), strip_party=True)
        date = _title_token(merged.get("date"), keep_slash=True)
        amount = _title_token(merged.get("amount"), keep_comma=True)
        payment = _title_token(merged.get("payment_method"))
        if all(not is_empty_value(value) for value in [sender, date, amount, payment]):
            return f"{sender}_B_{date}_{amount}_{payment}"
    return None


def _title_dependency_fields(collection_name: str) -> list[str]:
    collection = collection_name.strip().lower()
    if collection == "eingangsrechnung":
        return ["sender", "invoice_number", "date", "amount"]
    if collection == "ausgangsrechnung":
        return ["recipient", "invoice_number", "date", "amount"]
    if collection == "belege":
        return ["sender", "date", "amount", "payment_method"]
    return []


def _title_token(value: str | None, *, keep_slash: bool = False, keep_comma: bool = False, strip_party: bool = False) -> str:
    if is_empty_value(value):
        return "NA"
    text = str(value or "").strip()
    text = text.replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    if strip_party:
        text = re.sub(r"\bco\.?\s*ohg\b", " ", text, flags=re.I)
        text = re.sub(r"\b(ges\.?\s*mbh|gesmbh|gmbh|mbh|ag|kg|ug|ohg|re|inc|ltd|llc|sarl|e\.?k\.?)\b", " ", text, flags=re.I)
    allowed = "A-Za-z0-9"
    if keep_slash:
        allowed += r"/.-"
    if keep_comma:
        allowed += r",."
    return re.sub(rf"[^{allowed}]", "", text) or "NA"


def should_qwen_overwrite_field(
    field_name: str,
    current_value: str | None,
    current_source: str | None,
    locked: bool,
    overwrite_manual_values: bool,
    *,
    qwen_value: str | None = None,
    qwen_confidence: int | None = None,
    qwen_evidence: str | None = None,
) -> bool:
    if locked:
        return False
    if is_empty_value(current_value):
        return True
    if overwrite_manual_values:
        return True
    if current_source == "manual":
        return False
    if current_source == "deterministic" and qwen_candidate_is_stronger(
        field_name,
        current_value,
        qwen_value,
        qwen_confidence,
        qwen_evidence,
    ):
        return True
    return False


def review_warnings_for_resolution(
    document: Document,
    merged: dict[str, str | None],
    sources: dict[str, dict[str, Any]],
    qwen_suggestion: dict[str, Any] | None,
    deterministic: dict[str, str | None],
) -> list[str]:
    warnings: list[str] = []
    for field_name, source in sources.items():
        confidence = source.get("confidence")
        try:
            if confidence is not None and int(confidence) < 70:
                warnings.append(f"Low confidence for {field_name}")
        except (TypeError, ValueError):
            pass
    title = merged.get("title") or document.extracted_title or ""
    if title.startswith("Dok_") or "_NA" in title or title in {"Dok", "NA"}:
        warnings.append("Fallback title or missing title segment used")
    amount = merged.get("amount") or ""
    digits = "".join(ch for ch in amount if ch.isdigit())
    if amount == "42424242,00" or len(digits) > 9:
        warnings.append("Suspicious amount detected")
    date = merged.get("date") or ""
    if date in {"00/00", "00/00/0000"}:
        warnings.append("Suspicious or fallback date detected")
    normalized_qwen = normalize_qwen_suggestion(qwen_suggestion or {})
    for field_name in ["sender", "recipient", "invoice_number", "date", "amount"]:
        qwen_value = normalized_qwen.get(field_name)
        deterministic_value = deterministic.get(field_name)
        if sources.get(field_name, {}).get("source") == "qwen":
            continue
        if qwen_value and deterministic_value and str(qwen_value).strip() != str(deterministic_value).strip():
            if field_name == "sender" and strip_legal_suffix_key(compact_compare_text(qwen_value)) == compact_compare_text(deterministic_value):
                continue
            warnings.append(f"Qwen disagrees with deterministic {field_name}")
    ocr_state = getattr(document.ocr_state, "value", document.ocr_state)
    if ocr_state == "failed" or (document.raw_ocr_json or {}).get("partial_failure"):
        warnings.append("OCR failed partially")
    return sorted(set(warnings))


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text.upper() in EMPTY_VALUES


def normalize_qwen_suggestion(suggestion: dict[str, Any]) -> dict[str, str | None]:
    if not isinstance(suggestion, dict):
        return {}
    source = suggestion.get("metadata") if isinstance(suggestion.get("metadata"), dict) else suggestion
    aliases = {
        "title": ("title", "extracted_title"),
        "sender": ("sender", "correspondent", "vendor", "issuer"),
        "recipient": ("recipient", "customer"),
        "invoice_number": ("invoice_number", "invoiceNo", "invoice_no", "rechnungsnummer"),
        "date": ("date", "created_date", "invoice_date", "rechnungsdatum"),
        "amount": ("amount", "total", "gross_amount", "invoice_total"),
        "payment_method": ("payment_method", "zahlart"),
    }
    normalized: dict[str, str | None] = {}
    for target, keys in aliases.items():
        for key in keys:
            if key in source:
                value = source[key]
                normalized[target] = None if value is None else str(value).strip()
                if target == "date" and normalized[target]:
                    normalized[target] = normalize_qwen_date(normalized[target] or "")
                break
    return normalized


def qwen_confidence(suggestion: dict[str, Any], field_name: str) -> int | None:
    confidence = suggestion.get("confidence") if isinstance(suggestion, dict) else None
    if isinstance(confidence, dict):
        value = confidence.get(field_name)
    else:
        value = confidence
    try:
        if value is None:
            return None
        numeric = float(value)
        return int(numeric * 100) if numeric <= 1 else int(numeric)
    except (TypeError, ValueError):
        return None


def qwen_evidence(suggestion: dict[str, Any], field_name: str) -> str | None:
    evidence = suggestion.get("evidence") if isinstance(suggestion, dict) else None
    if isinstance(evidence, dict):
        value = evidence.get(field_name)
    else:
        value = None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def qwen_candidate_is_stronger(
    field_name: str,
    current_value: str | None,
    qwen_value: str | None,
    qwen_confidence: int | None,
    qwen_evidence: str | None,
) -> bool:
    if is_empty_value(qwen_value) or (qwen_confidence is not None and qwen_confidence < 90):
        return False
    if not qwen_evidence:
        return False
    if field_name == "sender":
        current_key = compact_compare_text(current_value)
        qwen_key = compact_compare_text(qwen_value)
        if current_key and qwen_key:
            if strip_legal_suffix_key(qwen_key) == current_key:
                return False
            if current_key in qwen_key and len(qwen_key) > len(current_key) + 3:
                return True
        return looks_like_compacted_or_damaged_party(current_value) and len(str(qwen_value or "")) > len(str(current_value or ""))
    if field_name == "date":
        return bool(re.search(r"rechnung|invoice", qwen_evidence, flags=re.I))
    if field_name == "amount":
        current_amount = amount_number(current_value)
        qwen_amount = amount_number(qwen_value)
        if current_amount is None or qwen_amount is None:
            return False
        return current_amount >= 10000 and qwen_amount < current_amount / 10
    if field_name == "invoice_number":
        return bool(re.search(r"rechnung|invoice", qwen_evidence, flags=re.I)) and "/" in str(qwen_value or "")
    return False


def normalize_qwen_date(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if match:
        return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
    try:
        from app.services.extraction import normalize_date

        normalized = normalize_date(text)
        if normalized:
            return normalized
    except Exception:  # pragma: no cover - defensive normalization only
        pass
    return text


def compact_compare_text(value: str | None) -> str:
    text = str(value or "").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def strip_legal_suffix_key(value: str) -> str:
    text = value
    suffixes = ("gmbh", "mbh", "ag", "kg", "ug", "ohg", "inc", "ltd", "llc", "sarl", "ek", "co")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix) + 2:
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def looks_like_compacted_or_damaged_party(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if " " not in text and len(text) >= 8:
        return True
    compact = compact_compare_text(text)
    return len(compact) >= 8 and len(compact) <= len(text.replace(" ", "")) - 1


def amount_number(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _candidates_for_field(
    field_name: str,
    deterministic: dict[str, str | None],
    normalized_qwen: dict[str, str | None],
    raw_qwen: dict[str, Any],
) -> list[MetadataCandidate]:
    candidates: list[MetadataCandidate] = []
    deterministic_value = deterministic.get(field_name)
    if not is_empty_value(deterministic_value):
        candidates.append(
            MetadataCandidate(
                field=field_name,
                value=str(deterministic_value),
                source="deterministic",
                confidence=_deterministic_confidence(field_name, deterministic_value),
                authority=_deterministic_authority(field_name, deterministic_value),
                reason=_deterministic_reason(field_name, deterministic_value),
            )
        )
    qwen_value = normalized_qwen.get(field_name)
    if not is_empty_value(qwen_value):
        candidates.append(
            MetadataCandidate(
                field=field_name,
                value=str(qwen_value),
                source="qwen",
                confidence=qwen_confidence(raw_qwen, field_name),
                evidence=qwen_evidence(raw_qwen, field_name),
                authority="qwen_grounded_candidate",
                reason="structured_qwen_metadata_brain",
            )
        )
    return candidates


def _choose_winner(
    field_name: str,
    current_value: str | None,
    current_source: str | None,
    candidates: list[MetadataCandidate],
    *,
    overwrite_manual_values: bool,
    force: bool,
) -> tuple[MetadataCandidate | None, str]:
    qwen = next((candidate for candidate in candidates if candidate.source == "qwen"), None)
    deterministic = next((candidate for candidate in candidates if candidate.source == "deterministic"), None)
    if qwen and should_qwen_overwrite_field(
        field_name,
        deterministic.value if deterministic else current_value,
        "deterministic" if deterministic else current_source,
        False,
        overwrite_manual_values,
        qwen_value=qwen.value,
        qwen_confidence=qwen.confidence,
        qwen_evidence=qwen.evidence,
    ):
        return qwen, "qwen_wins_authority_order"
    if deterministic:
        return deterministic, "deterministic_candidate"
    if qwen and (force or is_empty_value(current_value) or overwrite_manual_values):
        return qwen, "qwen_fills_empty_or_forced"
    return None, "no_winner"


def _deterministic_confidence(field_name: str, value: Any) -> int | None:
    if is_empty_value(value):
        return None
    text = str(value)
    if field_name == "title" and (text.startswith("Dok_") or "_NA" in text or text in {"Dok", "NA"}):
        return 35
    if field_name == "sender" and looks_like_compacted_or_damaged_party(text):
        return 75
    if field_name == "amount":
        number = amount_number(text)
        if number is not None and number >= 10000:
            return 35
    return 90


def _deterministic_authority(field_name: str, value: Any) -> str:
    confidence = _deterministic_confidence(field_name, value)
    if confidence is None:
        return "empty"
    if confidence >= 90:
        return "exact_deterministic_label"
    return "weak_fallback"


def _deterministic_reason(field_name: str, value: Any) -> str:
    confidence = _deterministic_confidence(field_name, value)
    if confidence is None:
        return "empty"
    if confidence >= 90:
        return "parser_label_or_schema_match"
    if field_name == "amount":
        return "suspicious_large_amount_or_identifier_context"
    if field_name == "title":
        return "fallback_title_segment"
    if field_name == "sender":
        return "compacted_or_possibly_ocr_damaged_party"
    return "weak_deterministic_candidate"
