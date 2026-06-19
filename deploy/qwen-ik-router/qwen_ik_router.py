#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import signal
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LOG_LEVEL = os.getenv("QWEN_IK_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

PUBLIC_HOST = os.getenv("QWEN_IK_PUBLIC_HOST", "172.18.0.1")
PUBLIC_PORT = int(os.getenv("QWEN_IK_PUBLIC_PORT", "18082"))
CHILD_HOST = os.getenv("QWEN_IK_CHILD_HOST", "127.0.0.1")
CHILD_PORT = int(os.getenv("QWEN_IK_CHILD_PORT", "18083"))
CHILD_URL = f"http://{CHILD_HOST}:{CHILD_PORT}"

MODEL_ID = os.getenv("QWEN_IK_MODEL_ID", "gemma-4-e2b-it-q8")
ALIASES = [item.strip() for item in os.getenv("QWEN_IK_ALIASES", "gemma-4-e2b-it-q8,gemma-e2b,qwen-mtp,qwen3.5-2b,qwen").split(",") if item.strip()]
BINARY = os.getenv("QWEN_IK_BINARY", "/root/ik_llama.cpp/build/bin/llama-server")
MODEL = os.getenv("QWEN_IK_MODEL", "/root/llm-models/gemma-4-E2B-it/gemma-4-E2B-it-Q8_0.gguf")
CHAT_TEMPLATE_FILE = os.getenv("QWEN_IK_CHAT_TEMPLATE_FILE", "/root/llm-models/gemma-4-E2B-it/google-gemma4-E2B-chat_template-main.jinja")
SPEC_TYPE = os.getenv("QWEN_IK_SPEC_TYPE", "ngram-mod:n_max=64,n_min=2,ngram_size_n=8").strip()

CTX_SIZE = os.getenv("QWEN_IK_CTX_SIZE", "4096")
BATCH_SIZE = os.getenv("QWEN_IK_BATCH_SIZE", "1024")
UBATCH_SIZE = os.getenv("QWEN_IK_UBATCH_SIZE", "512")
THREADS = os.getenv("QWEN_IK_THREADS", "4")
THREADS_BATCH = os.getenv("QWEN_IK_THREADS_BATCH", THREADS)
CACHE_TYPE_K = os.getenv("QWEN_IK_CACHE_TYPE_K", "q8_0")
CACHE_TYPE_V = os.getenv("QWEN_IK_CACHE_TYPE_V", "q8_0")
CACHE_RAM = os.getenv("QWEN_IK_CACHE_RAM", "0")
RUN_TIME_REPACK = os.getenv("QWEN_IK_RUN_TIME_REPACK", "0").strip().lower() not in {"", "0", "false", "no", "off"}
START_TIMEOUT_SECONDS = float(os.getenv("QWEN_IK_START_TIMEOUT_SECONDS", "90"))
STOP_TIMEOUT_SECONDS = float(os.getenv("QWEN_IK_STOP_TIMEOUT_SECONDS", "20"))
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("QWEN_IK_UPSTREAM_TIMEOUT_SECONDS", "360"))
LOG_DIR = Path(os.getenv("QWEN_IK_LOG_DIR", "/var/log/qwen-ik-router"))
CHILD_LOG = LOG_DIR / "llama-server.log"

_lock = threading.RLock()
_proc: subprocess.Popen[bytes] | None = None


