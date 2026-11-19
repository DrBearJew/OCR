# Installing Dok OCR with Docker

The Docker installer sets up Dok OCR on Linux x86_64 using prebuilt images from GitHub Container Registry—no repository clone, compiler, or manual model configuration needed.

Published images:

- `ghcr.io/drbearjew/ocr-backend:<tag>`
- `ghcr.io/drbearjew/ocr-frontend:<tag>`
- `ghcr.io/drbearjew/ocr-metadata:unified-<tag>` (PaddleOCR-VL + LFM2.5 on one CPU runtime)
- `ghcr.io/drbearjew/ocr-metadata:<tag>` (CPU metadata)
- `ghcr.io/drbearjew/ocr-metadata-cuda:<tag>` (NVIDIA CUDA metadata)
- `ghcr.io/drbearjew/ocr-metadata-vulkan:<tag>` (Vulkan metadata)

## Prerequisites

- Linux x86_64 host with `curl` and `openssl`
- [Docker Engine](https://docs.docker.com/engine/install/) and the [Docker Compose plugin](https://docs.docker.com/compose/install/linux/) (v2+)
- Outbound HTTPS access to `ghcr.io` (and Hugging Face on first startup if you enable local AI models)

### Sizing guide

| Setup | RAM | Free disk | CPU / GPU |
| --- | --- | --- | --- |
| Standard (PP-OCRv6) | 4 GiB (4 cores) | 10 GiB | Any x86_64 CPU |
| Unified (PaddleOCR-VL + LFM2.5) | 16 GiB | 20 GiB | x86_64 with AVX-512 (BF16, VBMI, VNNI) |
| Local CPU metadata (LFM2.5) | 16 GiB | 20 GiB | x86_64 with AVX2, FMA, F16C |
| Local GPU metadata (CUDA / Vulkan) | 16 GiB + VRAM | 20 GiB | AVX2, FMA, F16C host CPU + supported GPU |

## Standard install

Download the installer, inspect it if you like, and run it from the parent directory where you want `./dokocr` created:

```bash
mkdir -p "$HOME/dokocr-host" && cd "$HOME/dokocr-host"
curl -fL https://raw.githubusercontent.com/DrBearJew/OCR/main/scripts/install-docker.sh -o install-docker.sh
bash install-docker.sh
```

On first run, the script creates `./dokocr` (permissions `0700`), generates random credentials in `./dokocr/.env` (`0600`), pulls the images, runs database migrations, and starts the stack.

The admin username is `admin`. Read the generated `ADMIN_PASSWORD` directly from `./dokocr/.env`.

Out of the box, Dok OCR runs local **PP-OCRv6** on CPU (models are baked into the backend image) alongside deterministic metadata extraction, review queues, and PostgreSQL search.

## Adding local AI models

### Unified runtime: PaddleOCR-VL + LFM2.5 in one container

On a CPU with AVX-512 BF16, VBMI, and VNNI support:

```bash
bash install-docker.sh --metadata-runtime unified
```

This starts a single inference container backed by one custom `ik_llama.cpp` binary and `llama-swap`. Dok OCR uses PaddleOCR-VL for OCR and LFM2.5-8B-A1B for metadata, loading one model at a time and unloading it when idle.

Why pick `unified` on a CPU-only host: this image bundles our custom PaddleOCR-VL CPU kernels (unmasked `D=72` IQK vision attention, AVX-512 BF16 FFN tail fix, MRoPE/causal-mask parity, and fast LFM2.5 CPU decoding). Those kernels live inside this compiled binary and do not carry over to external engines like LM Studio or Ollama—use `external` instead when you already have a GPU or separate inference server.

First startup downloads and verifies ~7.85 GB of public model files into the persistent model volume and quantizes the OCR weights automatically.

### Metadata AI with standard PP-OCRv6 OCR

To keep PP-OCRv6 for OCR and add LFM2.5-8B-A1B Q5_K_M (6.03 GB download) for metadata refinement:

```bash
# CPU
bash install-docker.sh --metadata-runtime cpu

# NVIDIA GPU (automatic VRAM fitting)
bash install-docker.sh --metadata-runtime cuda

# AMD or Intel GPU via Linux Vulkan (/dev/dri)
bash install-docker.sh --metadata-runtime vulkan

# Existing OpenAI-compatible server for metadata (LM Studio, llama-server, Ollama, vLLM)
bash install-docker.sh --metadata-runtime external \
  --metadata-url http://host.docker.internal:1234/v1 \
  --metadata-model auto

# Use an external vision model for OCR too (e.g., LM Studio / llama-server / Ollama)
bash install-docker.sh \
  --ocr-runtime external --ocr-url http://host.docker.internal:1234/v1 --ocr-model auto \
  --metadata-runtime external --metadata-url http://host.docker.internal:1234/v1 --metadata-model auto
```

All local metadata modes share the same Docker model volume, so switching between CPU, CUDA, and Vulkan reuses the downloaded weights.

Pass `--metadata` on subsequent runs to re-enable your saved runtime, or `--no-metadata` to disable it without deleting documents or cached weights. Disabling metadata from `unified` mode also switches OCR back to PP-OCRv6.

### GPU notes

- **NVIDIA CUDA:** Requires a host NVIDIA driver supporting CUDA 12.4.1+, a Turing (compute capability 7.5) or newer GPU, and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **Vulkan:** Maps `/dev/dri` into the container without privileged mode and bundles Mesa AMD/Intel drivers. For proprietary NVIDIA Vulkan, configure host ICDs separately or use `cuda`.
- **Automatic vs. manual offloading:** GPU modes use `--fit` automatically. To pin an exact layer count or device list, set these in `./dokocr/.env` and rerun the installer:
  - `DOKOCR_METADATA_GPU_LAYERS=<N>` — replaces `--fit` with an explicit layer count.
  - `DOKOCR_METADATA_DEVICES=<list>` — passed to `--device` (e.g. `CUDA0` or `Vulkan0`).
  - `CUDA_VISIBLE_DEVICES` / `GGML_VK_VISIBLE_DEVICES` — limits which physical GPUs the container sees (e.g. `GGML_VK_VISIBLE_DEVICES=1` exposes physical GPU 1 as `Vulkan0`).
- **External servers (LM Studio, `llama-server`, Ollama, vLLM):** Pass `--ocr-runtime external` for multimodal vision OCR and/or `--metadata-runtime external` for metadata extraction. Use `--ocr-model auto` / `--metadata-model auto` to pick the first served model from `/v1/models`, and add `--ocr-api-key` / `--metadata-api-key` if your endpoint requires a Bearer token. Inside Docker, `localhost` refers to the container itself—use a LAN hostname or `host.docker.internal` (already mapped to `host-gateway` in `compose.yml`) for servers running on the Docker host. You can also switch presets and click detected models directly in **Admin → Models**.

> [!NOTE]
> If you have already saved custom model endpoints in **Admin → Model Setup**, those UI settings take priority over `.env`. Update them in the Admin UI when switching endpoints.

## Installer options

Run `bash install-docker.sh --help` to see all flags.

| Flag | Default | Description |
| --- | --- | --- |
| `--directory PATH` | `./dokocr` | Target install directory. |
| `--ocr-runtime MODE` | `local` | OCR runtime: `local` (PP-OCRv6 CPU) or `external` (OpenAI-compatible vision OCR). |
| `--ocr-url URL` | — | Base URL for `--ocr-runtime external` (HTTP/HTTPS, no embedded credentials or query string). |
| `--ocr-model NAME` | `auto` | Model ID sent to an external vision OCR server (`auto` picks the first model from `/v1/models`). |
| `--ocr-api-key KEY` | — | Optional Bearer API key for the external OCR server (stored in `.env` with `0600` permissions). |
| `--metadata` / `--no-metadata` | Off | Enable your saved metadata runtime (CPU on a fresh install) or disable metadata. |
| `--metadata-runtime MODE` | — | Enable and save a runtime: `unified`, `cpu`, `cuda`, `vulkan`, or `external`. |
| `--metadata-url URL` | — | Base URL for `external` mode (HTTP/HTTPS, no embedded credentials or query string). |
| `--metadata-model NAME` | `metadata` | Model ID sent to an `external` server (or `auto` to pick from `/v1/models`). |
| `--metadata-api-key KEY` | — | Optional Bearer API key for the external metadata server (stored in `.env` with `0600` permissions). |
| `--image-tag TAG` | `main` | Image tag and matching repository ref for Compose files. |
| `--bind IPv4` | `127.0.0.1` | Host IP to bind the web UI and API ports. |
| `--port PORT` | `3001` | Host port for the web UI. |
| `--api-port PORT` | `8001` | Host port for the FastAPI backend. |
| `--project-name NAME` | `dokocr` | Docker Compose project name (locked after initial install to protect volumes). |

Example with a custom path and port:

```bash
bash install-docker.sh --directory /srv/dokocr --port 3100
```

Rerunning the installer keeps your credentials, custom `.env` overrides, selected runtime, and data volumes intact. Because `main` is a moving tag, pass a published commit tag with `--image-tag <tag>` when you want pinned deployments, and back up PostgreSQL and document storage before upgrading.

## Daily operations

Default endpoints:

- Web UI: <http://localhost:3001>
- API docs: <http://localhost:8001/docs>
- Readiness probe: <http://localhost:8001/ready>

Manage the stack from your install directory (the installer writes `COMPOSE_FILE` into `.env`, so plain `docker compose` commands keep your active runtime override):

```bash
cd "$HOME/dokocr-host/dokocr"
docker compose ps
docker compose logs --follow --tail=100
docker compose stop
docker compose start
```

PostgreSQL, Redis, uploaded files, consume-folder files, and downloaded models live in named Docker volumes. Logs rotate automatically (10 MB × 3 files). Never run `docker compose down -v` unless you intend to wipe all data.

## Networking and HTTPS

By default, only `127.0.0.1:3001` and `127.0.0.1:8001` are published; PostgreSQL and Redis stay internal to the Docker network.

For LAN access, bind to a specific interface behind your firewall:

```bash
bash install-docker.sh --bind 192.168.1.20
```

For HTTPS, terminate TLS at a reverse proxy (Caddy, Nginx, Traefik) and add these lines to `./dokocr/.env`, then rerun the installer:

```env
PUBLIC_BASE_URL=https://docs.example.com
FRONTEND_ORIGIN=https://docs.example.com
CORS_ORIGINS=https://docs.example.com
COOKIE_SECURE=true
```

Custom variables in `.env` survive reruns; direct edits to downloaded Compose files do not.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Image pull fails | Verify DNS and outbound HTTPS access to `ghcr.io`, check `--image-tag`, and inspect `docker compose logs --tail=100`. |
| `Illegal instruction` on startup | Local metadata images require AVX2, FMA, and F16C; `unified` requires AVX-512 (BF16, VBMI, VNNI). Switch to `external` or standard PP-OCRv6 on older CPUs. |
| GPU container fails to start | Check host drivers, NVIDIA Container Toolkit (CUDA) or `/dev/dri` permissions (Vulkan), and free VRAM. Selected GPU modes fail fast rather than silently falling back to CPU. |
| Port already in use | Pass free ports via `--port` and `--api-port`, or check `--bind`. |
| Model download stalls or takes long | Ensure outbound access and >= 20 GiB free disk. Keep the model volume—downloads resume automatically and activate only after SHA-256 verification. Follow `docker compose logs -f metadata`. |
| `/ready` is OK but OCR or metadata fails | `/ready` only checks the API and database. Inspect `backend`, `worker`, and `metadata` logs, then test with a small document in the UI. |
| Document lands in **Needs review** | Normal when extracted fields are missing or low-confidence—review and approve them in the UI. |

Looking to develop from source? See [`app/README.md`](../app/README.md).
