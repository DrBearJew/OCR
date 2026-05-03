from __future__ import annotations

import logging
from pathlib import Path
import uuid

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def virus_scan_placeholder(path: str) -> None:
    """Hook point for a scanner such as ClamAV; v1 records the boundary without blocking."""
    logger.debug("Virus scan placeholder accepted path=%s", path)


def inspect_page_count(path: str, mime_type: str | None, settings: Settings | None = None) -> int | None:
    settings = settings or get_settings()
    if (mime_type or "").lower() != "application/pdf" and not str(path).lower().endswith(".pdf"):
        return 1
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        try:
            page_count = len(pdf)
        finally:
            pdf.close()
        if page_count > settings.max_pdf_pages:
            raise ValueError(f"PDF has {page_count} pages, max is {settings.max_pdf_pages}")
        return page_count
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not inspect PDF pages path=%s error=%s", path, exc)
        return None


def generate_thumbnail(
    path: str,
    mime_type: str | None,
    document_id: uuid.UUID,
    settings: Settings | None = None,
) -> str | None:
    settings = settings or get_settings()
    thumbnails_dir = Path(settings.storage_root) / "thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    target = thumbnails_dir / f"{document_id}.jpg"
    try:
        from PIL import Image

        lower_mime = (mime_type or "").lower()
        if lower_mime == "application/pdf" or str(path).lower().endswith(".pdf"):
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(path)
            try:
                if len(pdf) == 0:
                    return None
                page = pdf[0]
                bitmap = page.render(scale=1.0).to_pil()
            finally:
                pdf.close()
            image = bitmap.convert("RGB")
        elif lower_mime.startswith("image/"):
            image = Image.open(path).convert("RGB")
        else:
            return None

        image.thumbnail((settings.thumbnail_size, settings.thumbnail_size))
        image.save(target, format="JPEG", quality=82)
        return str(target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not generate thumbnail path=%s error=%s", path, exc)
        return None


def render_pdf_pages(
    path: str,
    document_id: uuid.UUID,
    *,
    page_limit: int,
    image_dpi: int,
    settings: Settings | None = None,
) -> list[str]:
    settings = settings or get_settings()
    pages_dir = Path(settings.storage_root) / "pages" / str(document_id)
    pages_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[str] = []
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        try:
            count = min(len(pdf), max(1, page_limit))
            scale = max(0.5, image_dpi / 72)
            for index in range(count):
                page = pdf[index]
                image = page.render(scale=scale).to_pil().convert("RGB")
                target = pages_dir / f"page_{index + 1:04d}.jpg"
                image.save(target, format="JPEG", quality=88)
                rendered.append(str(target))
        finally:
            pdf.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render PDF pages path=%s error=%s", path, exc)
    return rendered
