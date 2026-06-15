from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Document, OCRMode


@dataclass(slots=True)
class EffectiveOCRConfig:
    ocr_mode: OCRMode
    ocr_engine: str
    language: str
    cleanup_mode: str
    deskew: bool
    rotate_pages: bool
    rotate_threshold: float
    page_limit: int
    image_dpi: int
    output_type: str
    max_image_pixels: int

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ocr_mode"] = self.ocr_mode.value
        return payload


def resolve_ocr_config(document: Document, settings: Settings | None = None) -> EffectiveOCRConfig:
    settings = settings or get_settings()
    collection_config = {}
    if document.record and document.record.collection:
        collection_config = document.record.collection.ocr_config_json or {}
    document_config = document.ocr_config_json or {}
    merged = {
        "ocr_mode": settings.ocr_mode,
        "ocr_engine": settings.ocr_provider,
        "language": settings.ocr_language,
        "cleanup_mode": settings.ocr_cleanup_mode,
        "deskew": settings.ocr_deskew,
        "rotate_pages": settings.ocr_rotate_pages,
        "rotate_threshold": settings.ocr_rotate_threshold,
        "page_limit": settings.ocr_max_pages_per_doc,
        "image_dpi": settings.ocr_image_dpi,
        "output_type": settings.ocr_output_type,
        "max_image_pixels": settings.ocr_max_image_pixels,
        **collection_config,
        **document_config,
    }
    merged["ocr_mode"] = getattr(document.ocr_mode, "value", document.ocr_mode) or merged["ocr_mode"]
    if isinstance(merged.get("ocr_mode"), OCRMode):
        mode = merged["ocr_mode"]
    else:
        mode = OCRMode(str(merged.get("ocr_mode") or settings.ocr_mode))
    engine = str(merged.get("ocr_engine") or settings.ocr_provider).strip() or settings.ocr_provider
    if engine not in {"fake", "glm", "paddle_vl", "ppocrv6"}:
        engine = settings.ocr_provider
    return EffectiveOCRConfig(
        ocr_mode=mode,
        ocr_engine=engine,
        language=str(merged["language"]),
        cleanup_mode=str(merged["cleanup_mode"]),
        deskew=bool(merged["deskew"]),
        rotate_pages=bool(merged["rotate_pages"]),
        rotate_threshold=float(merged["rotate_threshold"]),
        page_limit=int(merged["page_limit"]),
        image_dpi=int(merged["image_dpi"]),
        output_type=str(merged["output_type"]),
        max_image_pixels=int(merged["max_image_pixels"]),
    )


def store_effective_ocr_trace(document: Document, config: EffectiveOCRConfig) -> None:
    document.prompt_trace_json = {
        **(document.prompt_trace_json or {}),
        "ocr_config": config.as_dict(),
    }
    document.model_trace_json = {
        **(document.model_trace_json or {}),
        "ocr_pipeline": {
            "engine": config.ocr_engine,
            "mode": config.ocr_mode.value,
            "output_type_note": "VLM OCR/parser produces text or markdown; output_type is trace-only in v1",
        },
    }
