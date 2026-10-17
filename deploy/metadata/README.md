# LFM metadata runtime

The production metadata alias is **LFM2.5-8B-A1B Q5_K_M**, not image OCR. Paddle/OpenVINO remains a separate, unchanged OCR build. Gemma is retained as `metadata-gemma` for rollback; legacy `qwen` settings and aliases are compatibility names.

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

Provision the weights separately and verify their checksum before serving. The [reference llama-swap config](../model-runtime/llama-swap.config.yaml) shows portable asset paths and the retained Gemma route. It requires prepared binaries/models; it is not a released runtime image.

The backend honors `QWEN_METADATA_THINKING_ENABLED`. Reasoning metadata HTTP requests have a minimum timeout of 240 seconds, preserving larger configured timeouts; non-reasoning calls and OCR keep their configured timeout. Redis leases cover both possible metadata HTTP attempts. This does not raise the 4096-token generation ceiling.

Metadata requests use a JSON schema for core `{value, confidence, evidence}` objects. Prompts copy company/person names verbatim, select labeled invoice/issue dates rather than due dates, and require numeric amounts. Deterministic candidates and manual locks remain in the application pipeline.

## Evidence and limits

The rollout checked three synthetic invoices through the real application provider/prompt, including German/English names, dates, amounts and structured fields, plus the live metadata route and application readiness. These are bounded integration checks, not a guarantee of perfect extraction or a production-wide speed benchmark.

A pre-existing single-image Paddle adapter issue can append instruction text on short synthetic images. It reproduced on both original and LFM deployments; native `OCR:` task-cue inference returned the exact test text. The metadata change does not repair that separate OCR issue.
