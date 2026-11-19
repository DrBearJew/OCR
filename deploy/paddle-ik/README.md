# Unified ik_llama.cpp runtime (PaddleOCR-VL + LFM2.5)

This image packages custom **AVX-512** and **AVX2** `ik_llama.cpp` `llama-server` binaries and `llama-swap` into a single private container, automatically selecting the best tier for the host CPU at startup (`DOKOCR_CPU_TIER=avx512|avx2` overrides auto-detection) and serving both:

- **PaddleOCR-VL 1.6** (`paddleocr-vl`) for document OCR, with the Q8_0 FP16-activation profile enabled
- **LFM2.5-8B-A1B Q5_K_M** (`metadata`) for metadata extraction, with JSON-schema enforcement

`llama-swap` loads whichever model is requested, swaps out the other so only one sits in memory at a time, and unloads on idle.

## What's inside the custom builds

Unlike stock CPU builds, this image compiles custom PaddleOCR-VL and LFM2.5 patches directly into `ik_llama.cpp`:

- **Unmasked `D=72` IQK vision-attention kernel (AVX2 + AVX-512):** dispatches PaddleOCR-VL's 72-wide vision attention through IQK instead of falling back to generic GGML CPU attention (cutting vision-attention CPU time from ~107 s down to ~13 s on tested AVX-512 pages, with an extra packed 72-lane tail micro-kernel on AVX-512).
- **AVX-512 BF16 FFN-down tail fix:** fixes dropped final 16 terms on PaddleOCR-VL's 4304-wide feed-forward layer on AVX-512 BF16 CPUs.
- **Accuracy parity fixes:** MRoPE image-grid position-span fix (`mtmd_image_tokens_get_n_pos`), corrected image causal mask, and Q8_0 FP16-scale activations.
- **Fast CPU metadata extraction:** shares the same `ik_llama.cpp` runtime with LFM2.5-8B-A1B JSON-schema extraction (~1.5× faster CPU token generation than stock `llama.cpp` on tested invoices).

These optimizations are compiled into this `ik_llama.cpp` image and do **not** transfer to external engines (LM Studio, Ollama, stock `llama-server`, or vLLM), which run their own GPU/CPU kernels. Choose `unified` for CPU-only AVX2/AVX-512 hosts; choose `--ocr-runtime external` / `--metadata-runtime external` for GPUs, older pre-AVX2 (AVX1-only) CPUs, or external inference servers.

## Usage

Install through the standard Docker installer on any x86_64 CPU with **AVX2, FMA, and F16C** (automatically uses **AVX-512 BF16/VBMI/VNNI** when present):

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
