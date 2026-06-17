#!/usr/bin/env python3
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
import openvino as ov

ROOT = Path(os.getenv("PADDLE_OV_ROOT", "/opt/paddleocr-vl-openvino"))
UPSTREAM_DIR = ROOT / "paddleocr_vl_ov_add_layout"
LEGACY_CODE_DIR = ROOT / "paddleocr_vl_ov"
if UPSTREAM_DIR.exists():
    sys.path.insert(0, str(UPSTREAM_DIR))
else:
    sys.path.insert(0, str(LEGACY_CODE_DIR))
try:
    from paddleocr_vl_openvino.paddleocr_vl.ov_paddleocr_vl import OVPaddleOCRVLForCausalLM  # type: ignore  # noqa: E402
except Exception:  # noqa: BLE001
    from ov_paddleocr_vl import OVPaddleOCRVLForCausalLM  # type: ignore  # noqa: E402

LOG = logging.getLogger("paddlevl-openvino")
MODEL_ID = os.getenv("PADDLE_OV_MODEL_ID", "paddleocr-vl")
MODEL_PATH = os.getenv("PADDLE_OV_MODEL_PATH", str(ROOT / "modelscope-cache" / "zhaohb" / "PaddleOCR-Vl-OV"))
HOST = os.getenv("PADDLE_OV_HOST", "0.0.0.0")
PORT = int(os.getenv("PADDLE_OV_PORT", "8091"))
MAX_NEW_TOKENS = int(os.getenv("PADDLE_OV_MAX_NEW_TOKENS", "1024"))
MAX_BATCH_SIZE = int(os.getenv("PADDLE_OV_MAX_BATCH_SIZE", "4"))
IMAGE_WIDTH = int(os.getenv("PADDLE_OV_IMAGE_WIDTH", "1200"))
IMAGE_HEIGHT = int(os.getenv("PADDLE_OV_IMAGE_HEIGHT", "800"))

_model: Any = None
_generation_config: dict[str, Any] | None = None
_model_lock = threading.Lock()


def _load_model() -> None:
    global _model, _generation_config
    start = time.perf_counter()
    core = ov.Core()
    _model = OVPaddleOCRVLForCausalLM(
        core=core,
        ov_model_path=MODEL_PATH,
        device="CPU",
        llm_int4_compress=False,
        vision_int8_quant=True,
        llm_int8_compress=False,
        llm_int8_quant=True,
        llm_infer_list=[],
        vision_infer=[],
    )
    _generation_config = {
        "bos_token_id": _model.tokenizer.bos_token_id,
        "eos_token_id": _model.tokenizer.eos_token_id,
        "pad_token_id": _model.tokenizer.pad_token_id,
        "max_new_tokens": MAX_NEW_TOKENS,
        "do_sample": False,
    }
    LOG.info(
        "Loaded PaddleOCR-VL OpenVINO model path=%s openvino=%s seconds=%.2f batch_methods=%s",
        MODEL_PATH,
        ov.get_version(),
        time.perf_counter() - start,
        hasattr(_model, "batch_generate"),
    )


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def _image_from_data_url(url: str) -> Image.Image:
    if not url.startswith("data:"):
        raise ValueError("Only data:image URLs are supported")
    encoded = url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def _resize_image(image: Image.Image) -> Image.Image:
    return image.convert("RGB").resize((IMAGE_WIDTH, IMAGE_HEIGHT), Image.Resampling.LANCZOS)


def _extract_text_and_image(payload: dict[str, Any]) -> tuple[str, Image.Image]:
    messages = payload.get("messages") or []
    prompt_parts: list[str] = []
    image: Image.Image | None = None
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            prompt_parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                prompt_parts.append(str(item.get("text") or ""))
            elif item.get("type") == "image_url":
                image_url = item.get("image_url") or {}
                url = image_url.get("url") if isinstance(image_url, dict) else None
                if isinstance(url, str):
                    image = _image_from_data_url(url)
            elif item.get("type") == "image":
                maybe = item.get("image")
                if isinstance(maybe, Image.Image):
                    image = maybe.convert("RGB")
    if image is None:
        raise ValueError("No data:image image_url found in request")
    prompt = "\n".join(part.strip() for part in prompt_parts if part and part.strip()).strip() or "OCR:"
    if "OCR" not in prompt.upper():
        prompt = "OCR:"
    return prompt, _resize_image(image)


def _extract_batch(payload: dict[str, Any]) -> tuple[str, list[Image.Image]]:
    prompt = str(payload.get("prompt") or "OCR:").strip() or "OCR:"
    if "OCR" not in prompt.upper():
        prompt = "OCR:"
    images_payload = payload.get("images") or []
    if not isinstance(images_payload, list) or not images_payload:
        raise ValueError("images must be a non-empty list")
    if len(images_payload) > MAX_BATCH_SIZE:
        raise ValueError(f"batch too large: max {MAX_BATCH_SIZE}, got {len(images_payload)}")
    images: list[Image.Image] = []
    for item in images_payload:
        url: str | None = None
        if isinstance(item, str):
            url = item
        elif isinstance(item, dict):
            if isinstance(item.get("image_url"), dict):
                url = item["image_url"].get("url")
            elif isinstance(item.get("image_url"), str):
                url = item.get("image_url")
            elif isinstance(item.get("url"), str):
                url = item.get("url")
            elif isinstance(item.get("data_url"), str):
                url = item.get("data_url")
        if not isinstance(url, str):
            raise ValueError("each image must be a data URL string or object containing image_url/url/data_url")
        images.append(_resize_image(_image_from_data_url(url)))
    return prompt, images


