# Dok OCR

Self-hosted document OCR, metadata extraction, review, and full-text search.

Dok OCR keeps every original file, preview, OCR transcript, extracted field, review decision, and processing log in one place. It is built for scanned documents, PDFs, receipts, and invoices, with an English and German web UI.

![React](https://img.shields.io/badge/React-19-61dafb?logo=react&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-search%20%2B%20data-4169e1?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-workers-37814a)
![OCR](https://img.shields.io/badge/OCR-PaddleOCR--VL%20%7C%20PP--OCRv6%20%7C%20OpenAI%20Vision-7c3aed)
![i18n](https://img.shields.io/badge/UI-English%20%2F%20German-0f766e)

<img src="docs/assets/dok-ocr-pipeline-hero.png" alt="Dok OCR processing flow" width="100%"/>

## Quick start (Docker)

On Linux x86_64 with Docker Engine and the Compose plugin installed:

```bash
curl -fL https://raw.githubusercontent.com/DrBearJew/OCR/main/scripts/install-docker.sh -o install-docker.sh
bash install-docker.sh
```

That gives you the full app using prebuilt images and local CPU **PP-OCRv6**—no source build, GPU, or external model server required. Open `http://127.0.0.1:3001` on first launch to pick your own admin username and password in the browser (and change them anytime under **Admin → System**).

To enable local AI models with the same installer:

```bash
# PaddleOCR-VL (OCR) + LFM2.5 (metadata) in one custom ik_llama.cpp container (auto AVX-512 / AVX2)
bash install-docker.sh --metadata-runtime unified

# Standard PP-OCRv6 + local LFM2.5 metadata on CPU, NVIDIA, Vulkan, or an external endpoint
bash install-docker.sh --metadata-runtime cpu      # or: cuda, vulkan, external

# Bring your own engine (LM Studio, llama-server, Ollama, vLLM) for both OCR and metadata
bash install-docker.sh \
  --ocr-runtime external --ocr-url http://host.docker.internal:1234/v1 --ocr-model auto \
  --metadata-runtime external --metadata-url http://host.docker.internal:1234/v1 --metadata-model auto
```

See the [Docker installation guide](docs/INSTALL.md) for hardware requirements, installer flags, HTTPS proxy setup, and troubleshooting.

## How it works

Documents flow through a transparent pipeline:

```text
Upload / Consume folder → OCR (or verified PDF text) → Metadata extraction → Review → Search
```

Everything is organized around three concepts:

```text
Collection → Record → Document
```

- **Collections** define document types (such as incoming invoices, receipts, or custom schemas), title templates, OCR defaults, and custom fields.
- **Records** group related documents under one browsable entry.
- **Documents** hold the original file, page previews, OCR text, extracted fields, processing history, and review status.

## Highlights

- **Custom CPU kernels in the unified runtime:** `--metadata-runtime unified` ships a tuned `ik_llama.cpp` image bundling **both AVX-512 and AVX2** builds with automatic CPU detection at startup—including dedicated unmasked `D=72` IQK vision-attention kernels for **both** tiers (cutting vision-attention CPU time ~8× on tested AVX-512 pages, from ~107 s to ~13 s, and cutting full-page AVX2 attention latency by **35–39% / 1.54×–1.63×** on a Ryzen 9 5900X with a zero-spill native `72`-wide packed-K/V kernel), an AVX-512 BF16 FFN tail fix, MRoPE image-grid & causal-mask fixes, and fast LFM2.5 CPU decoding—swapping models in one container so only one stays in RAM at a time.
- **Bring your own engine (LM Studio, `llama.cpp`, Ollama, vLLM):** Point OCR (`openai_vision`) and/or metadata at any OpenAI-compatible server via the installer or **Admin → Models** using one-click presets, `/v1/models` auto-detection (`auto`), and optional Bearer API keys. Note that external engines use their own GPU/CPU kernels; our custom CPU kernels live in the `unified` `ik_llama.cpp` image.
- **Flexible OCR:** Local CPU PP-OCRv6 out of the box, PaddleOCR-VL via the unified runtime, generic OpenAI-compatible vision models (`openai_vision`), and optional GLM OCR fallback. Searchable PDFs reuse their embedded text layer when every selected page passes text-quality checks, or force full OCR on demand.
- **Metadata and titles:** Deterministic extraction for titles, dates, correspondents, amounts, document types, and tags, with optional LLM refinement (**LFM2.5-8B-A1B Q5_K_M** or any external chat model). Manual edits can be locked so reprocessing never overwrites them.
- **Review and diagnostics:** Failed, duplicate, and low-confidence documents surface in dedicated queues with per-step event trails and one-click retry, force-OCR, re-extract, and search-rebuild controls.
- **Full-text search:** PostgreSQL search across OCR text, titles, dates, correspondents, tags, and custom collection fields.

## OCR runtimes

| Provider | Best for | Notes |
| --- | --- | --- |
| `ppocrv6` | Everyday CPU-only setups | Default in the Docker installer. Prewarmed in the backend image; no GPU needed. |
| `paddle_vl` | High-accuracy CPU OCR without a GPU | Included in `--metadata-runtime unified` with our custom `ik_llama.cpp` CPU kernels (auto-selects AVX-512 or AVX2 at startup). |
| `openai_vision` | LM Studio, `llama-server`, Ollama, vLLM | Works with any OpenAI-compatible multimodal vision model (`model=auto`, optional Bearer key). Uses the external engine's own GPU/CPU kernels. |
| `glm` | Secondary multimodal OCR | Optional fallback via an external OpenAI-compatible endpoint. |
| `fake` | UI and API development | Default in `app/.env.example` for fast local testing without running OCR. |

## Development setup

To build and run from source (uses `OCR_PROVIDER=fake` by default):

```bash
cd app
cp .env.example .env
# Edit .env to set ADMIN_PASSWORD and SECRET_KEY
docker compose up --build
```

Then open the UI at <http://localhost:3001> and API docs at <http://localhost:8001/docs>.

### Custom model-runtime overlay

If you maintain your own multi-model gateway image instead of using the prebuilt installer, set `DOKOCR_MODEL_RUNTIME_IMAGE` in `app/.env`, populate the `/models` volume, and run:

```bash
cd app
docker compose -f docker-compose.yml -f docker-compose.smart.yml up -d
python ../scripts/doctor-smart-runtime.py --base-url http://localhost:8092/v1
```

The `model-runtime` gateway exposes `paddleocr-vl`, `metadata` (LFM2.5-8B-A1B), optional `metadata-gemma`, and optional `glm`. Legacy `QWEN_*` environment variable names remain supported for compatibility, even though the metadata model is LFM2.5.

If you already run an OpenAI-compatible inference server, skip the overlay and configure its URL in **Admin → Model Setup**.

> [!IMPORTANT]
> Dok OCR stores sensitive documents. Change default credentials, put the app behind HTTPS on a reverse proxy, and back up both PostgreSQL and the document storage volume.

## Documentation

- [Docker installation guide](docs/INSTALL.md) — prebuilt setup, CPU/GPU/unified options, security, and upgrades.
- [Application & developer guide](app/README.md) — architecture, source builds, tests, CLI recovery, and troubleshooting.
- [Unified ik runtime](deploy/paddle-ik/README.md) — single-container PaddleOCR-VL + LFM2.5 runtime.
- [Metadata runtime](deploy/metadata/README.md) — LFM2.5 CPU/CUDA/Vulkan images, GPU controls, and JSON-schema patch.
- [Maintainer model-runtime recipe](deploy/model-runtime/README.md) — custom multi-model `llama-swap` container contract.
- [Native GLM-OCR port](deploy/glm/README.md) — optional CPU GLM-OCR patch for `ik_llama.cpp`.
