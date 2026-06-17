from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
import json
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Collection, Correspondent, Document, DocumentType, StoragePathRule, Tag
from app.services.collections import slugify
from app.services.events import record_event


@dataclass(slots=True)
class MetadataProfileMatch:
    row: Correspondent | DocumentType | Tag | StoragePathRule
    score: int
    reason: str
    evidence: str | None = None


def apply_paperless_metadata(db: Session, document: Document) -> None:
    """Apply Paperless-style DB-backed metadata profiles after canonical field resolution.

    Paperless-ngx treats correspondent, document type, tags, and storage paths as
    first-class metadata objects with matching rules. Dok OCR stores the same kind
    of objects in DB tables with `match_rules`; this function evaluates those
    rules against OCR text, canonical fields, Qwen candidates, and similar derived
    context, then assigns matching objects unless the user manually locked that
    assignment.
    """
    collection = _document_collection(db, document)
    if collection is None:
        return

    sources = document.metadata_sources_json if isinstance(document.metadata_sources_json, dict) else {}
    locked = document.metadata_locked
    assignments: dict[str, Any] = {}

    correspondent_match = _best_profile_match(db, collection, Correspondent, document, "correspondent")
    if not (locked or _manual_source(sources, "correspondent_id")):
        if correspondent_match:
            document.correspondent_id = correspondent_match.row.id
            assignments["correspondent"] = _match_payload(correspondent_match)
        else:
            party = document.extracted_sender or document.extracted_recipient
            if party and party != "Dok":
                correspondent = _ensure_correspondent(db, collection, party)
                document.correspondent_id = correspondent.id
                assignments["correspondent"] = {"id": str(correspondent.id), "name": correspondent.name, "source": "canonical_party"}

    document_type_match = _best_profile_match(db, collection, DocumentType, document, "document_type")
    if not (locked or _manual_source(sources, "document_type_id")):
        if document_type_match:
            document.document_type_id = document_type_match.row.id
            assignments["document_type"] = _match_payload(document_type_match)
        else:
            metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
            document_type_name = str(metadata.get("document_type") or document.collection_name)
            document_type = _ensure_document_type(db, collection, document_type_name)
            document.document_type_id = document_type.id
            assignments["document_type"] = {"id": str(document_type.id), "name": document_type.name, "source": "collection_or_qwen_type"}

    tag_matches = _profile_matches(db, collection, Tag, document, "tag")
    if not (locked or _manual_source(sources, "tag_ids") or _manual_source(sources, "tags")):
        existing_ids = {tag.id for tag in document.tags}
        added = []
        for match in tag_matches:
            if match.row.id in existing_ids:
                continue
            document.tags.append(match.row)
            existing_ids.add(match.row.id)
            added.append(_match_payload(match))
        for tag_name in _suggested_tag_names(document):
            tag = _ensure_tag(db, collection, tag_name)
            if tag.id in existing_ids:
                continue
            document.tags.append(tag)
            existing_ids.add(tag.id)
            added.append({"id": str(tag.id), "name": tag.name, "source": "qwen_bootstrap"})
        if added:
            assignments["tags"] = added

    storage_match = _best_profile_match(db, collection, StoragePathRule, document, "storage_path")
    if not (locked or _manual_source(sources, "storage_path_id")):
        if storage_match:
            document.storage_path_id = storage_match.row.id
            assignments["storage_path"] = _match_payload(storage_match)
        else:
            suggested_path = _suggested_storage_path(document)
            if suggested_path:
                storage_rule = _ensure_storage_path(db, collection, suggested_path, suggested_path)
                document.storage_path_id = storage_rule.id
                assignments["storage_path"] = {"id": str(storage_rule.id), "name": storage_rule.name, "path_template": storage_rule.path_template, "source": "qwen_bootstrap"}
            else:
                storage_rule = _ensure_storage_path(db, collection, "Default", "{collection}/{year}")
                document.storage_path_id = storage_rule.id
                assignments["storage_path"] = {"id": str(storage_rule.id), "name": storage_rule.name, "source": "default"}

    metadata = dict(document.metadata_json or {})
    metadata["paperless_assignments"] = assignments
    document.metadata_json = metadata
    record_event(
        db,
        document,
        "paperless_metadata_mapped",
        "Mapped correspondent, document type, tag, and storage path metadata",
        metadata={
            "correspondent_id": str(document.correspondent_id) if document.correspondent_id else None,
            "document_type_id": str(document.document_type_id) if document.document_type_id else None,
            "storage_path_id": str(document.storage_path_id) if document.storage_path_id else None,
            "tag_ids": [str(tag.id) for tag in document.tags],
            "assignments": assignments,
        },
    )


