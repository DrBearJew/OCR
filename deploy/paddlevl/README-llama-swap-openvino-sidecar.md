# Advanced PaddleOCR-VL llama-swap and OpenVINO sidecar

This is an advanced operator reference for the strict `paddle_vl` provider. PaddleOCR-VL uses ik_llama.cpp with a managed OpenVINO sidecar; llama-swap can expose it through an OpenAI-compatible endpoint. The app backend owns OCR prompts, response cleanup, metadata prompts, and JSON validation.

This guide does not establish that a released turnkey runtime image is available. The optional Compose runtime requires an operator-supplied prepared/tested image and model files; see [`../model-runtime/README.md`](../model-runtime/README.md). Do not expose the model endpoint directly to an untrusted network.

## Build PaddleOCR-VL ik runtime

These commands require the existing **custom Paddle/OpenVINO source tree**, including its helper and CMake options. This repository does not ship that port or a prepared runtime archive; a stock upstream ik checkout is not sufficient. Keep it separate from the pinned metadata source/build.

Set these paths for your custom checkout and OpenVINO installation before running the commands:

```bash
export IK_LLAMA_CPP_SOURCE=/path/to/ik_llama.cpp
export IK_LLAMA_CPP_BUILD=/path/to/ik-llama-build
export OPENVINO_CMAKE_DIR=/path/to/openvino/cmake

cmake -S "$IK_LLAMA_CPP_SOURCE" -B "$IK_LLAMA_CPP_BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=ON \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_PADDLEOCR_OPENVINO_SIDECAR=ON \
  -DLLAMA_PADDLEOCR_OPENVINO_DELEGATE=OFF \
  -DGGML_PADDLEOCR_D72_ATTN_GGML_EXPERIMENT=ON \
  -DOpenVINO_DIR="$OPENVINO_CMAKE_DIR"

cmake --build "$IK_LLAMA_CPP_BUILD" \
  --target llama-server llama-paddleocr-openvino-dry-run -j4
```

Check that OpenVINO remains isolated from `libmtmd` and is linked by the helper:

```bash
ldd "$IK_LLAMA_CPP_BUILD/examples/mtmd/libmtmd.so" | grep -i libopenvino || true
ldd "$IK_LLAMA_CPP_BUILD/bin/llama-paddleocr-openvino-dry-run" | grep -i libopenvino
```

Expected: the first command finds no OpenVINO dependency in `libmtmd`; the helper links the installed OpenVINO runtime.

## Service operations

The repository has a systemd unit example. Provision its host-specific `/etc/dokocr/llama-swap.config.yaml`, service account, and binary/model paths before enabling it; its default listener is loopback-only. Keep the endpoint on a trusted network; use a Compose service DNS name when the app and runtime share a Compose network.

For a host-level service, use a config whose model and helper paths match that host. The sample command shape is:

```bash
llama-swap \
  -config /path/to/operator-config.yaml \
  -listen localhost:8092
```

The maintainer/reference Dockerfile currently pins llama-swap v228; that build input is not a published-image claim.

Check service health and model discovery locally:

```bash
systemctl status dokocr-paddle-llama-swap.service
curl -fsS http://localhost:8092/health
curl -fsS http://localhost:8092/v1/models
```

The Compose model-runtime image files under `deploy/model-runtime/` are maintainer/reference scaffolding. They do not provide a released image reference or first-start model download. Operators must supply a prepared/tested image and provision the model assets before starting that overlay.

## llama-swap config

The maintainer/reference config is [`../model-runtime/llama-swap.config.yaml`](../model-runtime/llama-swap.config.yaml). It uses container paths and requires a prepared runtime and model assets; it is not directly runnable as a host-level config or a standalone released package.

The config currently listens on all interfaces on port `8092`. Restrict the bind address or firewall access to trusted clients before using it on a host; do not expose the endpoint directly to an untrusted network.

Model ids exposed to Dok OCR:

