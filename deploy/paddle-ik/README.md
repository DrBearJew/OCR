# Unified ik_llama.cpp runtime (PaddleOCR-VL + LFM2.5)

This image packages custom **AVX-512** and **AVX2** `ik_llama.cpp` `llama-server` binaries and `llama-swap` into a single private container, automatically selecting the best tier for the host CPU at startup (`DOKOCR_CPU_TIER=avx512|avx2` overrides auto-detection) and serving both:

- **PaddleOCR-VL 1.6** (`paddleocr-vl`) for document OCR, with the Q8_0 FP16-activation profile enabled
- **LFM2.5-8B-A1B Q5_K_M** (`metadata`) for metadata extraction, with JSON-schema enforcement

`llama-swap` loads whichever model is requested, swaps out the other so only one sits in memory at a time, and unloads on idle.

## What's inside the custom builds

Unlike stock CPU builds, this image compiles custom PaddleOCR-VL and LFM2.5 patches directly into `ik_llama.cpp`:

- **Unmasked `D=72` IQK vision-attention kernels (native AVX-512 and AVX2):** dispatches PaddleOCR-VL's 72-wide vision attention through IQK instead of generic GGML CPU attention, with **2D `(head, query-block)` thread partitioning** so non-power-of-two core counts (6, 10, 12, etc.) stay balanced and bit-exact:
  - **AVX-512:** packed 72-lane vision attention (`iqk_fa_vision_v72`) cutting vision-attention CPU time from ~107 s down to ~13 s on tested pages.
  - **AVX2:** dedicated zero-spill 8-key × 4-query packed-K + native 72-wide 32-key FP32 V-tile microkernel (`9 × 8` exact AVX2 vectors, zero wasted lanes, zero-copy Q/V fast path) cutting full-page attention latency by **35–39%** vs padded 96-wide AVX2 IQK plus another **18.4%** single-head V-stage drop (`106.9 → 87.2 ms`), bit-for-bit identical.
- **Physical-core & cgroup-aware auto-threading:** automatically uses available physical CPU cores (bounded by Docker cgroup CPU quotas and capped at 8 by default; override with `DOKOCR_THREADS`).
- **AVX-512 BF16 FFN-down tail fix:** fixes dropped final 16 terms on PaddleOCR-VL's 4304-wide feed-forward layer on AVX-512 BF16 CPUs.
- **Accuracy parity fixes:** MRoPE image-grid position-span fix (`mtmd_image_tokens_get_n_pos`), corrected image causal mask, and Q8_0 FP16-scale activations.
- **Fast CPU metadata extraction:** shares the same `ik_llama.cpp` runtime with LFM2.5-8B-A1B JSON-schema extraction (~1.5× faster CPU token generation than stock `llama.cpp` on tested invoices).

These optimizations are compiled into this `ik_llama.cpp` image and do **not** transfer to external engines (LM Studio, Ollama, stock `llama-server`, or vLLM), which run their own GPU/CPU kernels. Choose `unified` for CPU-only AVX2/AVX-512 hosts; choose `--ocr-runtime external` / `--metadata-runtime external` for GPUs, older pre-AVX2 (AVX1-only) CPUs, or external inference servers.

## Measured speedups

### AVX2 native `D=72` vision attention (Ryzen 9 5900X, Zen 3, `nh = 16`, `D = 72`)

Wall-clock median across 7 iterations on pinned physical cores (bit-for-bit identical output to padded 96-wide AVX2 IQK):

| Vision tokens (`nq = nk`) | Threads | Padded 96-wide AVX2 | Native 72-wide AVX2 | Latency drop | Speedup |
|---:|---:|---:|---:|---:|---:|
| 4920 | 4 | 562.0 ms | **365.0 ms** | −35.1% | **1.54×** |
| 4920 | 8 | 332.5 ms | **204.0 ms** | −38.7% | **1.63×** |
| 4988 | 4 | 575.7 ms | **371.1 ms** | −35.5% | **1.55×** |
| 4988 | 8 | 336.9 ms | **211.1 ms** | −37.4% | **1.60×** |

At 8 threads (`nq = nk = 4920`), QK dropped from `215.5 ms` to `85.3 ms` (2.5× faster), V accumulation dropped further with 32-key FP32 V-tile reuse (`106.9 ms → 87.2 ms` single-head total, −18.4%, bit-exact), and scratch/pack overhead dropped from `10.4 ms` to `1.1 ms`.

### End-to-end AVX2 PaddleOCR-VL 1.6 in `unified` Docker (Ryzen 9 5900X)

Measured inside the `unified` container on the 4-case receipt parity suite (**4/4 exact character-for-character match** against the AVX-512 VPS baseline):

| Case | Old hardcoded 4 threads | Auto-threaded (8 physical cores) + V-tile & 2D FA | Speedup |
|---|---:|---:|---:|
| `receipt-02-full` (864×1296) | 28.44 s | **16.85 s** | **1.69×** |
| `receipt-02-region` | 6.18 s | **3.72 s** | **1.66×** |
| `receipt-17-full` (960×1280) | 30.84 s | **17.04 s** | **1.81×** |
| `receipt-17-region` | 3.87 s | **2.63 s** | **1.47×** |

### AVX-512 vision attention & LFM2.5 CPU decoding (4-vCPU AVX-512 VPS)

- **PaddleOCR-VL vision attention:** dropped from **107.45 s** (generic fallback) to **13.31 s** (~8× faster), with full-page receipt OCR at **25.2–25.7 s** vs **30.6–34.3 s** on upstream `llama.cpp`.
- **LFM2.5-8B-A1B Q5_K_M metadata:** **43.4 tok/s** (`65.6–70.9 s` per invoice) vs **28.0 tok/s** (`88.1–107.6 s`) on upstream `llama.cpp` at matched 8k context and 4 threads.

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
