# Native GLM-OCR patch for ik_llama.cpp

[`glm-ocr-native.patch`](glm-ocr-native.patch) adds native CPU GLM-OCR multimodal support to `ik_llama.cpp` at commit `cea2d61ffdac38ee2958ba88d120fa07cb67703a`, with no Python inference engine or OpenVINO dependency.

This is an optional source patch for operators who want the `glm` fallback provider. It touches different files from the [LFM JSON-schema patch](../metadata/lfm-json-schema.patch), so both can be applied together if needed.

## Build

From the repository root, apply the patch to a fresh `ik_llama.cpp` checkout:

```bash
patch_file="$(pwd)/deploy/glm/glm-ocr-native.patch"
git clone https://github.com/ikawrakow/ik_llama.cpp.git ik-glm-ocr
cd ik-glm-ocr
git checkout cea2d61ffdac38ee2958ba88d120fa07cb67703a
git apply --check "$patch_file"
git apply "$patch_file"

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=ON
cmake --build build --target llama-server llama-mtmd-cli test-mtmd-pos -j2
ctest --test-dir build -R '^test-mtmd-pos$' --output-on-failure
./build/bin/test-chat-auto-parser
```

Keep the shared libraries alongside `build/bin/llama-server`. Note that `-DGGML_NATIVE=ON` targets the build host's CPU.

## Run

Start the server with your GLM-OCR text (`glm4`) and projector (`glm4v`) GGUFs:

```bash
./build/bin/llama-server \
  --model /path/to/glm.gguf \
  --mmproj /path/to/glm-mmproj.gguf \
  --host 127.0.0.1 --port 8080 \
  -ngl 0 --no-mmproj-offload --jinja
```

The appended NextN head is skipped (GLM MTP / speculative decoding is not implemented). Weights are not bundled—obtain them separately and verify their license and checksums.

## Summary of changes

- Adds GLM vision/projector graph loading and non-square preprocessing on ggml CPU operators.
- Loads M-RoPE metadata and projection widths for GLM text without altering standard GLM4 RoPE behavior.
- Fixes an in-place CPU vision-RoPE bug (covered in `tests/test-rope.cpp`).
- Applies raster causal attention for GLM images and advances text positions by `max(nx, ny)` across cache clones and serialization, without changing Qwen position counting.
- Leaves `common/chat.cpp` untouched.

Derived from MIT-licensed `ggml-org/llama.cpp` commit `7dad2f1a17d65b5e2034c277125bc9f97573a779` (`tools/mtmd/models/glm4v.cpp`, `src/models/glm4.cpp`). Keep upstream `LICENSE` files when redistributing binaries.

## Smoke test

To run the bundled API check (requires Python and Pillow):

```bash
python3 examples/mtmd/test-glm-ocr.py \
  --server build/bin/llama-server \
  --model /path/to/glm.gguf \
  --mmproj /path/to/glm-mmproj.gguf \
  --output /path/to/glm-test-results
```

Tested Q8_0 GGUF checksums (not bundled):

| File | SHA-256 |
| --- | --- |
| `glm.gguf` | `58b4b29c3303fc4d7e44d750243b78c475103118ccea1223a8c419f97908c315` |
| `glm-mmproj.gguf` | `9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f` |