def _document_collection(db: Session, document: Document) -> Collection | None:
    if document.record and document.record.collection:
        return document.record.collection
    return db.scalars(select(Collection).where(Collection.name == document.collection_name)).first()


def _profile_matches(
    db: Session,
    collection: Collection,
    model: type[Correspondent] | type[DocumentType] | type[Tag] | type[StoragePathRule],
    document: Document,
    kind: str,
) -> list[MetadataProfileMatch]:
    rows = db.scalars(
        select(model)
        .where(or_(model.collection_id == collection.id, model.collection_id.is_(None)))
        .order_by(model.name.asc())
    ).all()
    matches: list[MetadataProfileMatch] = []
    for row in rows:
        match = _match_profile(row, document, kind)
        if match:
            matches.append(match)
    matches.sort(key=lambda item: (-item.score, item.row.name.lower(), str(item.row.id)))
    return matches


def _best_profile_match(
    db: Session,
    collection: Collection,
    model: type[Correspondent] | type[DocumentType] | type[Tag] | type[StoragePathRule],
    document: Document,
    kind: str,
) -> MetadataProfileMatch | None:
    matches = _profile_matches(db, collection, model, document, kind)
    return matches[0] if matches else None


def _match_profile(row: Correspondent | DocumentType | Tag | StoragePathRule, document: Document, kind: str) -> MetadataProfileMatch | None:
    rules = row.match_rules if isinstance(row.match_rules, dict) else {}
    algorithm = str(rules.get("matching_algorithm") or rules.get("algorithm") or ("automatic" if rules.get("auto") else "any")).lower()
    if algorithm in {"none", "disabled"}:
        return None

    candidate_match = _match_profile_candidates(row, document, kind, rules)
    if candidate_match and algorithm in {"automatic", "auto", "qwen"}:
        return candidate_match

    target = _target_text(document, str(rules.get("field") or rules.get("target") or "content"))
    patterns = _rule_patterns(row, rules)
    if not patterns:
        return candidate_match

    insensitive = bool(rules.get("is_insensitive", rules.get("case_insensitive", True)))
    threshold = int(rules.get("threshold") or rules.get("confidence") or 0)
    match = _match_patterns(target, patterns, algorithm, insensitive=insensitive, threshold=threshold)
    if match:
        score, evidence = match
        return MetadataProfileMatch(row=row, score=score, reason=f"{algorithm}_rule", evidence=evidence)
    return candidate_match


def _match_profile_candidates(
    row: Correspondent | DocumentType | Tag | StoragePathRule,
    document: Document,
    kind: str,
    rules: dict[str, Any],
) -> MetadataProfileMatch | None:
    candidate_values = _candidate_values(document, kind)
    if not candidate_values:
        return None
    aliases = _profile_aliases(row, rules)
    for value in candidate_values:
        normalized_value = _normalize_key(value)
        if not normalized_value:
            continue
        for alias in aliases:
            normalized_alias = _normalize_key(alias)
            if normalized_alias and (normalized_value == normalized_alias or normalized_alias in normalized_value or normalized_value in normalized_alias):
                return MetadataProfileMatch(row=row, score=100, reason="automatic_candidate", evidence=value)
    return None


def _match_patterns(
    target: str,
    patterns: list[str],
    algorithm: str,
    *,
    insensitive: bool,
    threshold: int,
) -> tuple[int, str] | None:
    flags = re.IGNORECASE if insensitive else 0
    target_for_text = target.lower() if insensitive else target
    clean_patterns = [pattern.strip() for pattern in patterns if pattern and pattern.strip()]
    if not clean_patterns:
        return None

    if algorithm == "regex":
        for pattern in clean_patterns:
            if len(pattern) > 256:
                continue
            try:
                found = re.search(pattern, target, flags=flags)
            except re.error:
                continue
            if found:
                return max(threshold, 100), found.group(0)[:160]
        return None

    if algorithm in {"literal", "exact"}:
        for pattern in clean_patterns:
            needle = pattern.lower() if insensitive else pattern
            if needle in target_for_text:
                return max(threshold, 95), pattern[:160]
        return None

    if algorithm == "all":
        missing = [pattern for pattern in clean_patterns if (pattern.lower() if insensitive else pattern) not in target_for_text]
        if not missing:
            return max(threshold, 90), ", ".join(clean_patterns)[:160]
        return None

    if algorithm == "fuzzy":
        normalized_target = _normalize_key(target)
        for pattern in clean_patterns:
            normalized_pattern = _normalize_key(pattern)
            if not normalized_pattern:
                continue
            ratio = SequenceMatcher(None, normalized_pattern, normalized_target).ratio()
            if normalized_pattern in normalized_target:
                ratio = max(ratio, 0.95)
            score = int(ratio * 100)
            if score >= max(threshold or 85, 70):
                return score, pattern[:160]
        return None

    # default Paperless-like "any word" semantics.
    for pattern in clean_patterns:
        needle = pattern.lower() if insensitive else pattern
        if needle in target_for_text:
            return max(threshold, 80), pattern[:160]
    return None


