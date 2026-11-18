# PaddleOCR-VL ik CPU runtime

This optional runtime uses the existing PaddleOCR-VL Q8_0, projector, and OCR chat template. It does not ship or download model weights. It needs Linux x86-64 with AVX-512 BF16, VBMI and VNNI. The public Docker installer still defaults to PP-OCRv6; the metadata runtime is independent.

Build from this directory with `docker build -t dokocr-paddle-ik .`, or use `ghcr.io/drbearjew/ocr-paddle-ik:<commit>` from the Docker workflow. The build pins ik source, tests the portable build, and publishes a separate AVX-512 image. Before promotion, smoke-test the optimized image on the target CPU with the intended model files and full pages as well as crops. An image build alone does not validate OCR accuracy.

For an existing llama-swap gateway, give only the Paddle route this command (substitute absolute paths and a verified immutable image ref):

```yaml
cmd: /path/to/launch.sh ${PORT} IMAGE /path/to/paddle-assets
cmdStop: /usr/bin/docker stop -t 8 dokocr-paddle-ik
concurrencyLimit: 1
ttl: 900
```

The asset directory must contain `paddleocr-vl-q8_0.gguf`, `paddleocr-vl-mmproj.gguf`, and `paddleocr-vl-chat_template.jinja`. The child only binds loopback, runs on demand, and mounts only those files read-only. The gateway needs access to Docker. The app uses `OCR_PROVIDER=paddle_vl`, the existing gateway URL, and `PADDLE_VL_IK_PROFILE=true` in the API and OCR worker. The profile applies one grid-aligned bicubic resize and one greedy `OCR:` request per image, including each page of a PDF. It does not remove repeated quantities or rewrite output. Move the gateway route and app profile together; to roll back, restore the old gateway route and unset the profile.
