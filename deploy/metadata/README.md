# LFM metadata runtime

The production metadata alias is **LFM2.5-8B-A1B Q5_K_M**, not image OCR. Paddle/OpenVINO remains a separate, unchanged OCR build. Gemma is retained as `metadata-gemma` for rollback; legacy `qwen` settings and aliases are compatibility names.

## Optional prebuilt Docker runtime

The [one-command Docker installer](../../docs/INSTALL.md) selects CPU, CUDA, Vulkan, or an external server with `--metadata-runtime`. `--metadata` enables the saved choice (CPU on a new install). Local modes automatically download the pinned public LFM Q5 model into a persistent `/models` volume; external mode starts no local model container. Downloads resume when supported and are SHA-256 verified before activation. Existing invalid model files are preserved and reported, not silently overwritten. Model use is subject to the [official model's license](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF).

The CPU image builds the pinned schema-patched server from source with AVX2/FMA/F16C, without native/AVX512 or GPU requirements. It serves metadata on internal port 8080 and is separate from both the basic PP-OCRv6 OCR provider and the advanced Paddle runtime. Plan for at least 16 GiB RAM and 20 GiB free disk for the complete AI-enabled install; the model download alone is 6.03 GB. These are provisioning recommendations, not a throughput guarantee.

### CPU, CUDA, or Vulkan

All three images use the same pinned ik revision, schema patch, checksum-verified downloader and `/models` layout. Switching compute does not require a second copy of the model; retain and reuse the same model volume.

| Compute | Image (`ghcr.io/drbearjew/`, tag `main` or commit SHA) | Dockerfile |
| --- | --- | --- |
| CPU | `ocr-metadata` | `Dockerfile` |
| NVIDIA CUDA | `ocr-metadata-cuda` | `Dockerfile.cuda` |
| Vulkan (AMD/Intel, compatible NVIDIA drivers) | `ocr-metadata-vulkan` | `Dockerfile.vulkan` |

`DOKOCR_METADATA_COMPUTE=cpu|cuda|vulkan` defaults to **cpu**, including in GPU images. CPU mode explicitly disables GPU offload. Select both the matching GPU image and compute mode to use a GPU. GPU mode uses ik's **`--fit` automatic GPU fitting** by default; there is no required layer-count tuning. The fixed context, KV types and request/reasoning settings below are unchanged. Automatic fitting can retain work in system RAM; it is not a promise that every model/context fits entirely in VRAM.

For this pinned Vulkan backend, the launcher disables fused MoE and dense up/gate weight operations, using GPU-supported matmuls instead of copying expert weights through CPU fallbacks. It deliberately **keeps fused weighted expert reduction enabled**: disabling that too reaches an incorrect Vulkan expert-view reduction path. CPU and CUDA retain their native fusion defaults. The launcher regression protects this combination.

Optional advanced settings:

- `DOKOCR_METADATA_GPU_LAYERS`: integer from `0` to `2147483647`, GPU mode only. When supplied, replaces `--fit` with `--gpu-layers N`; `0` is an explicit user-requested zero-layer override.
- `DOKOCR_METADATA_DEVICES`: nonempty comma-separated ik device names, for example `CUDA0,CUDA1` or `Vulkan0`. GPU mode only; forwarded as one `--device` argument, without a shell. Empty/control-character values and unavailable devices fail. Device numbering is ik's numbering after host/container visibility filtering, not necessarily the host's physical index.
- `CUDA_VISIBLE_DEVICES` / `GGML_VK_VISIBLE_DEVICES`: optional backend visibility masks, passed through by their respective GPU Compose overrides. For example, `GGML_VK_VISIBLE_DEVICES=1` exposes physical Vulkan device 1 as ik's `Vulkan0`. The pinned Vulkan backend otherwise defaults to its first non-CPU device.
- `DOKOCR_METADATA_THREADS`: positive integer, default `4`.

Omit unused optional variables rather than setting them to empty strings. Invalid configuration, a mismatched image/backend, or no visible GPU fails **before model provisioning**; the launcher does not silently select another backend. It queries the pinned engine's exported ggml device API before downloading. No ROCm image is provided; a separately managed OpenAI-compatible endpoint can use other backends.

Standalone examples (choose one; retain `metadata-models` when switching):

```bash
# NVIDIA: host driver and NVIDIA Container Toolkit required.
docker run --rm --gpus all -p 127.0.0.1:8080:8080 \
  -v metadata-models:/models -e DOKOCR_METADATA_COMPUTE=cuda \
  ghcr.io/drbearjew/ocr-metadata-cuda:main

# AMD/Intel: Linux DRM device access and working Vulkan driver required.
docker run --rm --device /dev/dri -p 127.0.0.1:8080:8080 \
  -v metadata-models:/models -e DOKOCR_METADATA_COMPUTE=vulkan \
  ghcr.io/drbearjew/ocr-metadata-vulkan:main
```

**Support limits:** images target Linux x86-64 with AVX2/FMA/F16C. CUDA uses the upstream-supported CUDA 12.4.1 build path, targets compute capabilities `75;86` (Turing 7.5 minimum), and embeds PTX for later GPUs. Older NVIDIA architectures are not included; newer architectures depend on compatible driver/PTX JIT support, not verified native kernels. The host must support CUDA 12.4.1 containers. `GGML_CUDA_NO_VMM=ON` uses the upstream cudaMalloc path and avoids a hard driver-library dependency during GPU-less executable checks; it does not remove the inference driver requirement. The CUDA build generates NVIDIA's [host-linker script](https://docs.nvidia.com/cuda/archive/12.4.1/cuda-compiler-driver-nvcc/index.html#host-linker-script-use-lcs-gen-lcs-hls) for shared libraries: large embedded GPU code otherwise exceeds host relocation ranges. This retains the CUDA version and GPU targets rather than dropping kernels to make the link pass.

Vulkan uses the upstream `GGML_VULKAN`/glslc build path with Ubuntu 24.04 SDK packages. The runtime includes the Vulkan loader and Ubuntu Mesa AMD/Intel ICDs; hardware newer than that Mesa version may require a newer separately verified image. The pinned engine requires Vulkan 1.2 and 16-bit storage; shader/flash-attention support still depends on the device/driver. NVIDIA Vulkan requires matching proprietary host ICD/libraries (the Mesa packages alone do not supply these). Passing `/dev/dri` alone does not configure NVIDIA's proprietary driver. Non-root containers also need render-device group access.

CI runs offline launcher/downloader regressions, builds each image with the same schema regression, and checks executable startup/linkage without model weights. GPU-less CI **does not verify GPU inference**, fitting quality, throughput, or hardware compatibility. Run a real model request on the intended GPU before relying on GPU operation.

Local Vulkan launch validation on one RX 7900 XTX checked automatic full layer offload and real PP-OCRv6 plus application metadata on a synthetic German invoice: structured fields preserved both company names, invoice number, date, and amount. Disabling all three fusions was fast but failed correctness; the retained weighted-reduction setting passed. This is a bounded integration check, not a claim about all documents/devices or NVIDIA hardware.

The manual build and production-layout notes below remain useful for advanced operators; they are not prerequisites for the prebuilt installer.

## Engine fix and provenance

The pinned [ik_llama.cpp](https://github.com/ikawrakow/ik_llama.cpp) revision is `cea2d61ffdac38ee2958ba88d120fa07cb67703a`. At that revision, the LFM2.5 chat handler accepted API `response_format` requests but did not enforce their JSON/schema grammar. [The local patch](lfm-json-schema.patch) adds schema parsing, reference resolution and immediate grammar enforcement while retaining ordinary chat/reasoning behavior.

The included regression exercises JSON mode, typed objects, reasoning support and unconstrained chat for LFM2.5 and Gemma. It failed before the patch and passed after it on the production build. This is a local patch, not a claim that upstream contains the fix. Recheck newer upstream versions before reapplying it.

### Maintainer build

Use a separate source/build directory. **Do not update or rebuild an existing custom Paddle/OpenVINO tree in place.** From this repository root, with Git, CMake and a C++ toolchain available:

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

Keep the server's shared libraries when installing `build/bin/llama-server`. A native build targets the build machine's CPU; do not label it portable to other CPUs or architectures without checking those targets.

## Model and request settings

Official weights: [LiquidAI/LFM2.5-8B-A1B-GGUF](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF).

| Item | Value |
| --- | --- |
| File | `LFM2.5-8B-A1B-Q5_K_M.gguf` |
| Model revision | `49c14831707011e64d70b2ebd8462ba08d608434` |
| Bytes | `6030339296` |
| SHA-256 | `eb8bd10148ea21e195502d6d6a205983ba40815302068ce72eb160684df92b3e` |
| Context | `128000`, q8_0 KV, one slot |
| Completion ceiling | `4096` tokens, thinking enabled |
| Thinking budget | `3072`, reserving up to `1024` tokens for final JSON |
| Speculation | `--spec-type none`; no DSpark weights/flags |

For a manual build, provision the weights separately and verify their checksum before serving; the prebuilt Docker runtime handles this automatically. The [reference llama-swap config](../model-runtime/llama-swap.config.yaml) shows portable asset paths and the retained Gemma route. It requires prepared binaries/models; it is not a released runtime image.

The backend honors `QWEN_METADATA_THINKING_ENABLED`. Reasoning metadata HTTP requests have a minimum timeout of 240 seconds, preserving larger configured timeouts; non-reasoning calls and OCR keep their configured timeout. Redis leases cover both possible metadata HTTP attempts. This does not raise the 4096-token generation ceiling.

Metadata requests use a JSON schema for core `{value, confidence, evidence}` objects. Prompts copy company/person names verbatim, select labeled invoice/issue dates rather than due dates, and require numeric amounts. Deterministic candidates and manual locks remain in the application pipeline.

## Evidence and limits

The rollout checked three synthetic invoices through the real application provider/prompt, including German/English names, dates, amounts and structured fields, plus the live metadata route and application readiness. These are bounded integration checks, not a guarantee of perfect extraction or a production-wide speed benchmark.

A pre-existing single-image Paddle adapter issue can append instruction text on short synthetic images. It reproduced on both original and LFM deployments; native `OCR:` task-cue inference returned the exact test text. The metadata change does not repair that separate OCR issue.
