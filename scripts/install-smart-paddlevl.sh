#!/usr/bin/env bash
set -Eeuo pipefail

# One-click installer for Dok OCR smart PaddleOCR-VL stack.
# Supports two backends:
#   - llamacpp: legacy GGUF + smart-proxy gateway for llama.cpp/LM Studio style OCR.
#   - openvino-cpu: CPU OpenVINO 2025.2 gateway with /v1/ocr/batch for up to 4 pages.
#
# The installer is intentionally idempotent. It writes helper assets/services and
# prints Admin -> Model Setup values; it does not edit Dok OCR .env or
# docker-compose.yml.

INSTALL_DIR="${DOKOCR_SMART_INSTALL_DIR:-/opt/dokocr-smart-paddlevl}"
MODELS_DIR="${DOKOCR_MODELS_DIR:-/root/llm-models}"
SMART_PROXY_DIR="${DOKOCR_SMART_PROXY_DIR:-$INSTALL_DIR/smart-proxy}"
SMART_PROXY_IMAGE="${DOKOCR_SMART_PROXY_IMAGE:-dokocr-smart-proxy:latest}"
SMART_PROXY_CONTAINER="${DOKOCR_SMART_PROXY_CONTAINER:-smart-proxy}"
SMART_PROXY_NETWORK="${DOKOCR_SMART_PROXY_NETWORK:-app_default}"
LLAMA_HOST="${DOKOCR_LLAMA_HOST:-172.18.0.1}"
LLAMA_PORT="${DOKOCR_LLAMA_PORT:-1234}"
LLAMA_BASE_URL="http://${LLAMA_HOST}:${LLAMA_PORT}"
LLAMA_SERVER_BIN="${DOKOCR_LLAMA_SERVER_BIN:-/root/llama.cpp-master-mtp/build/bin/llama-server}"
MODEL_MANAGER_PIDFILE="${DOKOCR_LLAMA_PIDFILE:-$INSTALL_DIR/llama-server.pid}"
PADDLE_MODEL_FILE="${DOKOCR_PADDLE_MODEL_FILE:-$MODELS_DIR/paddleocr-vl-q8_0.gguf}"
PADDLE_MMPROJ_FILE="${DOKOCR_PADDLE_MMPROJ_FILE:-$MODELS_DIR/paddleocr-vl-mmproj.gguf}"
PADDLE_TEMPLATE_FILE="${DOKOCR_PADDLE_TEMPLATE_FILE:-$MODELS_DIR/paddleocr-vl-chat_template.jinja}"
PADDLE_MODEL_URL="${DOKOCR_PADDLE_MODEL_URL:-}"
PADDLE_MMPROJ_URL="${DOKOCR_PADDLE_MMPROJ_URL:-}"

OPENVINO_ROOT="${DOKOCR_OPENVINO_ROOT:-/opt/paddleocr-vl-openvino}"
OPENVINO_VENV="${DOKOCR_OPENVINO_VENV:-$OPENVINO_ROOT/.venv-2025.2}"
OPENVINO_REPO_DIR="${DOKOCR_OPENVINO_REPO_DIR:-$OPENVINO_ROOT/paddleocr_vl_ov_add_layout}"
OPENVINO_MODEL_DIR="${DOKOCR_OPENVINO_MODEL_DIR:-$OPENVINO_ROOT/modelscope-cache/zhaohb/PaddleOCR-Vl-OV}"
OPENVINO_MODEL_REPO="${DOKOCR_OPENVINO_MODEL_REPO:-zhaohb/PaddleOCR-Vl-OV}"
OPENVINO_UPSTREAM_REPO="${DOKOCR_OPENVINO_UPSTREAM_REPO:-https://github.com/zhaohb/paddleocr_vl_ov.git}"
OPENVINO_UPSTREAM_BRANCH="${DOKOCR_OPENVINO_UPSTREAM_BRANCH:-add_layout}"
OPENVINO_SERVICE_NAME="${DOKOCR_OPENVINO_SERVICE_NAME:-dokocr-paddlevl-openvino}"
OPENVINO_PORT="${DOKOCR_OPENVINO_PORT:-8091}"
OPENVINO_MAX_BATCH_SIZE="${DOKOCR_OPENVINO_MAX_BATCH_SIZE:-4}"
OPENVINO_MODEL_ID="${DOKOCR_OPENVINO_MODEL_ID:-paddleocr-vl}"
APP_NETWORK="${DOKOCR_APP_NETWORK:-app_default}"

