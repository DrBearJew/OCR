# Dok OCR Application & Developer Guide

This directory holds the Dok OCR application: FastAPI backend, Celery workers, React frontend, Alembic migrations, reference rule ports, and development Compose files.

Looking to deploy with prebuilt Docker images? Use [`../docs/INSTALL.md`](../docs/INSTALL.md). This guide covers building from source, architecture, configuration, tests, and day-to-day operations.

## Pipeline & data model

Every uploaded or consumed file moves through:

```text
Input → Storage → OCR (or verified PDF text) → Deterministic metadata → Optional LLM refinement → Title & validation → Review state → PostgreSQL search
```

Core entities:

| Entity | Role |
| --- | --- |
| `Collection` | Document category (`Eingangsrechnung`, `Ausgangsrechnung`, `Belege`, `Dokumente`, or custom) with schema, title rules, and OCR defaults. |
| `Record` | Browsable parent entry grouping one or more documents, with a derived status. |
| `Document` | Individual file plus previews, OCR text, metadata, events, pages, and retry state. |
| `Batch` | Upload grouping and legacy compatibility layer. |

A document reaches `complete` once storage, OCR, metadata extraction, title generation, required-field validation, and search indexing succeed. Optional LLM refinement proposes candidates; deterministic extraction and manual field locks stay authoritative.

## Directory layout

```text
app/
  backend/
    app/api/          FastAPI routes
    app/config/       Settings and collection rules
    app/models/       SQLAlchemy models
    app/prompts/      OCR and metadata prompt templates
    app/services/     Pipeline, OCR providers, metadata, search, folders, diagnostics
    app/workers/      Celery app and tasks
    app/tests/        Backend test suite
    alembic/          Database migrations
  frontend/
    src/api/          API client
    src/components/   Shared UI components
    src/i18n/         English / German strings
    src/pages/        Dashboard, Records, Documents, Search, Admin, etc.
  references/         Compact TypeScript, Go, and Rust ports of extraction rules
  docker-compose.yml
  docker-compose.smart.yml
  docker-compose.converters.example.yml
  docker-compose.llama.example.yml
  .env.example
```

## Local development quickstart

The development Compose stack builds from source and defaults to `OCR_PROVIDER=fake` in `.env.example` so you can work on the UI and API without running OCR models.

```bash
cp .env.example .env
# Set ADMIN_PASSWORD and SECRET_KEY in .env (change OCR_PROVIDER to ppocrv6 for real local OCR)
docker compose up --build
```

Services started by `docker-compose.yml`:

| Service | Role |
| --- | --- |
| `postgres` | Database, document events, and full-text search (bound to `127.0.0.1:5432`) |
| `redis` | Celery broker and locks (bound to `127.0.0.1:6379`) |
| `backend` | FastAPI server on `http://localhost:8001` (runs migrations on start) |
| `worker` | General Celery worker |
| `worker-metadata` | Metadata queue worker |
| `worker-maintenance` | Maintenance and reconciliation worker |
| `worker-beat` | Scheduled consume-folder scans and reconciliation |
| `frontend` | Nginx + React app on `http://localhost:3001` (proxies `/api` to backend) |

Endpoints:

- UI: <http://localhost:3001>
- OpenAPI docs: <http://localhost:8001/docs>
- Health / Readiness: <http://localhost:8001/api/health>, <http://localhost:8001/ready>

Run migrations manually if needed:

```bash
docker compose run --rm backend alembic upgrade head
```

## OCR and model configuration

### Providers

| Provider | Use case |
| --- | --- |
| `fake` | Fast UI/backend development with no model server |
| `ppocrv6` | Local CPU OCR via ONNX Runtime |
| `paddle_vl` | Multimodal OCR via PaddleOCR-VL (OpenAI-compatible endpoint) |
| `glm` | Optional multimodal fallback via GLM-OCR |

Provider rules:

- When `OCR_PDF_TEXT_LAYER_AUTO_ENABLED=true`, redo-mode runs may use an embedded PDF text layer if every selected page passes usable-text checks (recorded as `pdf_text_layer`). Force mode always runs the selected OCR provider.
- Strict `paddle_vl` failures surface for retry/review instead of silently falling back to `ppocrv6`.
- Metadata model errors never wipe deterministic metadata; empty output is treated as no candidate, while malformed JSON is flagged in diagnostics.

