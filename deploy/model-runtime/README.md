# Smart model-runtime: maintainer reference

This is a **reference recipe**, not a verified, published turnkey image. No registry tag or model downloader is supplied. The runnable app quickstart remains in [the app guide](../../app/README.md); an existing compatible model endpoint can be configured in Admin.

## Prepared image and assets

Maintainers must supply CPU/architecture/ABI-compatible binaries and shared libraries in a checksummed tarball. Extracting it under `/opt/dokocr` must provide:

| Path | Purpose |
| --- | --- |
| `ik-paddle/bin/llama-server` | Existing custom Paddle/OpenVINO build |
| `ik-paddle/bin/llama-paddleocr-openvino-dry-run` | Managed vision helper, with its OpenVINO dependencies |
| `ik-lfm/bin/llama-server` | [Pinned, schema-patched LFM metadata build](../metadata/README.md) |
| `ik/bin/llama-server` | Retained Gemma rollback build |
| `glm/bin/llama-server` | Optional GLM-compatible multimodal build; only needed for the GLM route |

Preserve the binaries' shared-library layout; do not assume a copied executable is self-contained. Never replace the custom Paddle build with the metadata build.

The config defines a fixed `/models` layout. Provision these files into the model volume before starting:

```text
paddleocr-vl/paddleocr-vl-q8_0.gguf
paddleocr-vl/paddleocr-vl-mmproj.gguf
paddleocr-vl/paddleocr-vl-chat_template.jinja
paddleocr-vl-openvino-direct-pos-0049/model/manifest.json
lfm2.5-8b-a1b/LFM2.5-8B-A1B-Q5_K_M.gguf
gemma-4-E2B-it-qat-q4_0-gguf/gemma-4-E2B_q4_0-it.gguf
gemma-4-E2B-it-qat-q4_0-gguf/google-gemma4-E2B-chat_template-main.jinja
```

To use optional GLM OCR, also provision `/opt/dokocr/glm/bin/llama-server`, `/models/glm/glm.gguf`, and `/models/glm/glm-mmproj.gguf`. Neither startup checks nor the doctor require GLM. Its alias remains in the reference config; selecting it without provisioning the runtime/assets will fail to load.

The OpenVINO directory needs the complete matching patched vision model, not just its manifest. Check model provenance, licenses and checksums when provisioning. Weights and runtime libraries are not in this repository. There is no first-start download or conversion step.

## Build and use

From the repository root, build your prepared artifact with:

```bash
docker build deploy/model-runtime -t dokocr-model-runtime:local \
  --build-arg LLAMA_SWAP_SHA256="$LLAMA_SWAP_SHA256" \
  --build-arg DOKOCR_IK_RUNTIME_TARBALL_URL="$DOKOCR_IK_RUNTIME_TARBALL_URL" \
  --build-arg DOKOCR_IK_RUNTIME_TARBALL_SHA256="$DOKOCR_IK_RUNTIME_TARBALL_SHA256"
```

Use the official checksum for the llama-swap v228 archive matching the target architecture, plus the checksum of your prepared runtime archive. Archives are verified before extraction. Do not put credentials into artifact URLs/build arguments or publish private production assets.

After provisioning and testing the image/models:

```bash
cd app
export DOKOCR_MODEL_RUNTIME_IMAGE=dokocr-model-runtime:local
docker compose -f docker-compose.yml -f docker-compose.smart.yml up -d
python ../scripts/doctor-smart-runtime.py --base-url http://127.0.0.1:8092/v1
```

The overlay requires an explicit image and publishes the gateway on loopback. App services use `http://model-runtime:8092/v1` internally. The named model volume can be replaced with an operator-managed bind mount at `/models`.

## Runtime contract

- `paddleocr-vl`: strict PaddleOCR-VL OCR; custom OpenVINO build remains separate.
- `metadata`: LFM2.5 Q5, no speculation/DSpark, thinking budget 3072 within the app's 4096 completion tokens.
- `metadata-gemma`: optional operational rollback route, provisioned in this reference layout.
- `glm`: optional OCR fallback; provision its runtime and assets only when needed.
- Legacy `metadata-model`, `qwen-mtp`, `qwen3.5-2b`, `qwen`, Gemma and GLM aliases remain compatible.

The app owns prompts, decoding requests, JSON schema, metadata validation and Redis inference coordination. llama-swap only loads/unloads/proxies models.

`/health`, image healthchecks and the doctor script establish availability/model discovery, **not inference correctness**. Before publishing an image, test real metadata and image inference, model switching, library loading and the actual target CPU. This repository update does not publish or deploy such an image.
