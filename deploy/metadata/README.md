# LFM2.5 metadata runtime

Dok OCR uses **LFM2.5-8B-A1B Q5_K_M** (alias `metadata`) for optional LLM metadata refinement. Legacy `QWEN_*` settings and `qwen` aliases remain supported for compatibility, and `metadata-gemma` is kept as an optional rollback alias.

## Prebuilt Docker images

The [Docker installer](../../docs/INSTALL.md) selects a compute backend with `--metadata-runtime` (`cpu`, `cuda`, `vulkan`, `unified`, or `external`).

All three standalone metadata images share the same pinned `ik_llama.cpp` revision, JSON-schema patch, SHA-256-verified downloader, and `/models` volume layout—so switching compute backends reuses your existing weights:

| Backend | Image (`ghcr.io/drbearjew/`, tag `main` or commit SHA) | Dockerfile |
| --- | --- | --- |
| CPU | `ocr-metadata` | `Dockerfile` |
| NVIDIA CUDA | `ocr-metadata-cuda` | `Dockerfile.cuda` |
| Vulkan (AMD/Intel, compatible NVIDIA) | `ocr-metadata-vulkan` | `Dockerfile.vulkan` |

On first startup, local modes download the 6.03 GB model into `/models` (resuming interrupted downloads and verifying SHA-256 before activation; corrupted existing files are reported rather than silently overwritten). Model usage is governed by the [LiquidAI LFM2.5-8B-A1B-GGUF license](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF).

Plan for at least 16 GiB RAM and 20 GiB free disk space on an x86_64 host with AVX2, FMA, and F16C.

## Standalone Docker examples

Keep the `metadata-models` volume when switching backends:

```bash
# NVIDIA (requires host driver + NVIDIA Container Toolkit)
docker run --rm --gpus all -p 127.0.0.1:8080:8080 \
  -v metadata-models:/models -e DOKOCR_METADATA_COMPUTE=cuda \
  ghcr.io/drbearjew/ocr-metadata-cuda:main

# AMD / Intel (requires /dev/dri + working Vulkan 1.2 driver)
docker run --rm --device /dev/dri -p 127.0.0.1:8080:8080 \
  -v metadata-models:/models -e DOKOCR_METADATA_COMPUTE=vulkan \
  ghcr.io/drbearjew/ocr-metadata-vulkan:main
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DOKOCR_METADATA_COMPUTE` | `cpu` | `cpu`, `cuda`, or `vulkan`. Defaults to `cpu` even in GPU images; set both the matching image and compute mode to use a GPU. |
| `DOKOCR_METADATA_THREADS` | `4` | CPU thread count (positive integer). |
| `DOKOCR_METADATA_GPU_LAYERS` | unset (`--fit`) | Explicit layer count (`0`–`2147483647`, GPU modes only). Replaces automatic `--fit` offloading. |
| `DOKOCR_METADATA_DEVICES` | unset | Comma-separated device names passed to `--device` (e.g. `CUDA0,CUDA1` or `Vulkan0`, numbered after container visibility filtering). |
| `CUDA_VISIBLE_DEVICES` | unset | Passed through by the CUDA Compose override to restrict visible NVIDIA GPUs. |
| `GGML_VK_VISIBLE_DEVICES` | unset | Passed through by the Vulkan Compose override (e.g. `1` exposes physical GPU 1 as `Vulkan0`). |

Omit unused variables rather than setting them to empty strings. Before downloading any weights, the launcher queries ggml's device API and exits immediately on invalid configuration or missing GPUs instead of falling back to CPU.

### Backend specifics

- **CUDA:** Built with CUDA 12.4.1 targeting compute capabilities `75;86` (Turing 7.5+) plus PTX for newer GPUs. Uses `GGML_CUDA_NO_VMM=ON` and NVIDIA's host-linker script for large shared libraries.
- **Vulkan:** Built with Ubuntu 24.04 `glslc` and ships the Vulkan loader plus Mesa AMD/Intel ICDs (requires Vulkan 1.2 and 16-bit storage). Proprietary NVIDIA Vulkan requires matching host ICDs/libraries. The launcher disables fused MoE and dense up/gate ops while keeping fused weighted expert reduction enabled, which avoids a Vulkan expert-view bug on this pinned revision.
- **Other GPUs (e.g. ROCm):** Run your own OpenAI-compatible server and connect with `--metadata-runtime external`.

## Model and request parameters

Weights: [LiquidAI/LFM2.5-8B-A1B-GGUF](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF)

| Setting | Value |
| --- | --- |
| File | `LFM2.5-8B-A1B-Q5_K_M.gguf` |
| Revision | `49c14831707011e64d70b2ebd8462ba08d608434` |
| Size | `6030339296` bytes (6.03 GB) |
| SHA-256 | `eb8bd10148ea21e195502d6d6a205983ba40815302068ce72eb160684df92b3e` |
| Context & KV cache | `128000` tokens, `q8_0` KV, 1 slot |
| Completion / thinking | `4096` max tokens, `--reasoning-budget 3072` (reserves 1024 tokens for final JSON) |
| Speculation | `--spec-type none` |

When `QWEN_METADATA_THINKING_ENABLED=true`, metadata HTTP requests enforce a minimum 240-second timeout (OCR keeps 120 seconds) and Redis leases cover retries. Requests enforce a JSON schema with `{value, confidence, evidence}` objects while preserving deterministic extraction and manual field locks in the app.

## JSON-schema patch and manual build

Pinned `ik_llama.cpp` revision: `cea2d61ffdac38ee2958ba88d120fa07cb67703a`.

At that commit, the LFM2.5 chat handler accepted `response_format` without enforcing the JSON grammar. [`lfm-json-schema.patch`](lfm-json-schema.patch) adds schema parsing, `$ref` resolution, and grammar enforcement while preserving chat and reasoning output. [`test-lfm-json-schema.cpp`](test-lfm-json-schema.cpp) covers JSON mode, typed objects, reasoning, and plain chat for LFM2.5 and Gemma.

To build manually in a clean directory (from the repository root):

```bash
patch_dir="$(pwd)/deploy/metadata"
source_dir="$(mktemp -d "${TMPDIR:-/tmp}/dokocr-ik-lfm.XXXXXX")"
git clone https://github.com/ikawrakow/ik_llama.cpp.git "$source_dir"
cd "$source_dir"
git checkout cea2d61ffdac38ee2958ba88d120fa07cb67703a
git apply "$patch_dir/lfm-json-schema.patch"
cp "$patch_dir/test-lfm-json-schema.cpp" tests/
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=ON
cmake --build build --target llama-server test-lfm-json-schema -j2
ctest --test-dir build -R '^test-lfm-json-schema$' --output-on-failure
```

Keep the accompanying shared libraries alongside `build/bin/llama-server`. Note that `-DGGML_NATIVE=ON` builds for the local CPU only.
