# Legacy PaddleOCR-VL OpenVINO sidecar reference

Operator notes for running PaddleOCR-VL through a custom `ik_llama.cpp` + OpenVINO sidecar behind `llama-swap`.

> [!NOTE]
> For new deployments on AVX-512 CPUs, prefer the prebuilt unified container (`bash install-docker.sh --metadata-runtime unified`), which runs PaddleOCR-VL and LFM2.5 natively without OpenVINO. See [`deploy/paddle-ik/README.md`](../paddle-ik/README.md).

## Build from a custom Paddle/OpenVINO checkout

These commands require your existing custom Paddle/OpenVINO `ik_llama.cpp` tree (stock upstream `ik_llama.cpp` does not include the OpenVINO helper). Keep this checkout separate from the pinned LFM metadata build.

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

Verify that OpenVINO stays isolated in the helper and is not linked into `libmtmd.so`:

```bash
ldd "$IK_LLAMA_CPP_BUILD/examples/mtmd/libmtmd.so" | grep -i libopenvino || true
ldd "$IK_LLAMA_CPP_BUILD/bin/llama-paddleocr-openvino-dry-run" | grep -i libopenvino
```

## Running with llama-swap

A sample systemd unit is included in this directory. Before enabling it, install `/etc/dokocr/llama-swap.config.yaml` with your host binary/model paths and restrict the listener to a trusted interface:

```bash
llama-swap -config /path/to/operator-config.yaml -listen localhost:8092
```

Check health and exposed models:

```bash
systemctl status dokocr-paddle-llama-swap.service
curl -fsS http://localhost:8092/health
curl -fsS http://localhost:8092/v1/models
```

See [`../model-runtime/llama-swap.config.yaml`](../model-runtime/llama-swap.config.yaml) for the containerized reference config and [`../model-runtime/README.md`](../model-runtime/README.md) for the asset layout.

### Model IDs and sidecar environment

- `paddleocr-vl` — PaddleOCR-VL OCR (single-image `/v1/chat/completions`; the app runs bounded parallel page requests when `/v1/ocr/batch` is absent)
- `metadata` — LFM2.5-8B-A1B Q5_K_M (`--reasoning-budget 3072`, 4096 completion cap, `--spec-type none`, 240 s minimum app timeout)
- `metadata-gemma` — optional Gemma rollback
- `glm` — optional GLM OCR fallback

If `llama-paddleocr-openvino-dry-run` sits next to `llama-server`, you do not need to set `IK_PADDLEOCR_OPENVINO_SIDECAR_BIN`. The helper manages its own temporary socket automatically; direct embedding replacement is gated by `IK_PADDLEOCR_OPENVINO_SIDECAR_FORCE_REPLACE=1`. The 0049 vision asset expects a `[1,58,86]` (`1200x800`) manifest grid.

## Dok OCR app configuration

Configure these in **Admin → Model Setup** or `.env` (using the Compose service name `model-runtime` or your host address):

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

`QWEN_*` setting names are retained for compatibility; `QWEN_MODEL_PATH=metadata` targets LFM2.5.

## Endpoint smoke test

```bash
python3 deploy/paddlevl/smoke_llama_swap_openvino_sidecar.py \
  --base-url http://localhost:8092/v1 \
  --image /path/to/fixture.png \
  --expect '<text printed on fixture>'
```
