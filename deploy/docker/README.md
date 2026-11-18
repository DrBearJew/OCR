# Published Docker install

Quick reference for the standalone Compose files in this directory. For full setup, hardware requirements, and HTTPS configuration, see [`docs/INSTALL.md`](../../docs/INSTALL.md).

## Commands

```bash
bash install-docker.sh                             # Standard: local CPU PP-OCRv6
bash install-docker.sh --metadata-runtime unified  # Unified: PaddleOCR-VL + LFM2.5 (AVX-512 CPU)
bash install-docker.sh --metadata-runtime cpu      # PP-OCRv6 + CPU LFM2.5 metadata
bash install-docker.sh --metadata-runtime cuda     # PP-OCRv6 + NVIDIA CUDA metadata
bash install-docker.sh --metadata-runtime vulkan   # PP-OCRv6 + AMD/Intel Vulkan metadata
bash install-docker.sh --metadata-runtime external \
  --metadata-url http://inference.example.local:8080/v1 \
  --metadata-model metadata
```

## Compose files

- `compose.yml` — Core stack (`postgres`, `redis`, `migrate`, `backend`, `worker`, `worker-beat`, `frontend`) plus the optional `metadata` profile service.
- `compose.metadata-unified.yml` — Switches to `ocr-metadata:unified-<tag>` and routes both PaddleOCR-VL and LFM2.5 metadata through one container.
- `compose.metadata-cuda.yml` — Requests NVIDIA GPU access and sets `DOKOCR_METADATA_COMPUTE=cuda`.
- `compose.metadata-vulkan.yml` — Maps `/dev/dri` without privileged mode and sets `DOKOCR_METADATA_COMPUTE=vulkan`.

When run remotely, `install-docker.sh` fetches the base file and the matching override from the same `--image-tag` ref (when run inside a local checkout, it copies the local files). It writes `COMPOSE_FILE` into the install directory's `.env` (`0600`), so plain `docker compose` commands keep the active override.

## Defaults and persistence

- Install directory: `./dokocr` (`0700`), Compose project: `dokocr`, tag: `main`
- Published ports: `127.0.0.1:3001` (UI) and `127.0.0.1:8001` (API); PostgreSQL and Redis are internal-only
- Persistent volumes: database, Redis, uploaded files, consume folder, and downloaded model weights (shared across CPU/GPU metadata modes)
- Reruns preserve credentials, ports, runtime selection, and volumes; renaming an existing project is blocked to avoid detaching volumes
- Use `docker compose stop` / `start` for routine control—avoid `docker compose down -v`, which deletes volumes

See [`deploy/metadata/README.md`](../metadata/README.md) for GPU environment variables and [`deploy/paddle-ik/README.md`](../paddle-ik/README.md) for the unified runtime image.