def _model_matches(name: str) -> bool:
    normalized = (name or "").strip().lower()
    return not normalized or normalized == MODEL_ID.lower() or normalized in {alias.lower() for alias in ALIASES}


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _child_health(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{CHILD_URL}/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _status_value() -> str:
    if not _is_running():
        return "unloaded"
    if _child_health(timeout=0.5):
        return "loaded"
    return "loading"


def _build_cmd() -> list[str]:
    cmd = [
        BINARY,
        "--model", MODEL,
        "--alias", MODEL_ID,
        "--host", CHILD_HOST,
        "--port", str(CHILD_PORT),
        "--ctx-size", str(CTX_SIZE),
        "--batch-size", str(BATCH_SIZE),
        "--ubatch-size", str(UBATCH_SIZE),
        "--threads", str(THREADS),
        "--threads-batch", str(THREADS_BATCH),
        "--cache-type-k", CACHE_TYPE_K,
        "--cache-type-v", CACHE_TYPE_V,
        "--cache-ram", str(CACHE_RAM),
        "--ctx-checkpoints", "0",
        "--ctx-checkpoints-interval", "0",
        "--no-warmup",
    ]
    if RUN_TIME_REPACK:
        cmd += ["--run-time-repack"]
    if CHAT_TEMPLATE_FILE:
        cmd += ["--chat-template-file", CHAT_TEMPLATE_FILE]
    if SPEC_TYPE:
        cmd += ["--spec-type", SPEC_TYPE]
    extra = os.getenv("QWEN_IK_EXTRA_ARGS", "").strip()
    if extra:
        cmd += shlex.split(extra)
    return cmd


def _ensure_child() -> None:
    global _proc
    with _lock:
        if _is_running() and _child_health(timeout=1.0):
            return
        if _proc is not None and _proc.poll() is not None:
            logging.warning("Previous ik child exited rc=%s", _proc.returncode)
            _proc = None
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        cmd = _build_cmd()
        logging.info("Starting ik Qwen child: %s", " ".join(cmd))
        log_handle = CHILD_LOG.open("ab", buffering=0)
        _proc = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _proc.poll() is not None:
                raise RuntimeError(f"ik child exited during startup rc={_proc.returncode}; see {CHILD_LOG}")
            if _child_health(timeout=1.0):
                logging.info("ik Qwen child ready pid=%s", _proc.pid)
                return
            time.sleep(0.5)
        raise TimeoutError(f"Timed out waiting for ik Qwen child health; see {CHILD_LOG}")


def _stop_child() -> bool:
    global _proc
    with _lock:
        proc = _proc
        _proc = None
        if proc is None or proc.poll() is not None:
            return True
        logging.info("Stopping ik Qwen child pid=%s", proc.pid)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        deadline = time.time() + STOP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if proc.poll() is not None:
                logging.info("ik Qwen child stopped rc=%s", proc.returncode)
                return True
            time.sleep(0.25)
        logging.warning("ik Qwen child did not stop after %.1fs; killing", STOP_TIMEOUT_SECONDS)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return True


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _models_payload() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "aliases": ALIASES,
                "object": "model",
                "owned_by": "ik_llama.cpp",
                "status": {
                    "value": _status_value(),
                    "runtime": "ik_llama.cpp",
                    "spec_type": SPEC_TYPE or "none",
                    "binary": BINARY,
                },
            }
        ],
    }


def _proxy_chat(handler: BaseHTTPRequestHandler) -> None:
    payload = _read_json(handler)
    requested = str(payload.get("model") or MODEL_ID)
    if not _model_matches(requested):
        _send_json(handler, {"error": {"message": f"model {requested!r} is not served by qwen-ik-router"}}, 404)
        return
    payload["model"] = MODEL_ID
    _ensure_child()
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{CHILD_URL}{handler.path}",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT_SECONDS) as resp:
            body = resp.read()
            handler.send_response(resp.status)
            handler.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        handler.send_response(exc.code)
        handler.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "qwen-ik-router/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
        logging.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/healthz"}:
            _send_json(self, {"ok": True, "child_status": _status_value(), "model": MODEL_ID, "runtime": "ik_llama.cpp"})
            return
        if self.path in {"/models", "/v1/models"}:
            _send_json(self, _models_payload())
            return
        _send_json(self, {"error": {"message": "not found"}}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path in {"/models/unload", "/v1/unload", "/unload"}:
            payload = _read_json(self)
            requested = str(payload.get("model") or payload.get("model_id") or MODEL_ID)
            if not _model_matches(requested):
                _send_json(self, {"success": False, "error": f"unknown model {requested!r}"}, 404)
                return
            ok = _stop_child()
            _send_json(self, {"success": ok, "model": MODEL_ID})
            return
        if self.path in {"/v1/chat/completions", "/chat/completions"}:
            try:
                _proxy_chat(self)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Qwen ik proxy failed")
                _send_json(self, {"error": {"message": str(exc), "type": "qwen_ik_router_error"}}, 502)
            return
        _send_json(self, {"error": {"message": "not found"}}, 404)


def _shutdown(signum: int, _frame: Any) -> None:
    logging.info("Signal %s received; shutting down", signum)
    _stop_child()
    raise SystemExit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    logging.info("Starting qwen ik router on %s:%s child=%s model=%s spec=%s", PUBLIC_HOST, PUBLIC_PORT, CHILD_URL, MODEL, SPEC_TYPE or "none")
    ThreadingHTTPServer((PUBLIC_HOST, PUBLIC_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
