# Dok OCR

Automated self-hosted document OCR workflow for uploads, metadata extraction, review, and search.

![React](https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-search%20%2B%20data-4169e1?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-workers-37814a)
![OCR](https://img.shields.io/badge/OCR-PaddleOCR--VL%20%7C%20PP--OCRv6%20%7C%20GLM-7c3aed)
![i18n](https://img.shields.io/badge/UI-English%20%2F%20German-0f766e)

Dok OCR automatically turns PDFs and scanned documents into searchable records. It runs OCR, extracts metadata, generates titles, routes exceptions for review, and keeps documents organized as collections, records, and files.

It is built around a `Collection → Record → Document` model. A document can store the original file, preview/thumbnail data, OCR text, extracted metadata, review state, events, and retry/reprocessing settings.

## Why it is useful

- Runs as a normal Docker app without a GPU; use `ppocrv6` for local CPU OCR or `fake` for UI/dev.
- Keeps large smart models outside the main containers, so small machines can run the web app and workers while LM Studio, llama.cpp, or another endpoint runs elsewhere.
- On sub-4GB machines, use `fake`/`ppocrv6`, keep OCR worker concurrency low, and put smart multimodal models on another endpoint.
- Automates the pipeline from upload to OCR, metadata extraction, title generation, search indexing, and review routing.
- Keeps manual controls for retrying OCR, re-extracting metadata, locking fields, and reviewing exceptions.

> [!IMPORTANT]
> Dok OCR handles sensitive documents. Run it only on trusted infrastructure, change default credentials, configure HTTPS at your reverse proxy, and back up PostgreSQL plus the file volume.

## Scope

The repository contains the app stack:

- React/Vite frontend
- FastAPI backend
- Celery workers and beat
- Redis
- PostgreSQL
- local file storage
- OCR provider adapters and deterministic metadata extraction

Supported OCR providers in the app configuration:

- `fake`: test/development OCR
- `ppocrv6`: local PP-OCRv6 OCR path
- `paddle_vl`: external PaddleOCR-VL-style multimodal endpoint
- `glm`: external GLM OCR fallback endpoint

Optional Qwen metadata refinement is configured separately from OCR.

## Pipeline

```mermaid
flowchart LR
  U[Upload or consume folder] --> V[Validate and store]
  V --> O[OCR]
  O --> M[Metadata and title extraction]
  M --> R[Review or complete]
  R --> S[Search index]
```

The pipeline can run automatically after upload. Review and retry controls remain available when extraction is incomplete or needs correction.

## Run locally

```bash
cd app
cp .env.example .env
# edit .env: change ADMIN_PASSWORD and SECRET_KEY
docker compose up --build
```

Prerequisites: Docker Compose and outbound network access for image, Python package, and PP-OCRv6 model downloads. The first backend build prewarms PP-OCRv6 even when you start with `OCR_PROVIDER=fake`.

Open:

- UI: <http://localhost:3001>
- API docs: <http://localhost:8001/docs>

Default development login is defined in `app/.env.example`. Change it before real use.

## OCR and model endpoints

For UI/dev without a real OCR model:

```env
OCR_PROVIDER=fake
```

For basic local OCR:

```env
OCR_PROVIDER=ppocrv6
```

For smart OCR or Qwen metadata refinement, configure external OpenAI-compatible endpoints in `.env`, for example:

```env
OCR_PROVIDER=paddle_vl
PADDLE_VL_LLAMACPP_BASE_URL=http://host.docker.internal:1234/v1
PADDLE_VL_MODEL_PATH=paddleocr-vl

LLM_METADATA_REFINEMENT_ENABLED=true
QWEN_LLAMACPP_BASE_URL=http://host.docker.internal:1234/v1
QWEN_MODEL_PATH=qwen
```

LM Studio, llama.cpp server, or another compatible service can provide these endpoints. The live server deployment uses an out-of-repo Flask smart-proxy in front of llama.cpp; that proxy is deployment-specific and is not part of the default app stack.

## Admin configuration

The Admin UI can configure collection-level OCR defaults, ingestion sources, processing hooks, integration status, and maintenance actions.

Global model endpoint setup is still environment-based. A visual setup screen for LM Studio, llama.cpp, and similar endpoints is planned.

## More documentation

Detailed setup and operations notes are in [`app/README.md`](app/README.md), including upload limits, optional converters, reverse proxy settings, migrations, tests, API routes, and the document model.
