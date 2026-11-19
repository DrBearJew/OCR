# Unified ik_llama.cpp runtime (PaddleOCR-VL + LFM2.5)

This image packages **one** `ik_llama.cpp` `llama-server` binary and `llama-swap` into a single private container serving both:

- **PaddleOCR-VL 1.6** (`paddleocr-vl`) for document OCR, with the Q8_0 FP16-activation profile enabled
- **LFM2.5-8B-A1B Q5_K_M** (`metadata`) for metadata extraction, with JSON-schema enforcement

`llama-swap` loads whichever model is requested, swaps out the other so only one sits in memory at a time, and unloads on idle.

## What's inside the custom binary

Unlike stock CPU builds, this image compiles custom PaddleOCR-VL and LFM2.5 patches directly into `ik_llama.cpp`:

- **Unmasked `D=72` IQK vision-attention kernel:** dispatches PaddleOCR-VL's 72-wide vision attention through IQK instead of falling back to generic GGML CPU attention (cutting vision-attention CPU time from ~107 s down to ~13 s on tested pages).
- **AVX-512 BF16 FFN-down tail fix:** fixes dropped final 16 terms on PaddleOCR-VL's 4304-wide feed-forward layer on AVX-512 BF16 CPUs.
- **Accuracy parity fixes:** MRoPE image-grid position-span fix (`mtmd_image_tokens_get_n_pos`), corrected image causal mask, and Q8_0 FP16-scale activations.
- **Fast CPU metadata extraction:** shares the same `ik_llama.cpp` binary with LFM2.5-8B-A1B JSON-schema extraction (~1.5× faster CPU token generation than stock `llama.cpp` on tested invoices).

These optimizations are compiled into this `ik_llama.cpp` binary and do **not** transfer to external engines (LM Studio, Ollama, stock `llama-server`, or vLLM), which run their own GPU/CPU kernels. Choose `unified` for CPU-only AVX-512 hosts; choose `--ocr-runtime external` / `--metadata-runtime external` when running on a GPU or external inference server.

## Usage

Install through the standard Docker installer on an x86_64 CPU with **AVX-512 BF16, VBMI, and VNNI**:

```bash
bash install-docker.sh --metadata-runtime unified
```

On first startup, the container downloads and SHA-256-verifies the public PaddleOCR-VL 1.6 and LFM2.5 weights (~7.85 GB total) into the shared `/models` volume and quantizes the OCR weights with the bundled `llama-quantize`. No host runtime installation or manual model setup is needed.

## Building from source (maintainers)

From the repository root:

```bash
# Full unified gateway image (llama-server + llama-quantize + llama-swap + prompt template)
docker build -f deploy/paddle-ik/Dockerfile --target unified -t dokocr-unified deploy

# Standalone runtime target for existing Paddle-only gateways
docker build -f deploy/paddle-ik/Dockerfile --target runtime -t dokocr-paddle-ik deploy
```