### Optional `model-runtime` overlay

If you maintain a custom multi-model `llama-swap` image (see [`../deploy/model-runtime/README.md`](../deploy/model-runtime/README.md)), set `DOKOCR_MODEL_RUNTIME_IMAGE` in `.env`, populate the model volume, and start:

```bash
docker compose -f docker-compose.yml -f docker-compose.smart.yml up -d
python ../scripts/doctor-smart-runtime.py --base-url http://localhost:8092/v1
```

Inside Compose, app services reach the gateway at `http://model-runtime:8092/v1` with model IDs `paddleocr-vl`, `metadata` (LFM2.5-8B-A1B Q5_K_M), optional `metadata-gemma`, and optional `glm`. If you already run an OpenAI-compatible server, skip the overlay and configure it in **Admin → Model Setup**.

### Key `.env` variables

```env
# OCR provider: fake, ppocrv6, paddle_vl, glm
OCR_PROVIDER=paddle_vl

PADDLE_VL_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
PADDLE_VL_MODEL_PATH=paddleocr-vl
PADDLE_VL_MMPROJ_PATH=/llm-models/paddleocr-vl-mmproj.gguf

PPOCRV6_TIER=medium
PPOCRV6_ENGINE=onnxruntime
PPOCRV6_DEVICE=cpu

GLM_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
GLM_MODEL_PATH=glm
GLM_MMPROJ_PATH=/llm-models/glm-mmproj.gguf

# Metadata refinement (QWEN_* names are kept for compatibility; model id `metadata` is LFM2.5)
QWEN_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
QWEN_MODEL_PATH=metadata
LLM_METADATA_REFINEMENT_ENABLED=true
LLM_REQUEST_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0
QWEN_METADATA_THINKING_ENABLED=true
```

With thinking enabled, metadata requests use a 4096-token cap (`--reasoning-budget 3072`, reserving 1024 tokens for final JSON) and a 240-second minimum timeout. For multi-page PDFs, metadata prompts pull ordered per-page OCR rows when available. See [`../deploy/metadata/README.md`](../deploy/metadata/README.md) for the pinned LFM build and JSON-schema patch.

### OCR time budgets

Celery task timeouts scale by page count and can be tuned in **Admin → Model Setup → OCR time budget**:

```text
soft_limit = max(floor, base_overhead + ceil(page_count / ocr_concurrency) * seconds_per_chunk)
hard_limit = max(hard_floor, soft_limit + hard_grace)
lease      = max(default_lease, hard_limit + lease_grace)
```

Adjust these ceilings up for slower CPUs or large PDFs, or down on faster hosts.

## Uploads, consume folder, and converters

Two limits apply to uploads:

1. **Nginx (`frontend/nginx.conf`):** Check the active body limit with `docker compose exec frontend nginx -T | grep client_max_body_size`. HTTP `413` responses are surfaced in the UI.
2. **Backend (`.env`):** `MAX_UPLOAD_FILE_SIZE_MB` (default `200`), `MAX_UPLOAD_BATCH_SIZE_MB` (`500`), `MAX_UPLOAD_FILES_PER_BATCH` (`50`), `MAX_PDF_PAGES` (`100`), `ALLOWED_EXTENSIONS`, and `ALLOWED_MIME_TYPES`.

**Consume folder:** `./consume` mounts to `/data/consume`. Enable a consume ingestion source in the Admin UI so Celery beat picks up new files.

**Office & email converters (optional):** PDF, image, and plain-text files work without converters. For Office and email formats (`.docx`, `.xlsx`, `.eml`, `.msg`, etc.), start Tika and Gotenberg:

```bash
docker compose -f docker-compose.yml -f docker-compose.converters.example.yml --profile converters up --build
```

Then enable them in `.env`:

```env
CONVERTERS_ENABLED=true
TIKA_BASE_URL=http://tika:9998
GOTENBERG_BASE_URL=http://gotenberg:3000
```

## Document lifecycle & metadata rules

Workflow states:

```text
uploaded → queued_for_ocr → ocr_processing → ocr_done → metadata_processing → complete
```