```text
paddleocr-vl
metadata
metadata-gemma   # optional Gemma rollback
glm              # optional fallback OCR
```

Production metadata is LFM2.5-8B-A1B Q5_K_M, using a separate ik runtime pinned to `cea2d61ffdac` with a local JSON-schema fix. Thinking is enabled with a 4096-token completion cap and `--reasoning-budget 3072`, leaving 1024 tokens for final JSON. Metadata request timeout has a 240-second minimum; OCR timeout remains 120 seconds. Do not enable DSpark for this route. The metadata prompt preserves company/person names verbatim, uses invoice/issue date rather than due date, and requires each schema field as an object containing `value`, `confidence`, and `evidence`. See [`../metadata/README.md`](../metadata/README.md) for build and regression details.

Legacy `QWEN_*` settings and old `qwen` model aliases remain for application compatibility, not model identity. The `metadata-gemma` model id is the explicit optional rollback route.

The config intentionally does not set a sidecar socket path; the managed helper creates and cleans up its own temporary socket.

If `llama-paddleocr-openvino-dry-run` is next to the PaddleOCR `llama-server`, no `IK_PADDLEOCR_OPENVINO_SIDECAR_BIN` is needed. Otherwise set that variable in the `dokocr_paddle_env` macro.

## Dok OCR app settings

Set endpoint URLs and model ids in **Admin → Model Setup** or `.env`. For a runtime service on the same Compose network:

```env
OCR_PROVIDER=paddle_vl
PADDLE_VL_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
PADDLE_VL_MODEL_PATH=paddleocr-vl
PADDLE_VL_MMPROJ_PATH=/llm-models/paddleocr-vl-mmproj.gguf
QWEN_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
QWEN_MODEL_PATH=metadata
GLM_LLAMACPP_BASE_URL=http://model-runtime:8092/v1
GLM_MODEL_PATH=glm
```

The `QWEN_*` names are retained compatibility settings. `QWEN_MODEL_PATH=metadata` selects the LFM2.5 production route; it does not identify a Qwen model.

## Smoke test

From the repository root, test one model endpoint using an image fixture you control:

```bash
python3 deploy/paddlevl/smoke_llama_swap_openvino_sidecar.py \
  --base-url http://localhost:8092/v1 \
  --image /path/to/your/fixture.png \
  --expect '<distinctive text printed on this fixture>'
```

This endpoint smoke is narrower than the full Dok OCR image-adapter and document pipeline path. In particular, the single-image adapter has a known limitation: on short synthetic images it can append instruction text. A separate raw native `OCR:` task-cue smoke returned the expected test text; do not infer that the full OCR path is flawless from that result.

## Expected route markers

The reference 0049 vision asset uses a fixed grid of `[1,58,86]` (`1200x800`). Verify the model manifest before serving; do not assume those dimensions for a different asset. In llama-server logs, look for the managed sidecar startup and embedding-replacement messages. The helper log reports its manifest grid and tensor dimensions. Exact log wording may change with the engine build.

## Caveats

- The managed OpenVINO sidecar is tied to its fixed-grid model manifest; verify the model asset and engine build agree before serving requests.
- Direct embedding replacement is controlled by `IK_PADDLEOCR_OPENVINO_SIDECAR_FORCE_REPLACE` in the runtime config.
- This llama-swap route exposes single-image OpenAI-compatible OCR, not Dok OCR's `/v1/ocr/batch` endpoint. The app can issue bounded parallel page requests when batching is unavailable; concurrency is controlled by the document's OCR configuration.
- Keep strict provider semantics: when model OCR is needed and provider is `paddle_vl`, use PaddleOCR-VL and surface failures. In redo mode, the backend may use an embedded PDF text layer only when every selected page passes usable-text validation; force mode ignores that fast path.
- This document describes an advanced operator route. It does not establish a packaged image, a production-ready complete container, or a benchmarked speedup.
