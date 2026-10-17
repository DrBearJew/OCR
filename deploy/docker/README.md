# Published Docker install

Use the [installation guide](../../docs/INSTALL.md) for requirements, security, GPU drivers, and operating instructions. No source build or source-tree mount is needed.

```bash
bash install-docker.sh                             # Real CPU PP-OCRv6; no model AI
bash install-docker.sh --metadata-runtime cpu       # Optional local LFM metadata
bash install-docker.sh --metadata-runtime cuda      # NVIDIA, automatic ik fitting
bash install-docker.sh --metadata-runtime vulkan    # Compatible AMD/Intel Vulkan GPU
bash install-docker.sh --metadata-runtime external --metadata-url http://inference.example.local:8080/v1 --metadata-model metadata
```

These switches choose metadata compute, not OCR acceleration. `--metadata` enables the saved runtime (CPU on a new install); `--no-metadata` disables it without deleting the selection or data. External mode starts/downloads no local metadata image or weights. Use a trusted, compatible endpoint: document text is sent there.

The installer fetches the base Compose file and selected GPU override from the same trusted image/repository ref, or uses its checkout's files when run from source. GPU overrides are recorded through `COMPOSE_FILE` in the private install `.env`, so ordinary `docker compose` commands retain the selection. CUDA requests NVIDIA GPUs; Vulkan maps `/dev/dri` without privileged mode. Optional GPU controls and driver/hardware limitations are in the [metadata runtime guide](../metadata/README.md).

Defaults: directory `./dokocr`, image/ref `main`, project `dokocr`, frontend `127.0.0.1:3001`, API `127.0.0.1:8001`. Docker Engine, Compose v2 or newer, curl, OpenSSL, and Linux x86_64 are required. Local metadata images also require AVX2/FMA/F16C. The pinned local LFM download is 6.03 GB, checksum-verified and shared across CPU/GPU modes.

Generated credentials/settings live in `<directory>/.env` (directory `0700`, file `0600`). Reruns preserve them, ports, selected runtime and named volumes unless explicitly changed. Existing project renames are refused to avoid selecting different volumes. PostgreSQL, Redis, source documents, consume files and model data persist; there is no automatic destructive cleanup. Do not use `down -v` for routine operations.

PostgreSQL/Redis have no published ports. Logs rotate at 10 MB with three files retained. Successful migrations gate the API/workers; `/ready` checks API/database readiness, not inference correctness. Review extraction results before relying on AI metadata. The live deployment is separate from this installer.
