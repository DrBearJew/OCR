# Optional native GLM-OCR port for ik

[`glm-ocr-native.patch`](glm-ocr-native.patch) adds native CPU GLM-OCR image-chat support to ik_llama.cpp **`cea2d61ffdac38ee2958ba88d120fa07cb67703a`**. No Python inference engine or OpenVINO is needed. This is an optional source port, not the default Docker installer or a production deployment. Paddle remains available; no existing deployment is changed.

## Build

From the OCR repository root, retain the patch's absolute path, then use a separate source tree:

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
# Relative template fixtures require this source-tree working directory:
./build/bin/test-chat-auto-parser
```

A native build targets the build machine, not arbitrary other CPUs. Preserve required shared libraries. The separate [LFM schema patch](../metadata/) touches different files and remains necessary for LFM JSON-schema enforcement.

Run with operator-provided compatible GLM-OCR text and projector GGUFs:

```bash
./build/bin/llama-server --model /path/to/glm.gguf \
  --mmproj /path/to/glm-mmproj.gguf --host 127.0.0.1 --port 8080 \
  -ngl 0 --no-mmproj-offload --jinja
```

The text architecture is `glm4`, the projector is `glm4v`. The appended NextN head is skipped; GLM MTP/speculative decoding is not implemented. This guide does not supply or automatically download GLM weights. Check model licenses and provenance.

## What changed

- GLM vision/projector graph, tensor loading and non-square preprocessing use existing ggml CPU operators.
- GLM text loads M-RoPE metadata and correct projection widths, without changing ordinary GLM4's default RoPE behavior.
- A CPU vision-RoPE in-place bug is corrected, with analytical coverage added to `tests/test-rope.cpp`.
- GLM image attention applies raster causal ordering. Following text advances by `max(nx, ny)`, preserved through cache cloning/serialization. Existing Qwen position counting is unchanged.
- `common/chat.cpp` is untouched. No external inference delegate or global convolution-precision change is added.

The implementation derives from MIT-licensed ggml-org/llama.cpp **`7dad2f1a17d65b5e2034c277125bc9f97573a779`** (`tools/mtmd/models/glm4v.cpp`, preprocessing/loading, and `src/models/glm4.cpp`). Attribution is retained in the patch; preserve upstream LICENSE files when redistributing binaries.

## Verification and limits

The native server passed three synthetic real-model API cases: exact clean-text smoke, a complete German invoice with accented parties/address, invoice/due dates and amounts, and a table with all rows and accented footer. Normalized OCR and rendered prompts matched a local build of the pinned reference. The position-span/cache regression, vision-RoPE regression and parser's 476 assertions passed. A retained unrelated Granite template whitespace assertion remains unresolved; this is not a claim that the entire upstream test suite passes.

Validated Q8_0 assets (not included):

| Asset | SHA-256 |
| --- | --- |
| `glm.gguf` | `58b4b29c3303fc4d7e44d750243b78c475103118ccea1223a8c419f97908c315` |
| `glm-mmproj.gguf` | `9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f` |

Reproduce the API checks with Python and Pillow installed for the test harness:

```bash
python3 examples/mtmd/test-glm-ocr.py --server build/bin/llama-server \
  --model /path/to/glm.gguf --mmproj /path/to/glm-mmproj.gguf \
  --output /path/to/glm-test-results
```

Observed candidate latencies were 3.014/23.765/20.383 seconds, with peak server RSS high-water mark about 2.73 GiB, on a shared Ryzen 9 5900X host using four threads. Reference timing overlapped compilation, so **no speedup claim is supported**. This is bounded local CPU correctness evidence, not production accuracy, VPS performance, every-model compatibility or deployment approval.