BACKEND="${DOKOCR_PADDLE_BACKEND:-llamacpp}"
SKIP_DOWNLOAD=0
DRY_RUN=0
START_SERVICES=1

usage() {
  cat <<USAGE
Usage: $0 [--backend llamacpp|openvino-cpu] [--openvino-cpu] [--llamacpp] [--dry-run] [--skip-download] [--no-start]

Backends:
  llamacpp       Legacy GGUF + smart-proxy gateway. Requires llama-server.
  openvino-cpu   CPU OpenVINO 2025.2 gateway with /v1/ocr/batch up to 4 pages.

Common environment overrides:
  DOKOCR_PADDLE_BACKEND          default: llamacpp
  DOKOCR_APP_NETWORK             Docker network used by Dok OCR, default app_default

llamacpp overrides:
  DOKOCR_SMART_INSTALL_DIR       default: /opt/dokocr-smart-paddlevl
  DOKOCR_MODELS_DIR              default: /root/llm-models
  DOKOCR_PADDLE_MODEL_URL        optional URL for paddleocr-vl-q8_0.gguf
  DOKOCR_PADDLE_MMPROJ_URL       optional URL for paddleocr-vl-mmproj.gguf
  DOKOCR_LLAMA_SERVER_BIN        llama-server binary path
  DOKOCR_SMART_PROXY_NETWORK     Docker network to attach smart-proxy to, default app_default

openvino-cpu overrides:
  DOKOCR_OPENVINO_ROOT           default: /opt/paddleocr-vl-openvino
  DOKOCR_OPENVINO_MODEL_DIR      default: <root>/modelscope-cache/zhaohb/PaddleOCR-Vl-OV
  DOKOCR_OPENVINO_MODEL_REPO     default: zhaohb/PaddleOCR-Vl-OV
  DOKOCR_OPENVINO_SERVICE_NAME   default: dokocr-paddlevl-openvino
  DOKOCR_OPENVINO_PORT           default: 8091
  DOKOCR_OPENVINO_MAX_BATCH_SIZE default: 4

Examples:
  sudo scripts/install-smart-paddlevl.sh --backend openvino-cpu
  sudo scripts/install-smart-paddlevl.sh --backend llamacpp
  sudo DOKOCR_PADDLE_MODEL_URL=https://.../paddleocr-vl-q8_0.gguf \
       DOKOCR_PADDLE_MMPROJ_URL=https://.../paddleocr-vl-mmproj.gguf \
       scripts/install-smart-paddlevl.sh --backend llamacpp
  scripts/install-smart-paddlevl.sh --backend openvino-cpu --dry-run --skip-download --no-start
USAGE
}

log() { printf "[smart-paddlevl] %s\n" "$*"; }
run() { if [[ "$DRY_RUN" == 1 ]]; then printf "DRY-RUN: %q" "$1"; shift || true; printf " %q" "$@"; printf "\n"; else "$@"; fi; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) BACKEND="${2:-}"; shift ;;
    --openvino-cpu) BACKEND="openvino-cpu" ;;
    --llamacpp) BACKEND="llamacpp" ;;
    --dry-run) DRY_RUN=1 ;;
    --skip-download) SKIP_DOWNLOAD=1 ;;
    --no-start) START_SERVICES=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

case "$BACKEND" in
  llama|llamacpp) BACKEND="llamacpp" ;;
  openvino|openvino-cpu) BACKEND="openvino-cpu" ;;
  *) echo "Unknown backend: $BACKEND" >&2; usage; exit 2 ;;