Special states: `needs_review`, `failed`, `duplicate`. Individual stage fields (`ocr_state`, `metadata_state`, `review_state`, `processing_state`, `final_state`) track granular progress. Marking a review-only document as reviewed promotes it to `complete` without masking failed or active tasks.

Deterministic extraction lives in `backend/app/services/extraction.py`. Built-in title patterns:

| Collection | Title format |
| --- | --- |
| `Belege` | `<Ersteller>_B_<MM/YY>_<Betrag>_<Zahlart>` |
| `Eingangsrechnung` | `<Absender>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>` |
| `Ausgangsrechnung` | `<Empfaenger>_<Rechnungsnummer>_<DD/MM/YYYY>_<Betrag>` |
| `Dokumente` | General fallback (`Dok`, `NA`, `00/00`, `00/00/0000`) |

`metadata_locked` and field-level locks prevent normal reprocessing from overwriting manual edits. Review warnings surface missing required fields, weak titles, duplicates, and model errors.

## API overview

Full interactive schemas live at <http://localhost:8001/docs>. Main route groups:

- `/api/auth/*` — authentication and sessions
- `/api/batches/*` — uploads and batch grouping
- `/api/collections/*` — collections and custom field schemas
- `/api/records/*` — record views, processing, and shared metadata
- `/api/documents/*` — document details, edits, bulk actions, OCR/re-extract/retry, previews, diagnostics (`GET /api/documents/{id}/diagnostics`)
- `/api/search` — PostgreSQL full-text and metadata search
- `/api/admin/*` — model setup, taxonomies, ingestion sources, hooks, and recovery
- `/health`, `/ready` — liveness and readiness probes

## Testing & development workflow

Backend tests:

```bash
docker compose run --rm \
  -e LLM_METADATA_REFINEMENT_ENABLED=false \
  -e COMMAND_HOOKS_ALLOWED_COMMANDS=python,python3,python3.12 \
  backend sh -lc "PYTHONPATH=/app pytest app/tests -q"
```

Frontend build and static checks:

```bash
cd frontend
npm ci
npm run build
npm run test:dashboard
```

Rebuild and inspect logs:

```bash
docker compose build backend frontend && docker compose up -d backend frontend
docker compose logs -f backend worker worker-metadata frontend
```

## CLI maintenance & recovery

```bash
# Reconcile stuck tasks
docker compose run --rm backend python -m app.cli reconcile-stuck

# Retry failed jobs
docker compose run --rm backend python -m app.cli retry-failed

# Re-extract a collection
docker compose run --rm backend python -m app.cli reextract-collection Eingangsrechnung --force

# Rebuild search index metadata
docker compose run --rm backend python -m app.cli rebuild-search

# Import from Paperless / legacy folder + export
docker compose run --rm backend python -m app.cli import-legacy \
  --files-dir /path/to/files \
  --metadata /path/to/export.json \
  --collection Belege \
  --legacy-source paperless

# Export documents
docker compose run --rm backend python -m app.cli export-documents --out /tmp/documents.json
```

## Reverse proxy (HTTPS)

Terminate TLS at your reverse proxy and forward traffic to the `frontend` container with:

```env
PUBLIC_BASE_URL=https://docs.example.local
API_BASE_URL=/api
COOKIE_SECURE=true
CORS_ORIGINS=https://docs.example.local
TRUSTED_PROXY_HEADERS=true
```

## Troubleshooting

| Symptom | Where to look |
| --- | --- |
| Upload fails before hitting backend | Nginx `client_max_body_size` or proxy timeout in `frontend/nginx.conf`. |
| Uploaded document never starts | Worker and Redis health, Celery logs, `processing_task_id`, `lease_until`, or run `reconcile-stuck`. |
| Empty or noisy OCR text | Selected provider, model endpoint logs, rendered page previews, and `GET /api/documents/{id}/diagnostics`. |
| Unexpected metadata | Inspect OCR text first, then deterministic extraction and candidate sources in diagnostics. |
| Stays in `needs_review` | Check both `processing_state` and `review_state`; review-only documents promote to `complete` once approved. |
| Office/email upload rejected | Start the Tika/Gotenberg converters and set `CONVERTERS_ENABLED=true`. |
| Stale UI after changes | Rebuild/restart `frontend` and hard-refresh the browser. |

See [`references/README.md`](references/README.md) for the standalone TypeScript/Go/Rust extraction rule ports.
