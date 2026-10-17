# Install Dok OCR with Docker

This is the straightforward prebuilt-image install for Linux x86_64. It needs no repository clone, compiler, image build, or model endpoint. The installer uses public images:

- `ghcr.io/drbearjew/ocr-backend:<tag>`
- `ghcr.io/drbearjew/ocr-frontend:<tag>`
- `ghcr.io/drbearjew/ocr-metadata:<tag>` (CPU metadata)
- `ghcr.io/drbearjew/ocr-metadata-cuda:<tag>` (NVIDIA metadata)
- `ghcr.io/drbearjew/ocr-metadata-vulkan:<tag>` (Vulkan metadata)

Metadata is optional. Choose the runtime explicitly; installing the app does not require a GPU or a metadata model.

## Requirements

Install Docker Engine and the Docker Compose plugin (v2 or newer, including v5) before running the installer. It does not install Docker or change system services. See the official [Docker Engine installation guide](https://docs.docker.com/engine/install/) and [Compose plugin installation guide](https://docs.docker.com/compose/install/linux/).

Supported images target Linux x86_64. The installer also needs `curl` and OpenSSL. Allow outbound access to GitHub Container Registry; locally hosted metadata models also need access to their public model download on first startup. External metadata mode downloads no local metadata image or weights.

| Install | Recommended provisioning | Disk space | CPU/GPU |
| --- | --- | --- | --- |
| Standard, local PP-OCRv6 | 4 CPU cores, 4 GiB RAM | At least 10 GiB | x86_64 CPU; no GPU |
| With local CPU metadata AI | 16 GiB RAM | At least 20 GiB | AVX2, FMA, and F16C; no GPU |
| With local GPU metadata AI | Depends on offloading and context | At least 20 GiB | Same host CPU baseline plus a compatible CUDA or Vulkan GPU/driver |

These are provisioning recommendations, not measured performance guarantees. The metadata option downloads a pinned 6.03 GB LFM2.5-8B-A1B Q5_K_M model. The extra space covers that model plus container images, documents, and runtime context.

## Install

Choose a working directory; the default install location is `./dokocr` relative to it. Download the standalone script to a file, inspect it, and then run it:

```bash
mkdir -p "$HOME/dokocr-host"
cd "$HOME/dokocr-host"
curl -fL https://raw.githubusercontent.com/DrBearJew/OCR/main/scripts/install-docker.sh -o install-docker.sh
less install-docker.sh
bash install-docker.sh --help
bash install-docker.sh
```

The installer fetches the standalone Compose file and prebuilt images. It generates an admin password, application secret key, and database password. The install directory is mode `0700`; its `.env` file is mode `0600` and contains the generated `ADMIN_PASSWORD`. The completion output prints the `.env` path. Keep it private; for the default example, the admin username is `admin` and the password is in `"$HOME/dokocr-host/dokocr/.env"`. The default install ends up in `"$HOME/dokocr-host/dokocr"`.

The default OCR path is real PP-OCRv6 medium running locally through ONNX Runtime on CPU. Its models are prewarmed in the backend image. It is not fake OCR and does not use PaddleOCR-VL. Metadata extraction, review, and search have deterministic application behavior; a model is not required for the standard install.

### Optional metadata AI

Add `--metadata` to enable native, schema-patched ik LFM2.5-8B-A1B Q5_K_M metadata refinement:

```bash
bash install-docker.sh --metadata
```

On first startup, a local metadata container downloads the pinned, SHA-256-verified model into persistent storage. No manual weights preparation or inference-Python engine is needed. CPU, CUDA, and Vulkan modes share this model volume, so switching compute backends does not require another copy of the weights. Metadata compute selection does **not** change the PP-OCRv6 OCR provider, which remains CPU-based in these images.

### Choose CPU, GPU, or your own metadata server

```bash
# CPU: no GPU drivers or device access needed
bash install-docker.sh --metadata-runtime cpu

# NVIDIA: CUDA-enabled ik with automatic GPU fitting
bash install-docker.sh --metadata-runtime cuda

# Compatible AMD/Intel GPU with Linux DRM access: Vulkan-enabled ik
bash install-docker.sh --metadata-runtime vulkan

# Your own OpenAI-compatible server, on any supported hardware/backend
bash install-docker.sh --metadata-runtime external \
  --metadata-url http://inference.example.local:8080/v1 \
  --metadata-model metadata
```

Selecting a runtime enables metadata. The installer remembers your choice on reruns; `--no-metadata` disables it without deleting documents or cached weights. There is no silent switch to another compute backend when the selected runtime fails.

- **CUDA:** the bundled CUDA 12.4.1 image targets Turing (compute capability 7.5) or newer; later GPU compatibility depends on driver/PTX support. Install a compatible NVIDIA host driver and configure the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) for Docker. The installer requests GPU access but does not install drivers, change Docker services, or require host `nvidia-smi` to select this mode.
- **Vulkan:** requires a compatible host GPU/driver and accessible `/dev/dri` devices. The container receives those devices without privileged mode and includes Mesa AMD/Intel Vulkan drivers. Proprietary NVIDIA Vulkan needs separately configured matching ICD/libraries; the bundled override does not arrange that integration. Compatibility depends on the GPU and Vulkan driver; this is not a guarantee that every GPU works.
- **External:** uses your selected server instead of starting a local metadata container. It must accept the application's OpenAI-compatible chat/schema requests without API-key authentication; the current adapter has no API-key option. Choose a server/model compatible with these requests. Remote servers receive document text, so use only a trusted endpoint. `localhost` inside an app container refers to that container, not your host; use a reachable hostname or `host.docker.internal` with a host server listening on an address reachable from Docker. Restrict that listener with your firewall.