esac

need_cmd python3
need_cmd curl

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_SRC="$REPO_ROOT/deploy/smart-proxy/proxy_app.py"
TEMPLATE_SRC="$REPO_ROOT/deploy/paddlevl/paddleocr-vl-chat_template.jinja"
MODELS_INI_SRC="$REPO_ROOT/deploy/paddlevl/models.ini"
OPENVINO_SERVER_SRC="$REPO_ROOT/deploy/paddlevl/openvino_paddlevl_server.py"

[[ -f "$PROXY_SRC" ]] || { echo "Missing $PROXY_SRC" >&2; exit 1; }
[[ -f "$TEMPLATE_SRC" ]] || { echo "Missing $TEMPLATE_SRC" >&2; exit 1; }
[[ -f "$MODELS_INI_SRC" ]] || { echo "Missing $MODELS_INI_SRC" >&2; exit 1; }
[[ -f "$OPENVINO_SERVER_SRC" ]] || { echo "Missing $OPENVINO_SERVER_SRC" >&2; exit 1; }

network_gateway() {
  if command -v docker >/dev/null 2>&1; then
    docker network inspect "$APP_NETWORK" --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true
  fi
}

write_admin_env() {
  local file="$1" base_url="$2" provider_note="$3"
  if [[ "$DRY_RUN" == 1 ]]; then
    log "Would write $file"
    return 0
  fi
  cat > "$file" <<ENV
# Use these values in Admin -> Model Setup
# $provider_note
OCR_PROVIDER=paddle_vl
PADDLE_VL_BASE_URL=$base_url
PADDLE_VL_MODEL=paddleocr-vl
GLM_BASE_URL=http://smart-proxy:8081/v1
GLM_MODEL=glm
QWEN_BASE_URL=http://smart-proxy:8081/v1
# OCR time budget defaults are user-editable in Admin -> Model Setup.
OCR_TASK_SOFT_TIME_LIMIT=600
OCR_TASK_TIME_LIMIT=660
OCR_TASK_BASE_OVERHEAD_SECONDS=300
OCR_TASK_PADDLE_VL_SECONDS_PER_CHUNK=180
ENV
}

download_if_needed() {
  local url="$1" dest="$2" label="$3"
  if [[ -s "$dest" ]]; then log "$label already exists: $dest"; return 0; fi
  if [[ "$SKIP_DOWNLOAD" == 1 ]]; then log "Skipping $label download; missing $dest"; return 0; fi
  if [[ -z "$url" ]]; then
    echo "Missing $label file: $dest" >&2
    echo "Set ${label}_URL env override or rerun with --skip-download after placing the file manually." >&2
    return 3
  fi
  log "Downloading $label to $dest"
  run curl -L --fail --retry 3 --retry-delay 5 -o "$dest.tmp" "$url"
  run mv "$dest.tmp" "$dest"
}

