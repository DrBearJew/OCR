from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Batch, Document, DocumentState, StageState
from app.services.collections import create_record_for_upload, ensure_collection, update_record_status
from app.services.document_assets import generate_thumbnail, inspect_page_count, virus_scan_placeholder
from app.services.events import record_event
from app.services.extraction import ExtractionInput, extract_metadata
from app.services.processing import mark_duplicate_document, update_batch_status
from app.services.reconciliation import reconcile_stuck_documents, reextract_collection, retry_failed_documents
from app.services.storage_integrity import scan_storage_integrity


def main() -> None:
    parser = argparse.ArgumentParser(prog="dokocr-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("retry-failed")
    sub.add_parser("reconcile-stuck")
    reextract = sub.add_parser("reextract-collection")
    reextract.add_argument("collection_name")
    reextract.add_argument("--force", action="store_true")
    rebuild = sub.add_parser("rebuild-search")
    rebuild.add_argument("--collection", dest="collection_name")
    sub.add_parser("storage-scan")
    importer = sub.add_parser("import-legacy")
    importer.add_argument("--files-dir", required=True)
    importer.add_argument("--metadata", help="CSV or JSON export with OCR/title/metadata")
    importer.add_argument("--collection", default="Belege")
    importer.add_argument("--legacy-source", default="legacy")
    exporter = sub.add_parser("export-documents")
    exporter.add_argument("--out", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.command == "retry-failed":
            print(json.dumps(retry_failed_documents(db), indent=2, default=str))
        elif args.command == "reconcile-stuck":
            print(json.dumps(reconcile_stuck_documents(db), indent=2, default=str))
        elif args.command == "reextract-collection":
            print(json.dumps(reextract_collection(db, args.collection_name, force=args.force), indent=2, default=str))
        elif args.command == "rebuild-search":
            print(json.dumps(rebuild_search_markers(db, collection_name=args.collection_name), indent=2, default=str))
        elif args.command == "storage-scan":
            print(json.dumps(scan_storage_integrity(db), indent=2, default=str))
        elif args.command == "import-legacy":
            print(json.dumps(import_legacy(db, Path(args.files_dir), args.metadata, args.collection, args.legacy_source), indent=2, default=str))
        elif args.command == "export-documents":
            export_documents(db, Path(args.out))
            print(json.dumps({"ok": True, "out": args.out}, indent=2))
    finally:
        db.close()


def import_legacy(
    db,
    files_dir: Path,
    metadata_path: str | None,
    default_collection: str,
    legacy_source: str,
) -> dict:
    settings = get_settings()
    rows = _load_metadata(metadata_path)
    batch = Batch(collection_name=default_collection, label=f"Legacy import: {legacy_source}")
    db.add(batch)
    db.flush()
    root_collection = ensure_collection(db, default_collection)
    record = create_record_for_upload(db, root_collection, title=f"Legacy import: {legacy_source}")

    imported = 0
    duplicates = 0
    target_dir = Path(settings.storage_root) / "imports" / str(batch.id)
    target_dir.mkdir(parents=True, exist_ok=True)

    for source_path in files_dir.rglob("*"):
        if not source_path.is_file():
            continue
        meta = _metadata_for(source_path, rows)
        collection = meta.get("collection") or default_collection
        target = target_dir / f"{uuid.uuid4()}_{source_path.name}"
        shutil.copy2(source_path, target)
        virus_scan_placeholder(str(target))
        file_hash = _sha256(target)
        existing = db.scalars(select(Document).where(Document.sha256 == file_hash).order_by(Document.created_at.asc())).first()
        page_count = inspect_page_count(str(target), meta.get("mime_type"))
        document = Document(
            batch_id=batch.id,
            record_id=record.id,
            collection_name=collection,
            original_filename=source_path.name,
            storage_path=str(target),
            mime_type=meta.get("mime_type"),
            file_size=target.stat().st_size,
            sha256=file_hash,
            page_count=page_count,
            legacy_source=legacy_source,
            legacy_document_id=str(meta.get("legacy_document_id") or meta.get("id") or ""),
            ocr_text=meta.get("ocr_text") or None,
        )
        db.add(document)
        db.flush()
        document.thumbnail_path = generate_thumbnail(str(target), document.mime_type, document.id)
        record_event(db, document, "imported", "Legacy document imported", source="import", metadata={"path": str(source_path)})

        if existing is not None:
            mark_duplicate_document(db, document, existing)
            duplicates += 1
        elif document.ocr_text:
            extraction = extract_metadata(ExtractionInput(collection, document.ocr_text, document.original_filename, document.created_at))
            document.extracted_title = meta.get("title") or extraction.title
            document.metadata_json = {**(meta.get("metadata_json") or {}), "imported": True, "deterministic_title": extraction.title}
            document.raw_ocr_json = meta.get("raw_ocr_json") or {}
            document.ocr_state = StageState.done
            document.metadata_state = StageState.done
            document.processing_state = DocumentState.complete
            document.final_state = DocumentState.complete
            document.completed_at = datetime.now(timezone.utc)
            record_event(db, document, "import_metadata_applied", "Imported OCR and metadata applied", source="import")
        imported += 1

    update_batch_status(db, batch.id)
    update_record_status(db, record.id)
    db.commit()
    return {"ok": True, "imported": imported, "duplicates": duplicates, "batch_id": str(batch.id)}


def export_documents(db, out: Path) -> None:
    docs = db.scalars(select(Document).order_by(Document.created_at.asc())).all()
    payload = [
        {
            "id": str(doc.id),
            "legacy_source": doc.legacy_source,
            "legacy_document_id": doc.legacy_document_id,
            "collection": doc.collection_name,
            "filename": doc.original_filename,
            "title": doc.manual_title_override or doc.extracted_title,
            "metadata": doc.metadata_json,
            "ocr_text": doc.ocr_text,
            "sha256": doc.sha256,
        }
        for doc in docs
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def rebuild_search_markers(db, collection_name: str | None = None) -> dict:
    stmt = select(Document).where(Document.deleted_at.is_(None))
    if collection_name:
        stmt = stmt.where(Document.collection_name == collection_name)
    updated = 0
    for document in db.scalars(stmt).all():
        document.metadata_json = {**(document.metadata_json or {}), "search_indexed": True}
        record_event(db, document, "search_indexed", "Search index marker refreshed by CLI")
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "collection_name": collection_name}


def _load_metadata(path: str | None) -> list[dict]:
    if not path:
        return []
    meta_path = Path(path)
    if meta_path.suffix.lower() == ".json":
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else list(data.values())
    with meta_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _metadata_for(path: Path, rows: list[dict]) -> dict:
    for row in rows:
        if str(row.get("original_path") or row.get("path") or "") == str(path):
            return _decode_json_columns(row)
        if str(row.get("filename") or row.get("original_filename") or "") == path.name:
            return _decode_json_columns(row)
    return {}


def _decode_json_columns(row: dict) -> dict:
    result = dict(row)
    for key in ("metadata_json", "raw_ocr_json"):
        if isinstance(result.get(key), str) and result[key].strip():
            try:
                result[key] = json.loads(result[key])
            except json.JSONDecodeError:
                result[key] = {}
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
