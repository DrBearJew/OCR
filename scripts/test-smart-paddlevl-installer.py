#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SMART_COMPOSE = ROOT / "app" / "docker-compose.smart.yml"
APP_COMPOSE = ROOT / "app" / "docker-compose.yml"
INSTALLER = ROOT / "scripts" / "install-smart-paddlevl.sh"
DOCTOR = ROOT / "scripts" / "doctor-smart-runtime.py"
MODEL_RUNTIME_DIR = ROOT / "deploy" / "model-runtime"
MODEL_RUNTIME_README = MODEL_RUNTIME_DIR / "README.md"
MODEL_RUNTIME_CONFIG = MODEL_RUNTIME_DIR / "llama-swap.config.yaml"
MODEL_RUNTIME_DOCKERFILE = MODEL_RUNTIME_DIR / "Dockerfile"
MODEL_RUNTIME_ENTRYPOINT = MODEL_RUNTIME_DIR / "entrypoint.sh"
ROOT_README = ROOT / "README.md"
APP_README = ROOT / "app" / "README.md"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    for path in (
        SMART_COMPOSE,
        APP_COMPOSE,
        INSTALLER,
        DOCTOR,
        MODEL_RUNTIME_README,
        MODEL_RUNTIME_CONFIG,
        MODEL_RUNTIME_DOCKERFILE,
        MODEL_RUNTIME_ENTRYPOINT,
        ROOT_README,
        APP_README,
    ):
        check(path.exists(), f"missing {path}")

    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    subprocess.run(["bash", "-n", str(MODEL_RUNTIME_ENTRYPOINT)], check=True)
    subprocess.run(["python3", "-m", "py_compile", str(DOCTOR)], check=True)

    smart = SMART_COMPOSE.read_text(encoding="utf-8")
    check("model-runtime:" in smart, "smart compose lacks model-runtime service")
    check("DOKOCR_MODEL_RUNTIME_IMAGE:?" in smart, "smart compose must require an explicitly prepared image")
    check('QWEN_METADATA_THINKING_ENABLED: "true"' in smart, "LFM metadata must enable thinking")
    check('127.0.0.1:${DOKOCR_MODEL_RUNTIME_PORT:-8092}:8092' in smart, "gateway must not default to public exposure")
    check("http://model-runtime:8092/v1" in smart, "smart compose should use service DNS endpoint")
    check("PADDLE_VL_LLAMACPP_BASE_URL" in smart and "QWEN_LLAMACPP_BASE_URL" in smart and "GLM_LLAMACPP_BASE_URL" in smart, "smart compose must configure all model roles")
    check("smart-proxy" not in smart and "qwen-router" not in smart, "smart compose must not use retired proxy/router")
    check("service_healthy" in smart, "app services should wait for model-runtime health")

    config = MODEL_RUNTIME_CONFIG.read_text(encoding="utf-8")
    for model_id in ("paddleocr-vl", "metadata", "metadata-gemma", "glm"):
        check(f'"{model_id}"' in config, f"model-runtime config missing {model_id}")
    for alias in ("metadata-model", "qwen-mtp", "qwen3.5-2b", "qwen", "glm-ocr"):
        check(alias in config, f"model-runtime config missing alias {alias}")
    check("IK_PADDLEOCR_OPENVINO_MODEL_DIR=${paddle_ov_model}" in config, "PaddleOCR route must use its matching OpenVINO model")
    check("LFM2.5-8B-A1B-Q5_K_M.gguf" in config, "metadata must use the tested LFM model")
    check("--reasoning-budget 3072" in config and "--spec-type none" in config, "LFM must reserve JSON tokens without speculation")
    check("--model-draft" not in config, "runtime must not configure a draft model")
    check("IK_PADDLEOCR_OPENVINO_SIDECAR_FORCE_REPLACE=1" in config, "PaddleOCR replacement must remain force-gated")
    check("/opt/dokocr/ik-paddle/bin/llama-server" in config, "config should use in-image ik-paddle binary path")

    dockerfile = MODEL_RUNTIME_DOCKERFILE.read_text(encoding="utf-8")
    check("DOKOCR_IK_RUNTIME_TARBALL_URL" in dockerfile, "model-runtime build should consume a prebuilt ik artifact")
    check("cmake --build" not in dockerfile and "git clone" not in dockerfile, "model-runtime image must not compile ik in user path")
    check("llama-swap" in dockerfile, "model-runtime image must install llama-swap")
    check(dockerfile.count("sha256sum -c -") == 2, "both downloaded archives must be checksum-verified")
    check(dockerfile.index("sha256sum -c -") < dockerfile.index("tar -xzf"), "verify archives before extraction")

    entrypoint = MODEL_RUNTIME_ENTRYPOINT.read_text(encoding="utf-8")
    check("paddleocr-vl-openvino-direct-pos-0049/model/manifest.json" in entrypoint, "entrypoint must guard fixed-grid OV manifest presence")
    check("llama-swap -config" in entrypoint, "entrypoint must run llama-swap")
    check("LFM2.5-8B-A1B-Q5_K_M.gguf" in entrypoint, "entrypoint must guard LFM asset presence")
    check("llama-paddleocr-openvino-dry-run" in entrypoint, "entrypoint must guard the vision helper")
    check("/opt/dokocr/glm/" not in entrypoint and "glm/glm.gguf" not in entrypoint, "optional GLM must not block runtime startup")
    doctor = runpy.run_path(str(DOCTOR))
    check("glm" not in doctor["REQUIRED_MODELS"] and "glm" in doctor["OPTIONAL_ALIASES"], "doctor must treat GLM as optional")

    compose = APP_COMPOSE.read_text(encoding="utf-8")
    check("127.0.0.1:5432:5432" in compose and "127.0.0.1:6379:6379" in compose, "database/broker host ports must be loopback-only")
    check("&& exec uvicorn" in compose, "backend must receive graceful shutdown signals")

    installer = INSTALLER.read_text(encoding="utf-8")
    check("LEGACY" in installer, "old installer must be marked legacy")
    check("docker-compose.smart.yml" in installer, "old installer should point new users to smart compose")
    check("> docker-compose.yml" not in installer and ">> docker-compose.yml" not in installer, "installer should not write docker-compose.yml")

    root_readme = ROOT_README.read_text(encoding="utf-8")
    app_readme = APP_README.read_text(encoding="utf-8")
    for text, name in ((root_readme, "root README"), (app_readme, "app README")):
        check("docker-compose.smart.yml" in text, f"{name} must document smart compose")
        check("model-runtime" in text, f"{name} must document model-runtime")
        check("cmake -S" not in text and "cmake --build" not in text, f"{name} should not contain ik build commands for users")

    print("smart model-runtime packaging static checks passed")


if __name__ == "__main__":
    main()