install_llamacpp_stack() {
  need_cmd docker
  log "Installing llama.cpp smart PaddleOCR-VL stack into $INSTALL_DIR"
  run mkdir -p "$INSTALL_DIR" "$SMART_PROXY_DIR" "$MODELS_DIR"
  run cp "$PROXY_SRC" "$SMART_PROXY_DIR/proxy_app.py"
  run cp "$TEMPLATE_SRC" "$PADDLE_TEMPLATE_FILE"
  run cp "$MODELS_INI_SRC" "$MODELS_DIR/models.ini"

  if [[ "$DRY_RUN" == 1 ]]; then
    log "Would write $SMART_PROXY_DIR/Dockerfile"
  else
    cat > "$INSTALL_DIR/smart-proxy.Dockerfile.tmp" <<DOCKERFILE
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask requests
COPY proxy_app.py /app/proxy_app.py
EXPOSE 8081
CMD ["python", "/app/proxy_app.py"]
DOCKERFILE
    mv "$INSTALL_DIR/smart-proxy.Dockerfile.tmp" "$SMART_PROXY_DIR/Dockerfile"
  fi

  download_if_needed "$PADDLE_MODEL_URL" "$PADDLE_MODEL_FILE" "DOKOCR_PADDLE_MODEL" || exit $?
  download_if_needed "$PADDLE_MMPROJ_URL" "$PADDLE_MMPROJ_FILE" "DOKOCR_PADDLE_MMPROJ" || exit $?

  if [[ "$START_SERVICES" == 1 ]]; then
    if [[ ! -x "$LLAMA_SERVER_BIN" ]]; then
      log "llama-server binary not found/executable at $LLAMA_SERVER_BIN; skipping model-manager start. Install llama.cpp or set DOKOCR_LLAMA_SERVER_BIN."
    elif [[ "$DRY_RUN" == 1 ]]; then
      log "Would start llama-server model manager on ${LLAMA_HOST}:${LLAMA_PORT}"
    elif ! curl -fsS "$LLAMA_BASE_URL/v1/models" >/dev/null 2>&1; then
      log "Starting llama-server model manager"
      nohup "$LLAMA_SERVER_BIN" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --models-dir "$MODELS_DIR" --models-preset "$MODELS_DIR/models.ini" --models-max 1 > "$INSTALL_DIR/llama-server.log" 2>&1 &
      echo $! > "$MODEL_MANAGER_PIDFILE"
      sleep 3
    else
      log "llama-server already reachable at $LLAMA_BASE_URL"
    fi

    log "Building smart-proxy image"
    run docker build -t "$SMART_PROXY_IMAGE" "$SMART_PROXY_DIR"
    if [[ "$DRY_RUN" == 1 ]]; then
      log "Would recreate $SMART_PROXY_CONTAINER on network $SMART_PROXY_NETWORK"
    else
      docker rm -f "$SMART_PROXY_CONTAINER" >/dev/null 2>&1 || true
      docker run -d --name "$SMART_PROXY_CONTAINER" --restart unless-stopped --network "$SMART_PROXY_NETWORK" \
        -e LLAMA_URL="$LLAMA_BASE_URL/v1" -e LLAMA_ADMIN="$LLAMA_BASE_URL" -e MAX_OCR_CHARS="24000" \
        "$SMART_PROXY_IMAGE" >/dev/null
    fi
  fi

  write_admin_env "$INSTALL_DIR/admin-model-setup.env" "http://smart-proxy:8081/v1" "llama.cpp/smart-proxy backend"
  log "Done. In Dok OCR open Admin -> Model Setup, click Use internal gateway, Test PaddleOCR-VL, then Save."
  log "Health check: docker exec app-backend-1 curl -fsS http://smart-proxy:8081/v1/models"
}

