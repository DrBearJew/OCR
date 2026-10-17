#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

REQUIRED_MODELS = {
    "paddleocr-vl",
    "metadata",
}
OPTIONAL_ALIASES = {
    "glm",
    "metadata-model",
    "metadata-gemma",
    "gemma-4-e2b-it-qat-q4_0",
    "gemma-e2b",
    "qwen-mtp",
    "qwen3.5-2b",
    "qwen",
    "glm-ocr",
    "zai-org/glm-ocr",
}


def fetch_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-provided local/admin URL
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check smart endpoint health/model discovery (does not test inference)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8092/v1", help="OpenAI-compatible /v1 base URL")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    health_url = f"{root}/health"
    models_url = f"{base}/models"
    try:
        health = urllib.request.urlopen(health_url, timeout=args.timeout).read().decode("utf-8")  # noqa: S310
        models_payload = fetch_json(models_url, args.timeout)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc), "base_url": base}, indent=2))
        return 2

    model_ids = {str(item.get("id")) for item in models_payload.get("data", []) if isinstance(item, dict)}
    missing = sorted(REQUIRED_MODELS - model_ids)
    missing_aliases = sorted(OPTIONAL_ALIASES - model_ids)
    ok = not missing
    print(json.dumps({
        "ok": ok,
        "base_url": base,
        "health": health,
        "models": sorted(model_ids),
        "missing_required": missing,
        "missing_optional_aliases": missing_aliases,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
