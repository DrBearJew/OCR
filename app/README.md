# Dok OCR App Guide

This directory contains the runnable Dok OCR application: backend API, workers, frontend, database migrations, reference implementations, and local Docker Compose files.

For the project overview and runtime boundaries, start with the repository-level [`../README.md`](../README.md). This file is the implementation and operations guide for the app.

---

## 1. What this app does

Dok OCR turns uploaded or consumed files into searchable, reviewable document records.

The app pipeline is:

```text
File input
  -> validation and storage
  -> OCR / text extraction
  -> deterministic metadata extraction
  -> optional metadata/search enrichment
  -> title generation and validation
  -> review state assignment
  -> PostgreSQL search indexing
  -> record/document UI
```

The main user-facing objects are:

| Object | Purpose |
| --- | --- |
| `Collection` | A schema/config bucket such as `Eingangsrechnung`, `Ausgangsrechnung`, `Dokumente`, or a custom collection. |
| `Record` | The browseable parent row users work with. It aggregates one or more documents and has a derived status. |
| `Document` | One physical uploaded/imported file, its OCR text, metadata, review state, events, pages, and retry path. |
| `Batch` | Upload grouping and migration compatibility layer. It is not the primary user mental model. |

A document is considered complete only when file storage, OCR, metadata extraction, title persistence, required-field validation, and search indexing are done. Optional metadata enrichment can add candidates and search hints; deterministic extraction remains the baseline.

---

## 2. Directory map

```text
app/
  backend/                         FastAPI app, SQLAlchemy models, workers, tests
    app/api/                       HTTP routes
    app/config/                    Settings and collection/rule config
    app/models/                    Database model definitions
    app/prompts/                   OCR/metadata prompt templates
    app/services/                  Pipeline, OCR, metadata, search, folders, diagnostics
    app/workers/                   Celery app and task entry points
    app/tests/                     Backend regression tests
    alembic/                       Database migrations

  frontend/                        React + Vite + TypeScript UI
    src/api/                       API client
    src/components/                Shared UI components
    src/i18n/                      English/German text dictionaries
    src/pages/                     Dashboard, Records, Documents, Admin, Search, etc.
    scripts/dashboard-static-tests.mjs

  references/                      Compact TypeScript/Go/Rust ports of core rules

  docker-compose.yml               Default app stack
  docker-compose.converters.example.yml
  docker-compose.llama.example.yml
  .env.example                     Local app configuration template
```

---

## 3. Runtime architecture

The default Compose stack starts the app layer only:

| Service | Role |
| --- | --- |
| `postgres` | Main database, metadata, document events, search data. |
| `redis` | Celery broker/result backend. |
| `backend` | FastAPI API server on host port `8001`. Runs migrations on startup. |
| `worker` | General Celery worker for OCR, metadata, and maintenance queues. |
| `worker-metadata` | Dedicated metadata queue worker. |
| `worker-maintenance` | Dedicated maintenance/reconciliation queue worker. |
| `worker-beat` | Periodic scans and reconciliation tasks. |
| `frontend` | Nginx-served React app on host port `3001`; proxies `/api` to backend. |

Storage is mounted as Docker volumes:

| Volume | Use |
| --- | --- |
| `postgres-data` | PostgreSQL data. |
| `redis-data` | Redis persistence. |
| `document-storage` | Stored uploaded/imported documents, previews, thumbnails. |

The app can talk to model servers, but it does not require them for basic development. Model services can be external, or deployed through the optional `docker-compose.smart.yml` model-runtime overlay.

---

## 4. Runtime modes

Choose a mode before configuring `.env` or the Admin model setup page.

| Mode | OCR provider | Intended use |
| --- | --- | --- |
| Basic dev/test | `fake` | Fast UI/backend development with no model server. |
| Fast local OCR | `ppocrv6` | CPU/local OCR for ordinary text extraction. |
| Smart document OCR | `paddle_vl` | Strict PaddleOCR-VL through a compatible endpoint. The optional Compose overlay needs an operator-prepared image and model assets. |
| GLM OCR | `glm` | GLM multimodal OCR through a compatible endpoint. Kept as a selectable fallback provider. |

