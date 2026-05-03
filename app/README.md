# Dok OCR

Self-hosted document processing app for multi-file upload, external llama.cpp-backed GLM OCR, optional Qwen metadata refinement, local file storage, and PostgreSQL full-text search.

## Stack

- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL
- Worker: Celery, Redis
- Frontend: React, Vite, TypeScript
- Storage: local filesystem volume
- OCR: GLM OCR through an external llama.cpp OpenAI-compatible multimodal server
- Text reasoning: optional Qwen through a separate external llama.cpp server
- Search: PostgreSQL full-text search over full OCR text

## Setup

```powershell
cd "C:\Users\Trent\Documents\New project\app"
Copy-Item .env.example .env
```

Edit `.env` before real use:

- change `ADMIN_PASSWORD`
- change `SECRET_KEY`
- set `OCR_PROVIDER=glm` when your llama.cpp OCR server is ready

## External llama.cpp Model Layer

This app does not install, own, or mutate llama.cpp. Keep existing llama.cpp containers, ports, model mounts, GPU mapping, aliases, and reverse-proxy routes stable. The app is only an HTTP client.

Example environment:

```env
OCR_PROVIDER=glm
GLM_LLAMACPP_BASE_URL=http://glm-llama:8080
GLM_MODEL_PATH=/llm-models/glm.gguf
GLM_MMPROJ_PATH=/llm-models/glm-mmproj.gguf

QWEN_LLAMACPP_BASE_URL=http://qwen-llama:8080
QWEN_MODEL_PATH=/llm-models/qwen.gguf
LLM_METADATA_REFINEMENT_ENABLED=false
```

Expected model split:

- `glm.gguf` + `glm-mmproj.gguf`: multimodal OCR and visual document reading
- `qwen.gguf`: optional metadata refinement, title suggestions, search assistance, and admin/debug text reasoning

If you need a fresh example only, see `docker-compose.llama.example.yml`. It is opt-in and intentionally separate from the default app Compose file.

Example GLM server shape:

```bash
llama-server -m /llm-models/glm.gguf --mmproj /llm-models/glm-mmproj.gguf --host 0.0.0.0 --port 8080
```

The adapter posts to:

```text
POST /v1/chat/completions
```

with multimodal `image_url` content containing a data URL for the uploaded file. For development and automated tests, keep `OCR_PROVIDER=fake`.

Prompts are real files under `backend/app/prompts/`. Collection/OCR rules are YAML files under `backend/app/config/`. Prompt output can assist, but deterministic extraction and title validation remain the final authority.

## Optional Converters

Office documents and email files are accepted only when external converters are enabled. They are not part of the default stack.

Example only:

```powershell
docker compose -f docker-compose.yml -f docker-compose.converters.example.yml --profile converters up --build
```

Then set:

```env
CONVERTERS_ENABLED=true
TIKA_BASE_URL=http://tika:9998
GOTENBERG_BASE_URL=http://gotenberg:3000
```

If converters are disabled, Office/email uploads and consume-folder imports fail cleanly with a user-visible validation error.

## Start Services

```powershell
docker compose up --build
```

The default Compose file starts only the app layer: Postgres, Redis, backend, worker, Celery beat, and frontend. External llama.cpp services stay outside this stack unless you deliberately run the separate example file.

The default stack also mounts `./consume` into backend, worker, and beat as `/data/consume` for optional consume-folder polling. Put files there only after you create and enable a consume-folder ingestion source in the Admin UI.

Open:

- UI: `http://localhost:3001`
- API docs: `http://localhost:8001/docs`
- Stable UI routes: `/dashboard`, `/collections`, `/records`, `/documents`, `/search`, `/processing`, `/failed`, `/schemas`, `/admin`, `/activity`

## Upload Limits

Large PDFs and multi-file batches are normal inputs. The app has two upload gates:

- Frontend Nginx: `frontend/nginx.conf` sets `client_max_body_size 250m` at `server` and `/api/`, disables request buffering for `/api/`, and raises proxy timeouts to 300 seconds.
- Backend FastAPI: validates every batch before and during streaming.

Backend limits in `.env`:

```env
MAX_UPLOAD_FILE_SIZE_MB=200
MAX_UPLOAD_BATCH_SIZE_MB=500
MAX_UPLOAD_FILES_PER_BATCH=50
MAX_PDF_PAGES=100
ALLOWED_EXTENSIONS=pdf,png,jpg,jpeg,webp,tif,tiff
ALLOWED_MIME_TYPES=application/pdf,image/png,image/jpeg,image/webp,image/tiff
```

Nginx config files do not automatically read `.env`. To change the Nginx body limit, update `frontend/nginx.conf`, rebuild/reload the frontend container, then verify inside the container with:

```sh
nginx -T | grep client_max_body_size
```

If Nginx rejects a request before FastAPI sees it, the frontend catches HTTP 413 and shows a friendly upload-size message instead of raw Nginx HTML.