Local GPU modes use ik's `--fit` to determine offloading from available GPU memory; users do not need to guess a layer count. For manual control, set `DOKOCR_METADATA_GPU_LAYERS` to a nonnegative integer in the install directory's `.env` and rerun the installer; this replaces automatic fitting. Optional `DOKOCR_METADATA_DEVICES` selects the device names accepted by ik's `--device` option. Leave both unset for automatic placement. To control physical GPU visibility, set `CUDA_VISIBLE_DEVICES` (CUDA) or `GGML_VK_VISIBLE_DEVICES` (Vulkan) in `.env` before rerunning; for example, `GGML_VK_VISIBLE_DEVICES=1` exposes the second Vulkan device, which ik then numbers `Vulkan0`. The pinned Vulkan backend otherwise selects the first non-CPU device by default.

GPU memory needs depend on context, buffers, and other GPU workloads, not just the model's file size. Automatic fitting is not a universal out-of-memory guarantee. For other backends such as ROCm, use an externally managed compatible server rather than assuming the CUDA image supports AMD.

The installer manages the selected GPU Compose override and records it in `.env`, so the ordinary `docker compose` operations below retain your chosen backend.

Endpoint/model environment values are application defaults. If you previously saved different settings in the app's **Admin → Model setup**, those saved settings take precedence; update them there when changing endpoints. The installer does not overwrite saved application settings. That screen also lets advanced users choose an external GLM/Paddle OCR provider instead of CPU PP-OCRv6. Such OCR servers are separately provisioned; the metadata GPU option does not install or accelerate them.

AI metadata is not guaranteed correct. A document can finish OCR and metadata extraction but enter **Needs review** because fields are missing or low-confidence. Inspect and correct those fields before marking it reviewed; this is different from an installation or processing failure.

### Installer options

Use `bash install-docker.sh --help` for the installer interface and current defaults. Supported options:

| Option | Effect |
| --- | --- |
| `--directory PATH` | Install into a chosen directory; default `./dokocr`. |
| `--metadata` / `--no-metadata` | Enable metadata using the saved runtime (CPU on a new install), or disable it. |
| `--metadata-runtime cpu\|cuda\|vulkan\|external` | Select and enable metadata using this runtime; preserve the choice on reruns. |
| `--metadata-url URL` | HTTP(S) base URL for the `external` runtime; no URL credentials, query, or fragment. |
| `--metadata-model NAME` | Served model alias for the `external` runtime; default `metadata`. |
| `--image-tag TAG` | Select the trusted repository ref and matching image tag; default `main`. |
| `--bind IPv4` | Choose the host address to bind; default `127.0.0.1`. |
| `--port PORT` | Set the frontend host port; default `3001`. |
| `--api-port PORT` | Set the API host port; default `8001`. |
| `--project-name NAME` | Set the Compose project name for a new install; default `dokocr`. Existing project renames are refused to protect its named volumes. |