def _target_text(document: Document, field: str) -> str:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    parts = {
        "content": [document.ocr_text, document.extracted_title, document.original_filename, json.dumps(metadata, ensure_ascii=False, default=str)],
        "ocr_text": [document.ocr_text],
        "title": [document.manual_title_override, document.extracted_title, document.original_filename],
        "filename": [document.original_filename],
        "sender": [document.extracted_sender],
        "recipient": [document.extracted_recipient],
        "invoice_number": [document.extracted_invoice_number],
        "date": [document.extracted_date],
        "amount": [document.extracted_amount],
        "qwen": [json.dumps(metadata.get("qwen_candidates") or {}, ensure_ascii=False, default=str)],
        "metadata": [json.dumps(metadata, ensure_ascii=False, default=str)],
    }.get(field, [document.ocr_text])
    return "\n".join(str(part) for part in parts if part)


def _candidate_values(document: Document, kind: str) -> list[str]:
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    qwen = metadata.get("qwen_candidates") if isinstance(metadata.get("qwen_candidates"), dict) else {}
    values: list[Any] = []
    if kind == "correspondent":
        values.extend([document.extracted_sender, document.extracted_recipient, _candidate_value(qwen.get("sender")), _candidate_value(qwen.get("correspondent"))])
        entities = qwen.get("entities") if isinstance(qwen.get("entities"), dict) else {}
        values.extend(entities.get("organizations") or [])
    elif kind == "document_type":
        values.extend([metadata.get("document_type"), _candidate_value(qwen.get("document_type")), document.collection_name])
    elif kind == "tag":
        values.extend(document.llm_suggested_tags or [])
        values.extend(qwen.get("suggested_tags") or [])
    elif kind == "storage_path":
        values.extend([document.llm_suggested_folder, qwen.get("suggested_folder")])
    result: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("text")
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _candidate_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def _rule_patterns(row: Correspondent | DocumentType | Tag | StoragePathRule, rules: dict[str, Any]) -> list[str]:
    raw = rules.get("match") or rules.get("matches") or rules.get("patterns") or rules.get("keywords") or rules.get("aliases")
    patterns: list[str] = []
    if isinstance(raw, str):
        patterns.extend([part.strip() for part in re.split(r"[,\n]", raw) if part.strip()])
    elif isinstance(raw, list):
        patterns.extend(str(item).strip() for item in raw if str(item).strip())
    include_name_default = raw is None or raw == "" or raw == []
    if rules.get("include_name", include_name_default):
        patterns.append(row.name)
    return list(dict.fromkeys(patterns))


