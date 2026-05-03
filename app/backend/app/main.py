from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, app_shell, auth, batches, collections, documents, folders, records, search
from app.config import get_settings, validate_production_settings
from app.db import SessionLocal
from app.services.integrations import log_startup_model_status
from app.utils.logging import configure_logging


configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(app_shell.router)
app.include_router(collections.router)
app.include_router(records.router)
app.include_router(folders.router)
app.include_router(batches.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(admin.router)


@app.on_event("startup")
def startup_checks() -> None:
    validate_production_settings(settings)
    log_startup_model_status(settings)


@app.get("/health")
def public_health() -> dict:
    return {"ok": True, "app": settings.app_name}


@app.get("/ready")
def ready() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": settings.app_name, "ocr_provider": settings.ocr_provider}