Default login from `.env.example`:

- username: `admin`
- password: `admin`

## HTTPS / Reverse Proxy

The containers serve HTTP internally. Terminate HTTPS in your existing reverse proxy and forward to the frontend container. API calls remain under `/api`, and Nginx forwards proxy headers to the backend.

Useful deployment config:

```env
PUBLIC_BASE_URL=https://docs.example.local
API_BASE_URL=/api
COOKIE_SECURE=true
CORS_ORIGINS=https://docs.example.local
TRUSTED_PROXY_HEADERS=true
```

Do not hardcode localhost in integrations or automations; use the public base URL when linking to the app from outside Docker.

## Migrations

Migrations run automatically in the backend container on startup.

Manual migration:

```powershell
docker compose run --rm backend alembic upgrade head
```

## Running Tests

Backend:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m pytest app/tests
```

Frontend build:

```powershell
cd frontend
npm install
npm run build
```

Reference implementations:

```powershell
cd references/typescript
npm install
npm test

cd ../go
go test ./...

cd ../rust
cargo test
```

## Collection / Record / Document Model

The user-facing model is now:

- `Collection`: schema bucket such as Belege, Eingangsrechnung, Ausgangsrechnung, Dokumente, or future custom collections.
- `Record`: PocketBase-like parent row users browse in the main list. A record owns one or many documents and has derived status/summary metadata.
- `Document`: one uploaded file, one first-class row, one OCR text, one metadata/title state, one retry path, one audit trail.

The legacy `batches` table remains as an upload grouping and migration compatibility layer. It is not the main user mental model.

The browser UI is a PocketBase-like app shell with separate sections for Dashboard, Collections, Records, Documents, Search, Processing, Failed/Review, Schemas, Admin, and Activity. The same objects are available through JSON APIs; the UI does not have private-only behavior.

Custom fields are schema-driven:

- Definitions live per collection in `custom_field_definitions`.
- Values live per document in `document_custom_field_values`.
- Supported field types: string, text, number, date, boolean, select.
- Values record source, confidence, lock state, raw value, and normalized value.
- Locked values are not overwritten unless force is used.

## Paperless-Like Ingestion And OCR Pipeline

The app has a Paperless-inspired consumer layer without copying Paperless internals:

- Uploads remain interactive and create one record per upload batch.
- Consume-folder sources are polled by Celery beat and default to one record per file.
- Every discovered file creates exactly one document row, unless it is skipped as an already-imported hash.
- OCR modes are explicit: `skip`, `redo`, and `force`.
- Effective OCR config is resolved from app defaults, collection config, source/document config, and document overrides.
- Pipeline events are visible per document: validation, storage, dedupe, hooks, render/thumbnail, OCR, metadata, search indexing, and completion.

OCR settings available in `.env` include language, cleanup mode, deskew, rotation, page limit, image DPI, output type, max image pixels, and default OCR mode. GLM receives these as pipeline context/trace for v1; final deterministic extraction remains code/config driven.

Pre/post consume hooks can be command or webhook hooks. Blocking hook failures fail the document/job; non-blocking hook failures are recorded as document events.

## API Overview

- `POST /api/auth/login`
- `GET /api/collections`
- `POST /api/collections`
- `PATCH /api/collections/{id}`
- `GET /api/collection-summaries`
- `GET /api/collection-pages/{slug}`
- `GET /api/collections/{id}/fields`
- `POST /api/collections/{id}/fields`
- `PATCH /api/collections/{id}/fields/{field_id}`
- `DELETE /api/collections/{id}/fields/{field_id}`
- `GET /api/records`
- `GET /api/records/{id}`
- `PATCH /api/records/{id}`
- `POST /api/batches/upload`
- `GET /api/batches`
- `GET /api/batches/{id}`
- `GET /api/documents?collection_name=...&state=...&review_state=...&filename=...&title=...&correspondent_id=...&document_type_id=...&tag_id=...&storage_path_id=...&ocr_mode=...`
- `GET /api/documents/{id}`
- `PATCH /api/documents/{id}`
- `POST /api/documents/bulk`
- `POST /api/documents/{id}/retry`
- `POST /api/documents/{id}/reextract`
- `GET /api/documents/{id}/download`
- `GET /api/documents/{id}/preview`
- `GET /api/documents/{id}/thumbnail`
- `GET /api/documents/{id}/events`
- `GET /api/documents/{id}/pages`
- `PATCH /api/documents/{id}/ocr-settings`
- `POST /api/documents/{id}/ocr`
- `GET /api/documents/{id}/pipeline`
- `GET /api/documents/{id}/custom-fields`
- `PUT /api/documents/{id}/custom-fields`
- `GET /api/documents/duplicates`
- `GET /api/search?q=...&collection_name=...&status=...&review_state=...&filename=...&title=...&date_from=...&date_to=...&custom_field=...&custom_value=...&correspondent_id=...&document_type_id=...&tag_id=...&storage_path_id=...&ocr_mode=...`
- `GET /api/dashboard`
- `GET /api/activity`
- `GET /api/processing`
- `GET /api/failed`
- `GET /api/saved-views`
- `POST /api/saved-views`
- `PATCH /api/saved-views/{id}`
- `DELETE /api/saved-views/{id}`
- `GET /api/admin/jobs`
- `GET /api/admin/failed`
- `GET /api/admin/integrations`
- `POST /api/admin/reconcile`
- `POST /api/admin/retry-failed`
- `POST /api/admin/reextract-collection`
- `GET /api/admin/ingestion-sources`
- `POST /api/admin/ingestion-sources`
- `PATCH /api/admin/ingestion-sources/{source_id}`
- `POST /api/admin/ingestion-sources/{source_id}/scan`
- `POST /api/admin/ingestion-sources/scan-all`
- `GET /api/admin/ingestion-jobs`
- `POST /api/admin/ingestion-jobs/{job_id}/retry`
- `GET /api/admin/hooks`
- `POST /api/admin/hooks`
- `POST /api/admin/hooks/{hook_id}/test`
- `GET /api/admin/correspondents`
- `POST /api/admin/correspondents`
- `GET /api/admin/document-types`
- `POST /api/admin/document-types`
- `GET /api/admin/tags`
- `POST /api/admin/tags`
- `GET /api/admin/storage-paths`
- `POST /api/admin/storage-paths`
- `GET /health`
- `GET /ready`

## Processing Rules

One uploaded file always creates one `documents` row. A batch is only a grouping record and never stores merged OCR. A document becomes `complete` only after OCR and metadata extraction both finish.

Document states:

```text
uploaded -> queued_for_ocr -> ocr_processing -> ocr_done -> metadata_processing -> complete
failed
duplicate
```

Batch status is derived from child documents:

```text
pending
processing
partially_failed
complete
```

## Extraction Rules

The source of truth is `backend/app/services/extraction.py`.

Supported collections:

- `Belege`: `<Ersteller>_B_<MM/YY>_<Betrag>_<Zahlart>`
- `Eingangsrechnung`: `<Absender>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>`
- `Ausgangsrechnung`: `<Empfaenger>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>`

Fallbacks are conservative: `Dok`, `NA`, `00/00`, `00/00/0000`.

Manual metadata edits are supported. When `metadata_locked` is true, reprocessing records a candidate result in debug metadata but does not overwrite current manual/extracted values unless `force=true`.

Each document also stores prompt/model trace JSON, optional Qwen response text, and a processing log for reproducibility.

## Operational Hardening

- Processing is idempotent: duplicate OCR/metadata task delivery is guarded by document state and heartbeat checks.
- Celery beat runs `reconcile_stuck_documents_task` every five minutes to requeue stale `uploaded`, `queued_for_ocr`, `ocr_processing`, `ocr_done`, and `metadata_processing` rows.
- Failed documents are retryable from the admin UI, CLI, or `POST /api/admin/retry-failed`.
- Duplicate uploads are detected by SHA-256. The new row is kept for auditability, linked with `duplicate_of_document_id`, and not reprocessed unless force retried.
- Upload validation enforces file extension, MIME type, max file size, and max PDF pages. A virus-scan hook is present as a v1 extension point.
- Images and PDFs can get thumbnails; PDFs are inspected/rendered with `pypdfium2`, thumbnails use `Pillow`.
- Per-document events are stored in `document_events`; optional page OCR fragments live in `document_pages`.
- Search remains database-backed and includes snippets plus filters for collection, state, date range, filename, title, correspondent, document type, tag, storage path, OCR mode, and searchable custom fields.
- Review state is first-class on documents: `unreviewed`, `needs_review`, and `reviewed`, with reason, reviewer, timestamp, filters, audit events, and bulk update support.
- Saved views store reusable filter/sort/display JSON for Records, Documents, Search, Processing, and Failed/Review.

## Admin CLI

Run these inside the backend environment:

```powershell
python -m app.cli retry-failed
python -m app.cli reconcile-stuck
python -m app.cli reextract-collection Eingangsrechnung --force
python -m app.cli rebuild-search
python -m app.cli import-legacy --files-dir C:\path\to\files --metadata C:\path\to\export.json --collection Belege --legacy-source paperless
python -m app.cli export-documents --out C:\path\to\documents.json
```

Legacy import supports folder files plus CSV/JSON metadata/OCR exports. Useful fields include `filename`, `original_path`, `legacy_document_id`, `collection`, `title`, `metadata_json`, `raw_ocr_json`, `ocr_text`, and `mime_type`.

## References

The `/references` directory contains compact ports of the core extraction and state logic in TypeScript, Go, and Rust. They are meant to preserve the business rules for future services, not to rebuild the app.
