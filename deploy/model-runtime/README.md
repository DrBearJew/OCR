# Custom model-runtime container (maintainer recipe)

This directory contains the packaging contract for operators who build and host their own multi-model `llama-swap` image (used with `app/docker-compose.smart.yml`). Unlike the prebuilt Docker installer in [`docs/INSTALL.md`](../../docs/INSTALL.md), this recipe has no public registry tag and does not download models on startup—you supply the binaries and model volume yourself.

For most users who want PaddleOCR-VL and LFM2.5 in one container, use `bash install-docker.sh --metadata-runtime unified` instead (see [`deploy/paddle-ik/README.md`](../paddle-ik/README.md)).

## Expected binaries

Package your prebuilt binaries and their shared libraries into a tarball that extracts under `/opt/dokocr`:

| Path | Role |
| --- | --- |
| `ik-paddle/bin/llama-server` | Custom PaddleOCR-VL / OpenVINO build |
| `ik-paddle/bin/llama-paddleocr-openvino-dry-run` | Managed vision helper + OpenVINO libraries |
| `ik-lfm/bin/llama-server` | Schema-patched LFM2.5 build ([`deploy/metadata/README.md`](../metadata/README.md)) |
| `ik/bin/llama-server` | Optional Gemma rollback build |
| `glm/bin/llama-server` | Optional GLM-OCR build (only needed if using the `glm` route) |

Preserve each binary's shared-library layout.

## Expected `/models` layout

Populate the model volume before starting the container:

```text
paddleocr-vl/paddleocr-vl-q8_0.gguf
paddleocr-vl/paddleocr-vl-mmproj.gguf
paddleocr-vl/paddleocr-vl-chat_template.jinja
paddleocr-vl-openvino-direct-pos-0049/model/manifest.json   # full vision model directory
lfm2.5-8b-a1b/LFM2.5-8B-A1B-Q5_K_M.gguf
gemma-4-E2B-it-qat-q4_0-gguf/gemma-4-E2B_q4_0-it.gguf
gemma-4-E2B-it-qat-q4_0-gguf/google-gemma4-E2B-chat_template-main.jinja
```

For optional GLM OCR, also add `/opt/dokocr/glm/bin/llama-server`, `/models/glm/glm.gguf`, and `/models/glm/glm-mmproj.gguf`. Startup checks and the doctor script do not require GLM.

## Build and run

From the repository root, pass the official `llama-swap` v228 checksum and your runtime tarball URL + SHA-256:

```bash
docker build deploy/model-runtime -t dokocr-model-runtime:local \
  --build-arg LLAMA_SWAP_SHA256="$LLAMA_SWAP_SHA256" \
  --build-arg DOKOCR_IK_RUNTIME_TARBALL_URL="$DOKOCR_IK_RUNTIME_TARBALL_URL" \
  --build-arg DOKOCR_IK_RUNTIME_TARBALL_SHA256="$DOKOCR_IK_RUNTIME_TARBALL_SHA256"
```

Both archives are checksum-verified before extraction. Do not embed secrets in build arguments.

Start the app with the overlay and run the health check:

```bash
cd app
export DOKOCR_MODEL_RUNTIME_IMAGE=dokocr-model-runtime:local
docker compose -f docker-compose.yml -f docker-compose.smart.yml up -d
python ../scripts/doctor-smart-runtime.py --base-url http://127.0.0.1:8092/v1
```

The gateway binds to loopback on the host and serves app containers at `http://model-runtime:8092/v1`. You can replace the named model volume with a host bind mount at `/models`.

## Exposed model IDs

- `paddleocr-vl` — PaddleOCR-VL OCR
- `metadata` — LFM2.5-8B-A1B Q5_K_M (thinking budget 3072 / 4096 max tokens, no speculation)
- `metadata-gemma` — optional Gemma rollback
- `glm` — optional GLM OCR fallback
- Compatibility aliases: `metadata-model`, `qwen-mtp`, `qwen3.5-2b`, `qwen`, `glm-ocr`

`llama-swap` only loads, unloads, and proxies requests; the Dok OCR backend owns prompts, JSON schemas, validation, and Redis locking. Test real OCR and metadata requests on your target hardware before rolling out an image—`/health` and the doctor script only verify startup and model discovery.