def _profile_aliases(row: Correspondent | DocumentType | Tag | StoragePathRule, rules: dict[str, Any]) -> list[str]:
    aliases = [row.name, row.slug]
    raw_aliases = rules.get("aliases") or rules.get("match") or []
    if isinstance(raw_aliases, str):
        aliases.extend([part.strip() for part in re.split(r"[,\n]", raw_aliases) if part.strip()])
    elif isinstance(raw_aliases, list):
        aliases.extend(str(item).strip() for item in raw_aliases if str(item).strip())
    if isinstance(row, StoragePathRule):
        aliases.append(row.path_template)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ß", "ss")
    text = re.sub(r"[äáàâ]", "a", text)
    text = re.sub(r"[öóòô]", "o", text)
    text = re.sub(r"[üúùû]", "u", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _match_payload(match: MetadataProfileMatch) -> dict[str, Any]:
    return {
        "id": str(match.row.id),
        "name": match.row.name,
        "score": match.score,
        "reason": match.reason,
        "evidence": match.evidence,
        "source": "paperless_profile",
    }


def _suggested_tag_names(document: Document) -> list[str]:
    names = _candidate_values(document, "tag")
    safe: list[str] = []
    seen: set[str] = set()
    for name in names:
        cleaned = _safe_tag_name(name)
        if not cleaned:
            continue
        key = slugify(cleaned)
        if key in seen:
            continue
        seen.add(key)
        safe.append(cleaned)
        if len(safe) >= 8:
            break
    return safe


def _safe_tag_name(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or len(text) > 80:
        return None
    low = text.lower()
    if low in {"na", "n/a", "unknown", "unbekannt", "none", "null"}:
        return None
    if re.fullmatch(r"\d{2,}", text):
        return None
    if re.fullmatch(r"\d{4}", text):
        return None
    if re.fullmatch(r"[A-Z0-9][A-Z0-9./-]{5,}", text, flags=re.I) and any(ch.isdigit() for ch in text):
        return None
    if any(token in low for token in ["iban", "bic", "hrb", "hra", "ust-id", "ust.-id"]):
        return None
    return text


def _suggested_storage_path(document: Document) -> str | None:
    for value in _candidate_values(document, "storage_path"):
        safe = _safe_storage_path(value)
        if safe:
            return safe
    return None


def _safe_storage_path(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text).strip("/")
    if not text or len(text) > 240:
        return None
    if text.startswith(("/", "~")) or ".." in text.split("/"):
        return None
    cleaned_segments: list[str] = []
    for segment in text.split("/"):
        segment = re.sub(r"\s+", " ", segment.strip())
        segment = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß _.,()\-]", "", segment).strip(" .")
        if not segment:
            return None
        cleaned_segments.append(segment[:80])
    return "/".join(cleaned_segments[:6])


def _ensure_tag(db: Session, collection: Collection, name: str) -> Tag:
    slug = slugify(name)
    row = db.scalars(
        select(Tag)
        .where(Tag.collection_id == collection.id)
        .where(Tag.slug == slug)
    ).first()
    if row:
        return row
    row = Tag(collection_id=collection.id, name=name, slug=slug, match_rules={"matching_algorithm": "automatic", "aliases": [name]})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(Tag)
            .where(Tag.collection_id == collection.id)
            .where(Tag.slug == slug)
        ).one()


def _ensure_correspondent(db: Session, collection: Collection, name: str) -> Correspondent:
    slug = slugify(name)
    row = db.scalars(
        select(Correspondent)
        .where(Correspondent.collection_id == collection.id)
        .where(Correspondent.slug == slug)
    ).first()
    if row:
        return row
    row = Correspondent(collection_id=collection.id, name=name, slug=slug, match_rules={"matching_algorithm": "automatic", "aliases": [name]})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(Correspondent)
            .where(Correspondent.collection_id == collection.id)
            .where(Correspondent.slug == slug)
        ).one()


def _manual_source(sources: dict, field: str) -> bool:
    value = sources.get(field)
    return isinstance(value, dict) and value.get("source") == "manual"


def _ensure_document_type(db: Session, collection: Collection, name: str) -> DocumentType:
    slug = slugify(name)
    row = db.scalars(
        select(DocumentType)
        .where(DocumentType.collection_id == collection.id)
        .where(DocumentType.slug == slug)
    ).first()
    if row:
        return row
    row = DocumentType(collection_id=collection.id, name=name, slug=slug, match_rules={"matching_algorithm": "automatic", "aliases": [name]})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(DocumentType)
            .where(DocumentType.collection_id == collection.id)
            .where(DocumentType.slug == slug)
        ).one()


def _ensure_storage_path(db: Session, collection: Collection, name: str, template: str) -> StoragePathRule:
    slug = slugify(name)
    row = db.scalars(
        select(StoragePathRule)
        .where(StoragePathRule.collection_id == collection.id)
        .where(StoragePathRule.slug == slug)
    ).first()
    if row:
        return row
    row = StoragePathRule(collection_id=collection.id, name=name, slug=slug, path_template=template, match_rules={"matching_algorithm": "automatic", "aliases": [name, template]})
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
            return row
    except IntegrityError:
        return db.scalars(
            select(StoragePathRule)
            .where(StoragePathRule.collection_id == collection.id)
            .where(StoragePathRule.slug == slug)
        ).one()