Metadata refinement is separate from OCR. The production runtime route uses LFM2.5-8B-A1B Q5_K_M behind model id `metadata`; optional Gemma rollback uses `metadata-gemma`. Existing `QWEN_*` settings and old `qwen` model aliases remain for app/runtime compatibility and do not identify the production model. For long PDFs, metadata prompts use stored page OCR rows when available so the model sees ordered page snippets instead of only a naive head/tail excerpt. See [`../deploy/metadata/README.md`](../deploy/metadata/README.md) for the pinned ik build, local JSON-schema fix, and runtime flags.

---

## 5. First-time local setup

From this directory:

```bash
cp .env.example .env
```

Edit `.env` before real use:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this
SECRET_KEY=change-this-to-a-long-random-value
OCR_PROVIDER=fake
```

Start the app:

```bash
docker compose up --build
```

Open:

| Target | URL |
| --- | --- |
| Frontend | <http://localhost:3001> |
| API docs | <http://localhost:8001/docs> |
| Health | <http://localhost:8001/api/health> |
| Readiness | <http://localhost:8001/ready> |

Stable UI sections:

```text
/dashboard
/collections
/records
/documents
/search
/processing
/failed
/schemas
/admin
/activity
```

Migrations run automatically when `backend` starts. To run them manually:

```bash
docker compose run --rm backend alembic upgrade head
```

---

## 6. Model and OCR configuration

### Basic app setup

The default app stack does not need a model server. The example environment defaults to `OCR_PROVIDER=fake`, and the local quickstart above is the recommended first run. For local OCR, select `ppocrv6` in `.env` or **Admin → Model Setup**.

### Advanced smart runtime

The optional Compose overlay is not a turnkey public install. Before starting it, configure `DOKOCR_MODEL_RUNTIME_IMAGE` in `app/.env` with an operator-supplied prepared and tested image, and provision the model files expected by that image. The repository's `deploy/model-runtime/` directory is maintainer/reference scaffolding; there is no released default image tag, and the entrypoint requires existing model files rather than downloading them on first start.

```bash
# From app/, after setting DOKOCR_MODEL_RUNTIME_IMAGE and preparing its model volume:
docker compose -f docker-compose.yml -f docker-compose.smart.yml up -d
python ../scripts/doctor-smart-runtime.py --base-url http://localhost:8092/v1
```

The app uses `http://model-runtime:8092/v1` inside Compose. The model ids are `paddleocr-vl`, `metadata`, and optional `glm`. `metadata` is LFM2.5-8B-A1B Q5_K_M; `metadata-gemma` is an optional Gemma rollback route. The detailed metadata runtime requirements are in [`../deploy/metadata/README.md`](../deploy/metadata/README.md). The PaddleOCR-VL sidecar guide is an advanced operator reference: [`../deploy/paddlevl/README-llama-swap-openvino-sidecar.md`](../deploy/paddlevl/README-llama-swap-openvino-sidecar.md).

If you already operate a compatible GPU/native/remote OpenAI-compatible endpoint, configure it in **Admin → Model Setup** and skip the overlay.

### `.env` provider keys

The important model settings are:

```env
# OCR provider: fake, ppocrv6, paddle_vl, glm
OCR_PROVIDER=paddle_vl

# PaddleOCR-VL through the Dok OCR model-runtime llama-swap endpoint.
# llama-swap only loads/unloads/proxies models; backend code owns OCR prompts and response cleanup.
PADDLE_VL_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
PADDLE_VL_MODEL_PATH=paddleocr-vl
PADDLE_VL_MMPROJ_PATH=/llm-models/paddleocr-vl-mmproj.gguf

# Fast local PP-OCRv6
PPOCRV6_TIER=medium
PPOCRV6_ENGINE=onnxruntime
PPOCRV6_DEVICE=cpu

# GLM fallback through the same Dok OCR model-runtime endpoint
GLM_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
GLM_MODEL_PATH=glm
GLM_MMPROJ_PATH=/llm-models/glm-mmproj.gguf

# Optional metadata refinement. QWEN_* names are retained for app compatibility;
# model id `metadata` is the production LFM2.5-8B-A1B Q5_K_M route.
QWEN_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
QWEN_MODEL_PATH=metadata
LLM_METADATA_REFINEMENT_ENABLED=true
LLM_REQUEST_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0
QWEN_METADATA_THINKING_ENABLED=true
```