For example, to use a different directory and frontend port:

```bash
bash install-docker.sh --directory /srv/dokocr --port 3100
```

The installer preserves credentials, settings, and Docker volumes on reruns unless an option is explicitly changed. Its default `main` ref is mutable and selects both the images and the matching Compose file, so rerunning against `main` is not a reproducible rollback. When immutable published commit tags are available, use `--image-tag <tag>` to pin that ref and image set. Back up your database and documents before upgrades; changing an image tag does not reverse database migrations.

## Open and operate

The default addresses are:

- Frontend: <http://localhost:3001>
- API documentation: <http://localhost:8001/docs>
- Readiness: <http://localhost:8001/ready>

The installer prints the credentials-file path but does not print the generated password. Read `ADMIN_PASSWORD` from the install directory's `.env` file locally; do not share its contents. Keep the install directory and its secrets readable only by trusted administrators.

From the install directory, inspect status and follow container logs:

```bash
cd "$HOME/dokocr-host/dokocr"
docker compose ps
docker compose logs --follow --tail=100
```

Stop and resume without removing persistent data:

```bash
docker compose stop
docker compose start
```

PostgreSQL, Redis, document storage, consume-folder files, and optional model data persist in named Docker volumes. Container logs rotate at 10 MB per file, with three files retained. Do not use `docker compose down -v` for routine stops, upgrades, or troubleshooting; `-v` removes persistent volumes.

## Network and security

By default the frontend and API bind to localhost. For LAN access, choose an explicit reachable address with `--bind` and, if needed, custom ports. Bind only to a trusted interface and restrict access with the host firewall. For example, on a host whose LAN address is `192.168.1.20`:

```bash
bash install-docker.sh --bind 192.168.1.20
```

PostgreSQL and Redis have no host-published ports; do not add public access to them or publish the app directly to the public internet. For HTTPS access, terminate TLS at a trusted reverse proxy. Set `PUBLIC_BASE_URL`, `FRONTEND_ORIGIN`, and `CORS_ORIGINS` to the HTTPS origin and `COOKIE_SECURE=true` in the install directory's `.env` file, then rerun the installer. These overrides are preserved on subsequent reruns, unlike edits to the downloaded Compose file. Use strong credentials and firewall the API and data services. Keep the backend API bound to localhost unless the proxy needs access from another trusted host.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Image pull fails | Confirm DNS/outbound access to `ghcr.io`, check the requested tag, then inspect `docker compose ps` and `docker compose logs --tail=100`. |
| Unsupported CPU / illegal instruction | Check the host is Linux x86_64. Local metadata images additionally require AVX2, FMA, and F16C, even when using GPU offload; use an external compatible server or omit metadata on CPUs without those flags. |
| GPU runtime cannot start or reports no device | Check the selected CUDA/Vulkan backend, host drivers, Docker device access, and available GPU memory. An explicit GPU selection is not silently replaced with CPU mode. |
| Port is already in use | Choose free frontend/API ports with `--port` and `--api-port`; check firewall rules and that the bind address belongs to this host. |
| Container is slow or exits under load | Compare available RAM and disk with the recommendations above; check container and host logs for out-of-memory or disk-full errors. These provisioning figures are not throughput guarantees. |
| Optional model download is incomplete or slow | Allow outbound model-host access and enough free disk space. Keep the metadata volume; incomplete downloads resume, and the model is activated only after its SHA-256 check passes. Follow metadata-container logs until it reports healthy. |
| App is ready but OCR/model inference is not | Read the backend, worker, and optional metadata service logs. Readiness does not prove an inference request completed; test with a small document and confirm its processing result in the UI. |

The existing [`app/README.md`](../app/README.md) describes the source-based developer setup. Its sample environment defaults to fake OCR. The optional PaddleOCR-VL/OpenVINO and model-runtime references are separate manual operator paths, not part of this install; see the [advanced PaddleOCR-VL guide](../deploy/paddlevl/README-llama-swap-openvino-sidecar.md).