def _message(prompt: str, image: Image.Image) -> list[dict[str, Any]]:
    return [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]


def _generation_config_for(payload: dict[str, Any]) -> dict[str, Any]:
    generation_config = dict(_generation_config or {})
    max_tokens = int(payload.get("max_tokens") or MAX_NEW_TOKENS)
    generation_config["max_new_tokens"] = max(1, min(MAX_NEW_TOKENS, max_tokens))
    generation_config["do_sample"] = False
    return generation_config


def _run_single(prompt: str, image: Image.Image, generation_config: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    messages = _message(prompt, image)
    if hasattr(_model, "prepare_inputs") and hasattr(_model, "generate_from_prepared"):
        prepared = _model.prepare_inputs(messages)
        text, stats = _model.generate_from_prepared(prepared, generation_config, block_label="ocr")
        return text, stats
    text, _history = _model.chat(messages=messages, generation_config=generation_config)
    return text, None


def _run_batch(prompt: str, images: list[Image.Image], generation_config: dict[str, Any], early_stop_ratio: float) -> tuple[list[dict[str, Any]], dict[str, float]]:
    if not hasattr(_model, "prepare_inputs") or not hasattr(_model, "batch_generate"):
        raise RuntimeError("Loaded PaddleOCR-VL wrapper does not support batch_generate")
    prepare_start = time.perf_counter()
    prepared = [_model.prepare_inputs(_message(prompt, image)) for image in images]
    prepare_seconds = time.perf_counter() - prepare_start
    generate_start = time.perf_counter()
    results, unfinished = _model.batch_generate(
        prepared,
        max_new_tokens=int(generation_config.get("max_new_tokens") or MAX_NEW_TOKENS),
        eos_token_id=_model.tokenizer.eos_token_id,
        block_labels=["ocr"] * len(prepared),
        early_stop_ratio=early_stop_ratio,
    )
    generate_seconds = time.perf_counter() - generate_start
    if unfinished:
        raise RuntimeError(f"batch_generate returned unfinished slots: {unfinished}")
    pages: list[dict[str, Any]] = []
    for index, (text, stats) in enumerate(results, start=1):
        pages.append({"index": index, "text": text or "", "chars": len(text or ""), "stats": stats or {}})
    return pages, {"prepare_seconds": prepare_seconds, "generate_seconds": generate_seconds, "total_seconds": prepare_seconds + generate_seconds}


class Handler(BaseHTTPRequestHandler):
    server_version = "DokOCRPaddleVLOpenVINO/0.2"

    def log_message(self, fmt: str, *args) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/health", "/v1/health"}:
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "model": MODEL_ID,
                    "engine": "paddleocr-vl-openvino",
                    "openvino": ov.get_version(),
                    "batch_generate": bool(hasattr(_model, "batch_generate")),
                    "max_batch_size": MAX_BATCH_SIZE,
                },
            )
            return
        if path == "/v1/models":
            _json_response(self, 200, {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "dokocr"}]})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = _read_json(self)
            generation_config = _generation_config_for(payload)
            if path == "/v1/chat/completions":
                prompt, image = _extract_text_and_image(payload)
                start = time.perf_counter()
                with _model_lock:
                    response_text, stats = _run_single(prompt, image, generation_config)
                elapsed = time.perf_counter() - start
                LOG.info("OCR completed chars=%s seconds=%.2f", len(response_text or ""), elapsed)
                _json_response(
                    self,
                    200,
                    {
                        "id": f"paddlevl-ov-{int(time.time() * 1000)}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": MODEL_ID,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                        "timings": {"total_seconds": elapsed},
                        "stats": stats or {},
                    },
                )
                return
            if path == "/v1/ocr/batch":
                prompt, images = _extract_batch(payload)
                early_stop_ratio = float(payload.get("early_stop_ratio") or 0.0)
                start = time.perf_counter()
                with _model_lock:
                    pages, timings = _run_batch(prompt, images, generation_config, early_stop_ratio)
                elapsed = time.perf_counter() - start
                timings["wall_seconds"] = elapsed
                LOG.info("Batch OCR completed pages=%s chars=%s seconds=%.2f timings=%s", len(pages), sum(p["chars"] for p in pages), elapsed, timings)
                _json_response(
                    self,
                    200,
                    {
                        "id": f"paddlevl-ov-batch-{int(time.time() * 1000)}",
                        "object": "ocr.batch",
                        "created": int(time.time()),
                        "model": MODEL_ID,
                        "batch_size": len(pages),
                        "pages": pages,
                        "timings": timings,
                    },
                )
                return
            _json_response(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            LOG.exception("OCR request failed path=%s", path)
            _json_response(self, 500, {"error": str(exc)})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _load_model()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    LOG.info("Serving PaddleOCR-VL OpenVINO on %s:%s", HOST, PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