With metadata thinking enabled, the completion cap is 4096 tokens and the runtime uses `--reasoning-budget 3072`, reserving 1024 tokens for final JSON. The metadata request timeout is at least 240 seconds; the OCR request timeout remains 120 seconds. Metadata calls ask for schema-constrained objects with `value`, `confidence`, and `evidence`; the prompt preserves company/person names verbatim and selects an invoice/issue date rather than a due date. See the metadata runtime guide for the pinned ik commit `cea2d61ffdac` and its local JSON-schema fix.

### OCR time budgets for large documents

Celery OCR task limits are page-aware instead of one fixed 600 second ceiling. The Admin **Model Setup → OCR time budget** section lets operators choose:

- minimum OCR soft/hard limits
- hard-limit and queue-lease grace seconds
- base overhead per document
- PaddleOCR-VL seconds per 4-page chunk
- GLM and PP-OCRv6 seconds per page

The PaddleOCR-VL estimate is:

```text
soft_limit = max(configured_floor, base_overhead + ceil(page_count / ocr_concurrency) * seconds_per_chunk)
hard_limit = max(configured_hard_floor, soft_limit + hard_grace)
lease = max(default_lease, hard_limit + lease_grace)
```

These are kill ceilings, not speed predictions. Users with slower CPUs or very large books can raise the values in Admin; faster hosts can lower them after benchmarking.

### Model boundary

The app calls OpenAI-compatible HTTP endpoints. It does not hardcode GPU topology, OpenVINO, llama.cpp flags, metadata model family, or model-manager behavior.

Expected endpoint shape:

```text
POST /v1/chat/completions
```

For PaddleOCR-VL and GLM image OCR, the request includes multimodal `image_url` content with a data URL. For metadata refinement, the request is text-only and expects schema-constrained JSON metadata candidates.

### Provider behavior

The OCR path is deliberately conservative and explicit:

- PaddleOCR-VL is the strict smart OCR path when `ocr_engine = paddle_vl`.
- PP-OCRv6 is available as a separate fast/local OCR provider.
- GLM remains available as a separate multimodal OCR provider.
- In redo mode, searchable PDFs may use a verified embedded text layer first; every selected page must meet the usable-text check, and accepted runs are traced as `pdf_text_layer`.
- Force mode always ignores the PDF text-layer fast path and runs the selected OCR provider.
- Strict PaddleOCR-VL failures are surfaced for retry/review instead of silently switching to PP-OCRv6.
- Metadata model failures should not erase deterministic metadata. Empty model output is treated as no candidate; malformed non-empty JSON is recorded for review/diagnostics.

---

## 7. Upload and ingestion limits

Large PDFs and multi-file batches are normal inputs. There are two gates.

### Frontend Nginx gate

`frontend/nginx.conf` sets request size and proxy behavior. If Nginx rejects a request first, the frontend catches HTTP `413` and shows a friendly upload-size message.

To verify the live Nginx body limit:

```bash
docker compose exec frontend nginx -T | grep client_max_body_size
```

### Backend validation gate

`.env` controls backend upload validation:

```env
MAX_UPLOAD_FILE_SIZE_MB=200
MAX_UPLOAD_BATCH_SIZE_MB=500
MAX_UPLOAD_FILES_PER_BATCH=50
MAX_PDF_PAGES=100
ALLOWED_EXTENSIONS=pdf,png,jpg,jpeg,webp,tif,tiff,txt,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp,rtf,eml,msg
ALLOWED_MIME_TYPES=application/pdf,image/png,image/jpeg,image/webp,image/tiff,text/plain,...
```

Office and email files require converters. If converters are disabled, those uploads fail cleanly with a user-visible validation error.

### Consume folder

The default stack mounts:

```text
./consume -> /data/consume
```

Use the Admin UI to create/enable consume-folder ingestion sources before dropping files there. Celery beat scans enabled sources and creates ingestion jobs/documents.

---

## 8. Optional converters

Converters are intentionally outside the default stack.

Start example converter services:

```bash
docker compose -f docker-compose.yml -f docker-compose.converters.example.yml --profile converters up --build
```

Enable them:

```env
CONVERTERS_ENABLED=true
TIKA_BASE_URL=http://tika:9998
GOTENBERG_BASE_URL=http://gotenberg:3000
```

Use converters for Office documents and email formats. Native PDF/image/text processing does not require them.

---

## 9. Document lifecycle

The main document workflow states are:

```text
uploaded
  -> queued_for_ocr
  -> ocr_processing
  -> ocr_done
  -> metadata_processing
  -> complete
```

Other terminal/special states:

```text
needs_review
failed
duplicate
```

Stage fields track finer-grained progress:

| Field | Meaning |
| --- | --- |
| `ocr_state` | OCR stage: pending, processing, done, skipped, failed. |
| `metadata_state` | Metadata stage: pending, processing, done, skipped, failed. |
| `review_state` | Human review state: unreviewed, needs_review, reviewed. |
| `processing_state` | Overall workflow state shown in status badges. |
| `final_state` | Last derived terminal/visible workflow state. |

Review is first-class. Marking a document as reviewed updates review metadata and promotes a review-only `needs_review` workflow state back to `complete`. Failed/OCR/queued states are not hidden by review actions.

---

## 10. Metadata, titles, and review warnings

The deterministic extraction source of truth is:

```text
backend/app/services/extraction.py
```

Supported built-in title patterns include:

| Collection | Title shape |
| --- | --- |
| `Belege` | `<Ersteller>_B_<MM/YY>_<Betrag>_<Zahlart>` |
| `Eingangsrechnung` | `<Absender>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>` |
| `Ausgangsrechnung` | `<Empfaenger>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>` |
| `Dokumente` | General document title fallback. |

Fallbacks are conservative, for example `Dok`, `NA`, `00/00`, and `00/00/0000`.

Manual edits and locks are respected:

- `metadata_locked` protects current metadata from normal reprocessing.
- Field-level locks protect individual fields.
- Forced processing can overwrite where explicitly allowed.
- Metadata refinement can propose fields or search metadata, but deterministic extraction and manual locks remain authoritative.

Review warnings are generated for missing required fields, weak/invalid title schema, OCR/model failures, duplicate signals, or other pipeline concerns. They are stored on the document and surfaced in the UI, filters, diagnostics, and activity trail.

---

## 11. Search and indexing

Search is PostgreSQL-backed and uses stored OCR/metadata.

Search covers:

- full OCR text
- generated/manual title
- collection
- workflow state
- review state
- date range
- filename/title filters
- correspondent
- document type
- tags
- storage path
- OCR mode
- searchable custom fields

The pipeline records a `search_indexed` marker after OCR and metadata are available. Diagnostics treat OCR text with completed/skipped OCR as implicitly searchable even if an older row lacks the marker.

Searchable PDF fast path: `OCR_PDF_TEXT_LAYER_AUTO_ENABLED=true` lets redo-mode OCR accept an embedded PDF text layer only when the text is usable across every selected page. It rejects suspicious/control-heavy text, records `ocr_pdf_text_layer_used`, and falls back to the selected OCR provider when rejected. Use OCR force mode to run the selected model regardless of embedded text.

---

## 12. Admin areas

The Admin UI is the technical configuration area for:

- model setup and endpoint tests
- OCR provider/default settings
- collections and schema metadata
- correspondents, document types, tags, storage paths
- ingestion sources and ingestion jobs
- command/webhook hooks
- failed jobs and retries
- reconciliation tasks

The backend owns prompts, decode parameters, PDF text-layer checks, and response cleanup; llama-swap only handles model load/unload/proxying. Legacy `QWEN_*` setting names and `qwen` aliases are compatibility plumbing, not the identity of the production LFM2.5 metadata model.

---

## 13. API map

The complete interactive API reference is available at:

```text
http://localhost:8001/docs
```

High-level route groups:

| Route group | Purpose |
| --- | --- |
| `/api/auth/*` | Login/session. |
| `/api/batches/*` | Upload grouping and upload endpoints. |
| `/api/collections/*` | Collections and custom field definitions. |
| `/api/records/*` | Record list/detail, record processing, shared title metadata. |
| `/api/documents/*` | Document detail, patch, bulk actions, OCR/reextract/retry, previews, diagnostics. |
| `/api/search` | Full text and metadata search. |
| `/api/admin/*` | Operational/admin configuration and recovery actions. |
| `/api/dashboard`, `/api/processing`, `/api/failed`, `/api/activity` | App shell summary pages. |
| `/health`, `/ready` | Health/readiness probes. |

Prefer the generated OpenAPI docs for exact payload shapes, because route payloads evolve faster than a static endpoint list.

---

## 14. Development workflow

### Backend tests

From the app directory with Compose:

```bash
docker compose run --rm \
  -e LLM_METADATA_REFINEMENT_ENABLED=false \
  -e COMMAND_HOOKS_ALLOWED_COMMANDS=python,python3,python3.12 \
  backend sh -lc "PYTHONPATH=/app pytest app/tests -q"
```

Focused examples:

```bash
docker compose run --rm backend sh -lc "PYTHONPATH=/app pytest app/tests/test_processing.py -q"
docker compose run --rm backend sh -lc "PYTHONPATH=/app pytest app/tests/test_model_prompts.py -q"
docker compose run --rm backend sh -lc "PYTHONPATH=/app pytest app/tests/test_app_shell.py -q"
```

### Frontend checks

```bash
cd frontend
npm ci
npm run build
npm run test:dashboard
```

Or from the app directory:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine \
  sh -lc "npm ci >/tmp/npm-ci.log 2>&1 && npm run test:dashboard"
```

### Rebuild and restart

```bash
docker compose build backend frontend
docker compose up -d backend frontend
```

### Useful logs

```bash
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f worker-metadata
docker compose logs -f frontend
```

---

## 15. Operations and recovery

### Reconcile stuck work

Celery beat periodically runs reconciliation. Manual command:

```bash
docker compose run --rm backend python -m app.cli reconcile-stuck
```

### Retry failures

```bash
docker compose run --rm backend python -m app.cli retry-failed
```

### Re-extract a collection

```bash
docker compose run --rm backend python -m app.cli reextract-collection Eingangsrechnung --force
```

### Rebuild search metadata

```bash
docker compose run --rm backend python -m app.cli rebuild-search
```

### Import/export legacy data

```bash
docker compose run --rm backend python -m app.cli import-legacy \
  --files-dir /path/to/files \
  --metadata /path/to/export.json \
  --collection Belege \
  --legacy-source paperless

docker compose run --rm backend python -m app.cli export-documents --out /tmp/documents.json
```

Legacy import supports folder files plus CSV/JSON metadata/OCR exports. Useful fields include `filename`, `original_path`, `legacy_document_id`, `collection`, `title`, `metadata_json`, `raw_ocr_json`, `ocr_text`, and `mime_type`.

---

## 16. HTTPS and reverse proxy

The containers serve HTTP internally. Terminate HTTPS at your reverse proxy and forward to the frontend container.

Recommended deployment settings:

```env
PUBLIC_BASE_URL=https://docs.example.local
API_BASE_URL=/api
COOKIE_SECURE=true
CORS_ORIGINS=https://docs.example.local
TRUSTED_PROXY_HEADERS=true
```

Keep external links and integrations on the public base URL. Avoid hardcoding localhost outside Docker/dev.

---

## 17. Troubleshooting guide

| Symptom | Check |
| --- | --- |
| Upload fails before backend logs appear | Nginx body limit or proxy timeout. Inspect `frontend/nginx.conf` and `nginx -T`. |
| Upload accepted but document never processes | Worker/Redis health, Celery queue logs, `processing_task_id`, `lease_until`, reconciliation status. |
| OCR returns empty or noisy text | Check the selected provider, endpoint, rendered page images, and provider error events. A known limitation is that the single-image PaddleOCR-VL adapter can append instruction text on very short synthetic images; this was reproduced on both the original and new deployment. A raw native task-cue smoke returned the expected test text, but that does not prove the full adapter/pipeline path is flawless. |
| Metadata looks wrong | Check OCR text first, then deterministic extraction, then metadata candidates/sources. |
| Status says `needs_review` after action | Compare `processing_state` and `review_state`; review-only states should promote to `complete` when marked reviewed. |
| Metadata sidecar shows failed but document is complete | Inspect diagnostics. Empty model output is optional/no-candidate; malformed non-empty JSON is a real metadata candidate failure. |
| Office/email files are rejected | Enable Tika/Gotenberg converters and set `CONVERTERS_ENABLED=true`. |
| Browser still shows old UI | Rebuild/restart `frontend`, then hard-refresh the browser. |

Document diagnostics are available from the document detail advanced actions and backend route:

```text
GET /api/documents/{document_id}/diagnostics
```

---

## 18. Reference implementations

The `references/` directory contains compact ports of core extraction/state logic in TypeScript, Go, and Rust. They preserve business rules for future services and test comparisons; they are not alternate production apps.
