# One ik runtime for PaddleOCR-VL and LFM

Use the [Docker installer](../../docs/INSTALL.md) with `--metadata-runtime unified`. It starts one private inference container with one `llama-server` binary. llama-swap runs either PaddleOCR-VL or LFM in a child process, never both at once. The Paddle process enables the OCR-specific Q8_0 activation profile; LFM uses the standard ik path and the LFM JSON-schema fix.

The installer fetches the pinned, verified weights into the existing model volume. It downloads the official PaddleOCR-VL 1.6 checkpoint and prepares the Q8_0 checkpoint with the bundled quantizer. No host ik/llama-swap install and no manual model setup are required. This release targets x86-64 CPUs with AVX-512 BF16, VBMI and VNNI. The default PP-OCRv6 install and the existing metadata-only CPU/GPU modes are unaffected.

For maintainers, from the repository root:

```bash
docker build -f deploy/paddle-ik/Dockerfile --target unified -t dokocr-unified deploy
```

The `runtime` target remains available for existing Paddle-only gateways. Production updates should compare full-page and crop OCR and metadata JSON from the same image, not just gateway health.
