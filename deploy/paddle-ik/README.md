# Unified ik_llama.cpp runtime (PaddleOCR-VL + LFM2.5)

This image packages **one** `ik_llama.cpp` `llama-server` binary and `llama-swap` into a single private container serving both:

- **PaddleOCR-VL 1.6** (`paddleocr-vl`) for document OCR, with the Q8_0 FP16-activation profile enabled
- **LFM2.5-8B-A1B Q5_K_M** (`metadata`) for metadata extraction, with JSON-schema enforcement

`llama-swap` loads whichever model is requested, swaps out the other so only one sits in memory at a time, and unloads on idle.

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
