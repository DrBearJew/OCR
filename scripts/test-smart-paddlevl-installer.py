#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-smart-paddlevl.sh"
PROXY = ROOT / "deploy" / "smart-proxy" / "proxy_app.py"
TEMPLATE = ROOT / "deploy" / "paddlevl" / "paddleocr-vl-chat_template.jinja"
MODELS_INI = ROOT / "deploy" / "paddlevl" / "models.ini"
OPENVINO_SERVER = ROOT / "deploy" / "paddlevl" / "openvino_paddlevl_server.py"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    for path in (INSTALLER, PROXY, TEMPLATE, MODELS_INI, OPENVINO_SERVER):
        check(path.exists(), f"missing {path}")
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    installer = INSTALLER.read_text(encoding="utf-8")
    check("--dry-run" in installer, "installer lacks --dry-run")
    check("--skip-download" in installer, "installer lacks --skip-download")
    check("--backend" in installer and "openvino-cpu" in installer, "installer lacks OpenVINO backend selector")
    check('BACKEND="${DOKOCR_PADDLE_BACKEND:-openvino-cpu}"' in installer, "installer should default to the tested OpenVINO CPU OCR gateway")
    check("GPU/native/remote PaddleOCR-VL endpoint" in installer, "installer should tell GPU/remote users to skip local OCR provisioning")
    check("deploy/qwen-ik-router" in installer, "installer should point CPU metadata users to the ik_llama sidecar")
    check("openvino==2025.2.0" in installer, "installer must pin working OpenVINO 2025.2")
    check("DOKOCR_PADDLE_MODEL_URL" in installer, "installer lacks model URL override")
    check("DOKOCR_PADDLE_MMPROJ_URL" in installer, "installer lacks mmproj URL override")
    check("Admin -> Model Setup" in installer, "installer does not print Admin setup guidance")
    check("OCR_TASK_PADDLE_VL_SECONDS_PER_CHUNK" in installer, "installer does not document OCR time-budget setting")
    check("> docker-compose.yml" not in installer and ">> docker-compose.yml" not in installer, "installer should not write docker-compose.yml")
    template = TEMPLATE.read_text(encoding="utf-8")
    check("image_url" in template, "template must accept OpenAI image_url")
    check("<|IMAGE_PLACEHOLDER|>" in template, "template missing image placeholder")
    proxy = PROXY.read_text(encoding="utf-8")
    check("os.getenv(\"LLAMA_URL\"" in proxy, "proxy must use LLAMA_URL env")
    check("os.getenv(\"LLAMA_ADMIN\"" in proxy, "proxy must use LLAMA_ADMIN env")
    check("data[\"temperature\"] = 0.0" in proxy, "proxy OCR must be deterministic")
    check("repeat_penalty" in proxy and "repeat_last_n" in proxy, "proxy lacks repeat controls")
    models = MODELS_INI.read_text(encoding="utf-8")
    check("[paddleocr-vl]" in models, "models.ini lacks paddle preset")
    check("paddleocr-vl-q8_0.gguf" in models, "models.ini lacks model path")
    check("paddleocr-vl-mmproj.gguf" in models, "models.ini lacks mmproj path")
    openvino_server = OPENVINO_SERVER.read_text(encoding="utf-8")
    check("/v1/ocr/batch" in openvino_server, "OpenVINO gateway lacks batch endpoint")
    check("batch_generate" in openvino_server, "OpenVINO gateway lacks batch_generate path")
    check("PADDLE_OV_MODEL_PATH" in openvino_server, "OpenVINO gateway lacks model path env override")
    print("smart PaddleVL installer static checks passed")


if __name__ == "__main__":
    main()
