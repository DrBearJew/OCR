from __future__ import annotations

import hashlib
from pathlib import Path
import re
import uuid

from fastapi import UploadFile

from app.config import Settings, get_settings


class StoredFile(dict):
    path: str
    sha256: str
    size: int


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "document")
    cleaned = cleaned.strip(" .") or "document"
    return cleaned[:180]


class LocalStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = Path(self.settings.storage_root)

    async def save_upload(self, upload: UploadFile, batch_id: uuid.UUID, *, max_bytes: int | None = None) -> dict:
        self.validate_upload(upload)
        max_bytes = max_bytes or self.settings.max_upload_bytes
        batch_dir = self.root / str(batch_id)
        batch_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_filename(upload.filename or "document")
        target = batch_dir / f"{uuid.uuid4()}_{filename}"
        digest = hashlib.sha256()
        size = 0
        too_large = False
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    too_large = True
                    break
                digest.update(chunk)
                out.write(chunk)
        await upload.close()
        if too_large:
            target.unlink(missing_ok=True)
            raise ValueError(f"Upload too large. Max file size is {self.settings.max_upload_file_size_mb} MB and max batch size is {self.settings.max_upload_batch_size_mb} MB.")
        return {"path": str(target), "sha256": digest.hexdigest(), "size": size}

    def validate_upload(self, upload: UploadFile) -> None:
        filename = safe_filename(upload.filename or "document")
        suffix = Path(filename).suffix.lower().lstrip(".")
        mime_type = (upload.content_type or "").lower()
        if suffix not in self.settings.allowed_extensions_set:
            raise ValueError(f"File extension .{suffix or 'none'} is not allowed")
        if mime_type and mime_type not in self.settings.allowed_mime_types_set:
            raise ValueError(f"MIME type {mime_type} is not allowed")

    def resolve(self, storage_path: str) -> Path:
        raw = Path(storage_path)
        if ".." in raw.parts:
            raise ValueError("Storage path contains traversal")
        root = self.root.resolve()
        path = raw if raw.is_absolute() else root / raw
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Storage path escapes storage root") from exc
        current = root
        for part in path.relative_to(root).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("Storage path contains symlink component")
        if path.is_symlink():
            raise ValueError("Storage path is a symlink")
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("Storage path escapes storage root")
        if not resolved.exists():
            raise FileNotFoundError(storage_path)
        return resolved
