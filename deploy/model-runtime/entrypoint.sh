#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG="${DOKOCR_MODEL_RUNTIME_CONFIG:-/etc/dokocr/llama-swap.config.yaml}"
LISTEN="${DOKOCR_MODEL_RUNTIME_LISTEN:-0.0.0.0:8092}"

need_file() {
  if [[ ! -f "$1" || ! -r "$1" ]]; then
    printf '[dokocr-model-runtime] missing or unreadable %s: %s\n' "$2" "$1" >&2
    return 1
  fi
}

need_file "$CONFIG" "llama-swap config"
for binary in /opt/dokocr/ik-paddle/bin/llama-server /opt/dokocr/ik-lfm/bin/llama-server /opt/dokocr/ik/bin/llama-server; do
  need_file "$binary" "model server"
  [[ -x "$binary" ]] || { printf 'model server is not executable: %s\n' "$binary" >&2; exit 1; }
  "$binary" --version
done
need_file /opt/dokocr/ik-paddle/bin/llama-paddleocr-openvino-dry-run "managed OpenVINO helper"
for model in \
  paddleocr-vl/paddleocr-vl-q8_0.gguf \
  paddleocr-vl/paddleocr-vl-mmproj.gguf \
  paddleocr-vl/paddleocr-vl-chat_template.jinja \
  paddleocr-vl-openvino-direct-pos-0049/model/manifest.json \
  lfm2.5-8b-a1b/LFM2.5-8B-A1B-Q5_K_M.gguf \
  gemma-4-E2B-it-qat-q4_0-gguf/gemma-4-E2B_q4_0-it.gguf \
  gemma-4-E2B-it-qat-q4_0-gguf/google-gemma4-E2B-chat_template-main.jinja; do
  need_file "/models/$model" "model asset"
done

printf '[dokocr-model-runtime] starting reference layout on %s\n' "$LISTEN"
exec /usr/local/bin/llama-swap -config "$CONFIG" -listen "$LISTEN"
