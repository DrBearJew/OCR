#!/usr/bin/env python3
"""Smoke test Dok OCR's PaddleOCR-VL llama-swap managed OpenVINO sidecar endpoint.

This calls the same OpenAI-compatible `/v1/chat/completions` interface that
Dok OCR's PaddleVLLlamaCppOCRProvider uses.

Example:
  python3 deploy/paddlevl/smoke_llama_swap_openvino_sidecar.py \
    --base-url http://127.0.0.1:8092/v1 \
    --image /path/to/synthetic-invoice.png \
    --expect INV-2026-0619-01 \
    --expect 'EUR 1123.45'

Expected route markers in llama-server/helper logs:
  started managed OpenVINO sidecar
  manifest_grid_thw=[1,58,86]
  serve_unix_request grid_thw=[1,58,86]
  replaced PaddleOCR image embeddings with OpenVINO sidecar vit_mlp
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8092/v1", help="Dok OCR llama-swap /v1 base URL")
    ap.add_argument("--model", default="paddleocr-vl")
    ap.add_argument("--image", required=True, help="image path to OCR")
    ap.add_argument("--expect", action="append", default=[], help="substring expected in OCR text; may repeat")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        print(json.dumps({"status": "error", "error": f"image not found: {image_path}"}, indent=2), file=sys.stderr)
        return 2

    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "OCR this invoice page image. Return only the visible text."},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 256,
    }

    t0 = time.perf_counter()
    try:
        body = post_json(args.base_url.rstrip("/") + "/chat/completions", payload, args.timeout)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:2000]
        print(json.dumps({"status": "error", "http_status": exc.code, "error": err}, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": repr(exc)}, indent=2), file=sys.stderr)
        return 1

    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    missing = [needle for needle in args.expect if needle not in content]
    result = {
        "status": "ok" if not missing else "mismatch",
        "wall_s": time.perf_counter() - t0,
        "base_url": args.base_url,
        "model": args.model,
        "image": str(image_path),
        "content": content,
        "missing": missing,
        "usage": body.get("usage"),
        "timings": body.get("timings"),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
