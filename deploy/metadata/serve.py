#!/usr/bin/env python3
"""Validate the backend, provision pinned LFM weights, then exec the patched server."""
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import urllib.request

NAME = "LFM2.5-8B-A1B-Q5_K_M.gguf"
REVISION = "49c14831707011e64d70b2ebd8462ba08d608434"
URL = f"https://huggingface.co/LiquidAI/LFM2.5-8B-A1B-GGUF/resolve/{REVISION}/{NAME}"
SIZE = 6030339296
SHA256 = "eb8bd10148ea21e195502d6d6a205983ba40815302068ce72eb160684df92b3e"
CHUNK = 4 * 1024 * 1024


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK):
            result.update(chunk)
    return result.hexdigest()


def ensure_model(directory, url=URL, size=SIZE, sha256=SHA256):
    """Resume our partial download; never overwrite an existing invalid model."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / NAME
    partial = directory / (NAME + ".partial")
    lock = directory / (NAME + ".lock")
    for path in (model, partial, lock):
        if path.is_symlink():
            raise RuntimeError(f"Refusing symlink at model-managed path: {path}")
    with lock.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        if model.exists():
            if model.stat().st_size != size or digest(model) != sha256:
                raise RuntimeError(f"Existing model checksum mismatch: {model}; preserved, not overwritten")
            return model
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            raise RuntimeError(f"Oversized partial model: {partial}; move it aside before retrying")
        if offset == size:
            if digest(partial) != sha256:
                raise RuntimeError(f"Partial model checksum mismatch: {partial}; move it aside before retrying")
        else:
            if shutil.disk_usage(directory).free < size - offset + 128 * 1024 * 1024:
                raise RuntimeError("Not enough disk space for LFM model download (6.1 GB plus working space)")
            print(f"Downloading {NAME} ({size} bytes; resuming at {offset}); first start can take several minutes", flush=True)
            headers = {"User-Agent": "DokOCR-model-setup"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
                if response.status == 206:
                    expected_range = f"bytes {offset}-{size - 1}/{size}"
                    if response.headers.get("Content-Range") != expected_range:
                        raise RuntimeError("Unexpected model download Content-Range; partial download preserved")
                elif response.status == 200:
                    # Some mirrors ignore Range. Restart only our incomplete download.
                    offset = 0
                    if shutil.disk_usage(directory).free < size + 128 * 1024 * 1024:
                        raise RuntimeError("Mirror cannot resume; not enough disk space to restart download")
                else:
                    raise RuntimeError(f"Unexpected model download status: {response.status}")
                with partial.open("ab" if offset else "wb") as output:
                    received = offset
                    while chunk := response.read(CHUNK):
                        received += len(chunk)
                        if received > size:
                            raise RuntimeError("Model download exceeded expected size")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if partial.stat().st_size != size or digest(partial) != sha256:
                raise RuntimeError(f"Incomplete or checksum-mismatched model download: {partial}; no model activated")
        os.replace(partial, model)
        print("LFM model checksum verified", flush=True)
        return model


def integer_setting(name, default, minimum):
    value = os.environ.get(name, default)
    if not value or not value.isascii() or not value.isdecimal() or len(value) > 10:
        raise ValueError(f"{name} must be an integer from {minimum} to 2147483647")
    number = int(value)
    if not minimum <= number <= 2147483647:
        raise ValueError(f"{name} must be an integer from {minimum} to 2147483647")
    return number


def runtime_options():
    compute = os.environ.get("DOKOCR_METADATA_COMPUTE", "cpu")
    if compute not in ("cpu", "cuda", "vulkan"):
        raise ValueError("DOKOCR_METADATA_COMPUTE must be cpu, cuda, or vulkan")
    threads = integer_setting("DOKOCR_METADATA_THREADS", "4", 1)
    layers = None
    if "DOKOCR_METADATA_GPU_LAYERS" in os.environ:
        layers = integer_setting("DOKOCR_METADATA_GPU_LAYERS", None, 0)
    devices = os.environ.get("DOKOCR_METADATA_DEVICES")
    if devices is not None and (not devices.strip() or any(ord(c) < 32 or ord(c) == 127 for c in devices)):
        raise ValueError("DOKOCR_METADATA_DEVICES must be nonempty and contain no control characters")
    if compute == "cpu":
        if layers is not None or devices is not None:
            raise ValueError("DOKOCR_METADATA_GPU_LAYERS / DOKOCR_METADATA_DEVICES requires cuda or vulkan compute")
        return threads, ["--gpu-layers", "0", "--device", "none"]

    # Pinned ik otherwise silently uses CPU when a backend/device is unavailable.
    # Its public ggml API needs no model; shared GPU images expose these symbols.
    backend, prefix = ("cuda", "CUDA") if compute == "cuda" else ("vk", "Vulkan")
    try:
        library = ctypes.CDLL("libggml.so")
        count = getattr(library, f"ggml_backend_{backend}_get_device_count")
        count.argtypes = []
        count.restype = ctypes.c_int
        available = [f"{prefix}{i}" for i in range(count())]
    except (OSError, AttributeError) as error:
        raise RuntimeError(f"{compute} backend unavailable; use the matching metadata image and host GPU drivers: {error}") from error
    if not available:
        raise RuntimeError(f"{compute} backend has no visible GPU devices; check host drivers and container device access")
    if devices is not None and any(device not in available for device in devices.split(",")):
        raise RuntimeError(f"DOKOCR_METADATA_DEVICES is unavailable for {compute}; available: {','.join(available)}")
    options = ["--fit"] if layers is None else ["--gpu-layers", str(layers)]
    # ponytail: pinned Vulkan lacks fused weight ops; avoid CPU expert-weight round-trips.
    # Keep fused weighted reduction: Vulkan MULTI_ADD has truncated expert-view bounds.
    if compute == "vulkan":
        options += ["--no-fused-moe", "--no-fused-up-gate"]
    if devices is not None:
        options += ["--device", devices]
    return threads, options


def main():
    threads, offload = runtime_options()
    model = ensure_model("/models")
    command = ["/usr/local/bin/llama-server", "--model", str(model),
               "--alias", "metadata", "--host", "0.0.0.0", "--port", "8080",
               "--jinja", "--ctx-size", "128000", "--parallel", "1",
               "--batch-size", "1024", "--ubatch-size", "512",
               "--threads", str(threads), "--threads-batch", str(threads),
               "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
               "--ctx-checkpoints", "0", "--ctx-checkpoints-interval", "0",
               "--no-warmup", "--spec-type", "none", "--reasoning-budget", "3072",
               "--flash-attn", "on", "--webui", "none"] + offload
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