install_openvino_cpu_stack() {
  need_cmd git
  log "Installing OpenVINO CPU PaddleOCR-VL gateway into $OPENVINO_ROOT"
  run mkdir -p "$OPENVINO_ROOT" "$(dirname "$OPENVINO_MODEL_DIR")"
  run cp "$OPENVINO_SERVER_SRC" "$OPENVINO_ROOT/openvino_paddlevl_server.py"

  if [[ ! -d "$OPENVINO_VENV" ]]; then
    log "Creating Python virtualenv $OPENVINO_VENV"
    run python3 -m venv "$OPENVINO_VENV"
  fi

  if [[ "$DRY_RUN" == 1 ]]; then
    log "Would install OpenVINO 2025.2 CPU dependencies into $OPENVINO_VENV"
  else
    "$OPENVINO_VENV/bin/python" -m pip install --upgrade pip setuptools wheel
    "$OPENVINO_VENV/bin/python" -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
    "$OPENVINO_VENV/bin/python" -m pip install \
      openvino==2025.2.0 openvino-tokenizers==2025.2.0.0 openvino-genai==2025.2.0.0 \
      transformers==4.54.0 pillow psutil requests sentencepiece safetensors numpy tqdm modelscope datasets protobuf accelerate nncf
  fi

  if [[ ! -d "$OPENVINO_REPO_DIR/.git" ]]; then
    log "Cloning PaddleOCR-VL OpenVINO wrapper branch $OPENVINO_UPSTREAM_BRANCH"
    run git clone --depth 1 --branch "$OPENVINO_UPSTREAM_BRANCH" "$OPENVINO_UPSTREAM_REPO" "$OPENVINO_REPO_DIR"
  else
    log "OpenVINO wrapper already exists: $OPENVINO_REPO_DIR"
  fi

  if [[ ! -s "$OPENVINO_MODEL_DIR/llm_stateful.xml" ]]; then
    if [[ "$SKIP_DOWNLOAD" == 1 ]]; then
      log "Skipping OpenVINO model download; missing $OPENVINO_MODEL_DIR/llm_stateful.xml"
    else
      log "Downloading preconverted OpenVINO model $OPENVINO_MODEL_REPO"
      run "$OPENVINO_VENV/bin/modelscope" download --model "$OPENVINO_MODEL_REPO" --local_dir "$OPENVINO_MODEL_DIR"
    fi
  else
    log "OpenVINO model already exists: $OPENVINO_MODEL_DIR"
  fi

  if [[ "$DRY_RUN" == 1 ]]; then
    log "Would write /etc/systemd/system/${OPENVINO_SERVICE_NAME}.service"
  else
    cat > "/etc/systemd/system/${OPENVINO_SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Dok OCR PaddleOCR-VL OpenVINO gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$OPENVINO_ROOT
Environment=PADDLE_OV_MODEL_ID=$OPENVINO_MODEL_ID
Environment=PADDLE_OV_MODEL_PATH=$OPENVINO_MODEL_DIR
Environment=PADDLE_OV_PORT=$OPENVINO_PORT
Environment=PADDLE_OV_MAX_BATCH_SIZE=$OPENVINO_MAX_BATCH_SIZE
ExecStart=$OPENVINO_VENV/bin/python -u $OPENVINO_ROOT/openvino_paddlevl_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
  fi

  if [[ "$START_SERVICES" == 1 ]]; then
    if [[ "$DRY_RUN" == 1 ]]; then
      log "Would enable and start systemd service $OPENVINO_SERVICE_NAME"
    elif command -v systemctl >/dev/null 2>&1; then
      systemctl daemon-reload
      systemctl enable --now "$OPENVINO_SERVICE_NAME"
    else
      log "systemctl not available; start manually: $OPENVINO_VENV/bin/python -u $OPENVINO_ROOT/openvino_paddlevl_server.py"
    fi
  fi

  local gateway
  gateway="$(network_gateway)"
  if [[ -n "$gateway" ]]; then
    write_admin_env "$OPENVINO_ROOT/admin-model-setup.env" "http://${gateway}:${OPENVINO_PORT}/v1" "OpenVINO CPU backend reachable from Dok OCR containers through Docker network gateway $gateway"
    log "Admin PaddleOCR-VL base URL for containers: http://${gateway}:${OPENVINO_PORT}/v1"
  else
    write_admin_env "$OPENVINO_ROOT/admin-model-setup.env" "http://host.docker.internal:${OPENVINO_PORT}/v1" "OpenVINO CPU backend; adjust host name for your Docker setup if needed"
    log "Could not detect Docker gateway for $APP_NETWORK. Use http://host.docker.internal:${OPENVINO_PORT}/v1 if your Docker setup supports it, otherwise use the host gateway IP."
  fi

  log "Done. In Dok OCR open Admin -> Model Setup, set provider paddle_vl, paste the PaddleOCR-VL base URL, Test PaddleOCR-VL, then Save."
  log "Health check: curl -fsS http://127.0.0.1:${OPENVINO_PORT}/health"
  log "Note: OpenVINO 2025.2 is pinned because 2025.3+/2026 CPU wheels have known SIGFPE regressions on some AMD Zen4/KVM hosts."
}

if [[ "$BACKEND" == "openvino-cpu" ]]; then
  install_openvino_cpu_stack
else
  install_llamacpp_stack
fi
