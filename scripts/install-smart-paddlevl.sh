#!/usr/bin/env bash
set -Eeuo pipefail

# One-click installer for Dok OCR smart PaddleOCR-VL stack.
# Installs/updates a local llama.cpp model-manager config, PaddleOCR-VL chat
# template, model files, and smart-proxy container. It is intentionally
# idempotent and does not edit Dok OCR .env or docker-compose.yml.

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
SKIP_DOWNLOAD=0
DRY_RUN=0
START_SERVICES=1

usage() {
  cat <<USAGE
Usage: $0 [--dry-run] [--skip-download] [--no-start]

Environment overrides:
  DOKOCR_SMART_INSTALL_DIR       default: /opt/dokocr-smart-paddlevl
  DOKOCR_MODELS_DIR              default: /root/llm-models
  DOKOCR_PADDLE_MODEL_URL        optional URL for paddleocr-vl-q8_0.gguf
  DOKOCR_PADDLE_MMPROJ_URL       optional URL for paddleocr-vl-mmproj.gguf
  DOKOCR_LLAMA_SERVER_BIN        llama-server binary path
  DOKOCR_SMART_PROXY_NETWORK     Docker network to attach smart-proxy to, default app_default

Examples:
  sudo scripts/install-smart-paddlevl.sh
  sudo DOKOCR_PADDLE_MODEL_URL=https://.../paddleocr-vl-q8_0.gguf \\
       DOKOCR_PADDLE_MMPROJ_URL=https://.../paddleocr-vl-mmproj.gguf \\
       scripts/install-smart-paddlevl.sh
  scripts/install-smart-paddlevl.sh --dry-run --skip-download
USAGE
}

log() { printf "[smart-paddlevl] %s\n" "$*"; }
run() { if [[ "$DRY_RUN" == 1 ]]; then printf "DRY-RUN: %q" "$1"; shift || true; printf " %q" "$@"; printf "\n"; else "$@"; fi; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-download) SKIP_DOWNLOAD=1 ;;
    --no-start) START_SERVICES=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

need_cmd docker
need_cmd python3
need_cmd curl

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY_SRC="$REPO_ROOT/deploy/smart-proxy/proxy_app.py"
TEMPLATE_SRC="$REPO_ROOT/deploy/paddlevl/paddleocr-vl-chat_template.jinja"
MODELS_INI_SRC="$REPO_ROOT/deploy/paddlevl/models.ini"

[[ -f "$PROXY_SRC" ]] || { echo "Missing $PROXY_SRC" >&2; exit 1; }
[[ -f "$TEMPLATE_SRC" ]] || { echo "Missing $TEMPLATE_SRC" >&2; exit 1; }
[[ -f "$MODELS_INI_SRC" ]] || { echo "Missing $MODELS_INI_SRC" >&2; exit 1; }

log "Installing smart PaddleOCR-VL stack into $INSTALL_DIR"
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

if [[ "$DRY_RUN" == 1 ]]; then
  log "Would write $INSTALL_DIR/admin-model-setup.env"
else
  cat > "$INSTALL_DIR/admin-model-setup.env" <<ENV
# Use these values in Admin -> Model Setup -> Use internal gateway
OCR_PROVIDER=paddle_vl
PADDLE_VL_BASE_URL=http://smart-proxy:8081/v1
PADDLE_VL_MODEL=paddleocr-vl
GLM_BASE_URL=http://smart-proxy:8081/v1
GLM_MODEL=glm
QWEN_BASE_URL=http://smart-proxy:8081/v1
ENV
fi

log "Done. In Dok OCR open Admin -> Model Setup, click Use internal gateway, Test PaddleOCR-VL, then Save."
log "Health check: docker exec app-backend-1 curl -fsS http://smart-proxy:8081/v1/models"
